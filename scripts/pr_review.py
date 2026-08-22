#!/usr/bin/env python3
"""pr_review.py — ensemble machine review of a code diff.

Single source of truth for the review rubric. Shared by:
  * worker.py  handle_propose_fix  (pre-PR refine loop and post-PR check)
  * explicit proposal workflows   (bounded review before a human merge)

Review axes: BLOCKERS (crashes/logic/security/syntax) + ACCURACY (fully solves
the stated task) + CONVENTIONS (fits codebase style, no over-engineering).

CLI:  pr_review.py <repo> <pr_number>
    exit 0 = CLEAN, 1 = DEFECTS (hold label applied), 2 = error.
"""
import os, sys, json, urllib.request, urllib.error

ENV_PATH = os.environ.get("AGENCY_ENV_FILE", "/home/agency/.config/agency/core.env")


def load_env():
    try:
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ[k] = v
    except Exception:
        pass


load_env()

ZEN_URL = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/chat/completions"
ZEN_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# Fixer first, independent critic second — heterogeneous ensemble.
REVIEW_MODELS = ["deepseek-v4-flash", "deepseek-v4-pro"]

# Rough USD pricing for cost accounting.
_PRICES = {
    "deepseek-v4-flash": {"in": 0.14 / 1_000_000, "out": 0.28 / 1_000_000},
    "deepseek-v4-pro": {"in": 0.435 / 1_000_000, "out": 0.87 / 1_000_000},
}

REVIEW_PROMPT = (
    "You are performing a code review of a diff before human review. "
    "Judge against three axes:\n"
    "1. BLOCKERS: crashes, wrong logic, security issues, invalid syntax, broken invocations.\n"
    "2. ACCURACY: does the change fully and correctly solve the stated task? "
    "Call out missed edge cases, incorrect assumptions, or a partial fix.\n"
    "3. CONVENTIONS: does it fit the codebase's existing style and patterns "
    "(reuse the libraries already in use, don't reinvent the standard library)? "
    "Flag unnecessary complexity / over-engineering.\n"
    "List concrete, actionable findings, each on its own numbered line; if nothing "
    "should change, write 'No changes required.'. "
    "Your reply MUST end with a final line that is exactly VERDICT: CLEAN "
    "or exactly VERDICT: DEFECTS."
)


