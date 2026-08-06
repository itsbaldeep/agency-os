"""
Gmail OAuth 2.0 authentication for sending emails via Gmail API.

Usage:
  1. Set up a Google Cloud project, enable Gmail API, create OAuth 2.0 credentials.
  2. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env
  3. Run: python3 -m jobs.gmail_auth --campaign-id <id>
     This prints a URL. Visit it, authorize, paste the code back.
  4. Token is stored encrypted in job_campaigns.gmail_token
"""

import base64, hashlib, json, os, sys, urllib.request, urllib.parse

ENV_PATH = "/home/agency/agency-os/.env"


def load_env():
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k] = v


load_env()

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


def get_auth_url(state=None):
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    if state:
        params["state"] = state
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def exchange_code(code):
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())


def refresh_token(refresh_token_str):
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token_str,
        "grant_type": "refresh_token",
    }
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())


def get_conn():
    pw = os.environ.get("POSTGRES_PASSWORD") or ""
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "100.64.0.1"),
        dbname="agencyos", user="agency", password=pw,
    )


def _simple_encrypt(text, key):
    """Simple XOR-based obfuscation (not real encryption — use at own risk)."""
    result = bytearray()
    for i, c in enumerate(text.encode("utf-8")):
        result.append(c ^ key[i % len(key)])
    return base64.urlsafe_b64encode(bytes(result)).decode()


def _simple_decrypt(cipher, key):
    try:
        raw = base64.urlsafe_b64decode(cipher.encode())
        result = bytearray()
        for i, c in enumerate(raw):
            result.append(c ^ key[i % len(key)])
        return result.decode("utf-8")
    except Exception:
        return ""


def _get_key():
    return hashlib.sha256(os.environ.get("POSTGRES_PASSWORD", "changeme!").encode()).digest()


def encrypt_token(token_json):
    return _simple_encrypt(json.dumps(token_json), _get_key())


def decrypt_token(encrypted):
    raw = _simple_decrypt(encrypted, _get_key())
    if raw:
        return json.loads(raw)
    return None


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", type=int, required=True)
    args = parser.parse_args()

    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env")
        sys.exit(1)

    print("=" * 60)
    print("Gmail OAuth Authorization")
    print("=" * 60)
    url = get_auth_url(state=str(args.campaign_id))
    print(f"\n1. Open this URL in your browser:\n{url}\n")
    print("2. Authorize the app (use your Gmail account for job search).")
    print("3. Copy the authorization code you receive.")
    code = input("\nPaste authorization code: ").strip()

    token = exchange_code(code)
    print(f"\nToken received. Refresh token present: {'refresh_token' in token}")

    encrypted = encrypt_token(token)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE job_campaigns SET gmail_token=%s, gmail_oauth_state='authorized' WHERE id=%s",
            (encrypted, args.campaign_id),
        )
        conn.commit()
        print(f"Token stored for campaign {args.campaign_id}.")
    except Exception as e:
        print(f"ERROR storing token: {e}")
    finally:
        conn.close()
