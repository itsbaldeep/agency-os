import json, os, subprocess, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from scripts import owned_marketing_run as runner

class Cursor:
    def __init__(self, rows): self.rows, self.calls = rows, []
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, args=()): self.calls.append((sql, args))
    def fetchone(self): return self.rows.pop(0) if self.rows else None
class Conn:
    def __init__(self, rows): self.cur, self.commits = Cursor(rows), 0
    def cursor(self): return self.cur
    def commit(self): self.commits += 1
    def close(self): pass

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        (self.root / "prompts").mkdir(); (self.root / "prompts/run.md").write_text("run marketing")
        self.cfg = self.root / "config.json"
        self.cfg.write_text(json.dumps({"schema": 1, "brands": {"31": {"enabled": True, "project_id": 7, "prompt_file": "prompts/run.md", "timeout_seconds": 120}}}))
    def tearDown(self): self.tmp.cleanup()
    def test_dry_run_resolves_prompt_relative_to_config(self):
        self.assertTrue(runner.execute(31, self.cfg, True)["dry_run"])
    def test_active_project_and_tuple_dedup(self):
        result = runner.execute(31, self.cfg, now=datetime(2026,10,25,tzinfo=timezone.utc), db=lambda _: Conn([(31,7),(88,"done",None,{})]))
        self.assertEqual(result["task_id"], 88)
    def test_item_completed_final_and_secret_free_env(self):
        seen = {}
        def fake(command, **kwargs):
            seen.update(kwargs); seen["command"] = command; return subprocess.CompletedProcess(command, 0, '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}\n', '')
        with patch.dict(os.environ, {"OPENAI_API_KEY":"secret", "DEEPSEEK_API_KEY":"secret2"}):
            result = runner.execute(31, self.cfg, db=lambda _: Conn([(31,7),None,(99,)]), runner=fake)
        self.assertTrue(result["ok"]); self.assertNotIn("OPENAI_API_KEY", seen["env"]); self.assertEqual(seen["env"]["CODEX_HOME"], "/home/agency/.codex")
    def test_empty_final_fails(self):
        fake = lambda command, **kwargs: subprocess.CompletedProcess(command, 0, '{"type":"turn.completed"}\n', '')
        result = runner.execute(31, self.cfg, db=lambda _: Conn([(31,7),None,(99,)]), runner=fake)
        self.assertFalse(result["ok"]); self.assertIn("without an assistant final", result["error"])
    def test_timeout_failed(self):
        def fake(*args, **kwargs): raise subprocess.TimeoutExpired(args[0], 120)
        result = runner.execute(31, self.cfg, db=lambda _: Conn([(31,7),None,(99,)]), runner=fake)
        self.assertFalse(result["ok"]); self.assertIn("no automatic retry", result["error"])
    def test_clean_env_drops_credential_names(self):
        env = runner.clean_env({"PATH":"x", "FOO_PASSWORD":"p", "X_TOKEN":"t", "CLIENT_ACCESS_KEY":"a", "LANG":"C"})
        self.assertEqual(set(env), {"PATH", "HOME", "CODEX_HOME", "NO_COLOR", "LANG"})
    def test_workdir_is_passed_to_child(self):
        seen = {}
        def fake(command, **kwargs):
            seen.update(kwargs); seen["command"] = command; return subprocess.CompletedProcess(command, 0, '{"item":{"type":"agent_message","text":"ok"}}', '')
        cfg = json.loads(self.cfg.read_text()); cfg["brands"]["31"]["workdir"] = str(runner.OPERATOR_ROOT / "31"); self.cfg.write_text(json.dumps(cfg))
        runner.execute(31, self.cfg, db=lambda _: Conn([(31,7),None,(99,)]), runner=fake)
        self.assertEqual(seen["cwd"], str(runner.OPERATOR_ROOT / "31"))
        self.assertEqual(seen["command"][seen["command"].index("-C")+1], seen["cwd"])

    def test_finalization_failure_keeps_receipt_and_returns_failure(self):
        class FinalizeFail(Conn):
            def __init__(self, rows): super().__init__(rows); self.n = 0
            def commit(self):
                self.n += 1
                if self.n > 1: raise RuntimeError("db unavailable")
        fake = lambda command, **kwargs: subprocess.CompletedProcess(command, 0, '{"item":{"type":"agent_message","text":"ok"}}', '')
        conn = FinalizeFail([(31,7),None,(99,)])
        result = runner.execute(31, self.cfg, now=datetime(2026,10,25,tzinfo=timezone.utc), db=lambda _: conn, runner=fake)
        self.assertFalse(result["ok"])
        self.assertTrue((runner.STATE / "receipt-31-2026-10-25.json").is_file())
    def test_process_contract_uses_pipes_and_devnull(self):
        class FakeProc:
            pid = 123
            returncode = 0
            def communicate(self, timeout=None): return (b"out", b"err")
        with patch.object(runner.subprocess, "Popen", return_value=FakeProc()) as popen:
            result = runner._process(["fake"], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.stdout, b"out")
        kwargs = popen.call_args.kwargs
        self.assertTrue(kwargs["start_new_session"])
        self.assertIs(kwargs["stdin"], runner.subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], runner.subprocess.PIPE)

if __name__ == "__main__": unittest.main()