def call_zen(prompt, model, max_tokens=4000, timeout=90):
    """Return (content, tokens_in, tokens_out)."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
    }).encode()
    req = urllib.request.Request(
        ZEN_URL, data=body,
        headers={"Authorization": f"Bearer {ZEN_KEY}",
                 "Content-Type": "application/json",
                 "User-Agent": "AgencyOS-pr-review/1.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read())
        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})
        return (choice.get("message", {}).get("content", "") or "",
                usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    except Exception:
        return "", 0, 0


def parse_verdict(content):
    """Find the trailing VERDICT marker leniently (case-insensitive, may precede
    trailing prose). Returns ('CLEAN'|'DEFECTS'|'UNCLEAR', note)."""
    import re
    m = re.findall(r"VERDICT:\s*(CLEAN|DEFECTS)", content or "", re.IGNORECASE | re.DOTALL)
    if not m:
        return "UNCLEAR", (content or "").strip()[:600]
    final = m[-1].upper()
    if final == "CLEAN":
        return "CLEAN", ""
    # Keep the full review body — no truncation of the review text itself.
    return "DEFECTS", (content or "").rstrip()


def _review_model(prompt, model):
    """Call a model, retrying once on a non-verdict reply. Returns
    (verdict, note, tokens_in, tokens_out) and the running cost."""
    content, i, o = call_zen(prompt, model)
    verdict, note = parse_verdict(content)
    if verdict == "UNCLEAR":
        content2, i2, o2 = call_zen(prompt, model)
        i += i2
        o += o2
        verdict, note = parse_verdict(content2)
    p = _PRICES.get(model, {"in": 0.15 / 1_000_000, "out": 0.60 / 1_000_000})
    return verdict, note, i, o, i * p["in"] + o * p["out"]


DIFF_BUDGET = 60000  # chars of unified diff fed to reviewers (avoids 9000-char false holds)


def review_diff(diff_text, description, problem="", diff_names=""):
    """Ensemble review. Returns (clean, findings, tokens_in, tokens_out, cost, notes).

    clean: True unless any model explicitly returned VERDICT: DEFECTS.
    findings: consolidated DEFECTS feedback to feed back into the fixer.
    notes: per-model verdict lines for humans. UNCLEAR counts as non-blocking.
    """
    manifest = f"\nChanged files:\n{diff_names or '(unknown)'}" if diff_names else ""
    prompt = REVIEW_PROMPT + (
        f"\nTask: {description}"
        + (f"\nEarlier reviewer feedback the author must address:\n{problem}" if problem else "")
        + manifest
        + f"\nDiff:\n{diff_text[:DIFF_BUDGET]}"
    )
    clean = True
    findings = []
    notes = []
    tin = tout = 0
    cost = 0.0
    for m in REVIEW_MODELS:
        verdict, note, i, o, c = _review_model(prompt, m)
        tin += i
        tout += o
        cost += c
        if verdict == "DEFECTS":
            clean = False
            if note:
                findings.append(f"[{m}] {note}")
        notes.append(f"[{m}:{verdict}]")
    return clean, "\n\n".join(findings).strip()[:8000], tin, tout, round(cost, 8), " ".join(notes)


def gh_api(path, method="GET", data=None, accept=None):
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "AgencyOS-pr-review/1.0"}
    if accept:
        headers["Accept"] = accept
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"https://api.github.com{path}", data=body, method=method, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        raw = resp.read()
        try:
            return json.loads(raw)
        except Exception:
            return raw.decode(errors="replace")
    except urllib.error.HTTPError as e:
        return None if e.code == 404 else {"_error": e.code, "_body": e.read().decode(errors="replace")[:500]}


def main():
    if len(sys.argv) != 3:
        sys.stderr.write("usage: pr_review.py <repo> <pr_number>\n")
        return 2
    repo, pr = sys.argv[1], int(sys.argv[2])
    owner = os.environ.get("GITHUB_OWNER", "itsbaldeep")
    pull = gh_api(f"/repos/{owner}/{repo}/pulls/{pr}")
    if not pull or isinstance(pull, str) or "_error" in pull:
        sys.stderr.write(f"could not load PR {repo}#{pr}\n")
        return 2
    diff = gh_api(f"/repos/{owner}/{repo}/pulls/{pr}", accept="application/vnd.github.diff")
    if not diff:
        sys.stderr.write(f"empty diff for {repo}#{pr}\n")
        return 2
    files = gh_api(f"/repos/{owner}/{repo}/pulls/{pr}/files")
    names = "\n".join(str(f.get("filename", "")) for f in files) if isinstance(files, list) else ""
    description = f"{pull.get('title','')}\n{(pull.get('body') or '')[:2000]}"
    clean, findings, tin, tout, cost, notes = review_diff(diff, description, diff_names=names)
    if clean:
        print(f"PR #{pr} {notes} OUTCOME CLEAN (${cost:.6f})")
        return 0
    label = str(pull.get("labels") or [])
    if "hold" not in label:
        gh_api(f"/repos/{owner}/{repo}/issues/{pr}/labels", method="POST",
               data={"labels": ["hold"]})
        gh_api(f"/repos/{owner}/{repo}/issues/{pr}/comments", method="POST",
               data={"body": "🔍 Machine review flagged DEFECTS — human merge should remain blocked.\n\n"
                              f"{findings or 'see below'}"})
    print(f"PR #{pr} {notes} OUTCOME DEFECTS (${cost:.6f})\n{findings}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
