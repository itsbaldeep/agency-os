import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import marketing_email_provider as provider


class Response:
    def __init__(self, value, status=200): self.body, self.status = json.dumps(value).encode(), status
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, size=-1): return self.body[:size]


class Cursor:
    def __init__(self, row): self.row, self.calls = row, []
    def execute(self, sql, params=()): self.calls.append((sql, params))
    def fetchone(self): return self.row


class Conn:
    def __init__(self, row): self.cur, self.commits = Cursor(row), 0
    def cursor(self, **kwargs): return self.cur
    def commit(self): self.commits += 1
    def rollback(self): pass
    def close(self): pass


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        patcher = mock.patch.object(provider, 'ENGAGEMENT_ROOT', Path('/tmp'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cred = self.root / ".env"
        self.cred.write_text("BREVO_KEY=fixture-value\n")
        self.cred.chmod(0o600)
        self.config = {"provider": "brevo", "credential_ref": str(self.cred), "credential_name": "BREVO_KEY", "sender_email": "owner@example.com"}
        self.project = {"classification": "engagement", "local_path": str(self.root)}
        self.digest = provider.config_digest(self.config)
    def tearDown(self): self.tmp.cleanup()

    def opener(self, request, timeout=0):
        return Response({"user_id": 4, "plan": []}) if request.full_url.endswith("/account") else Response({"senders": [{"email": "owner@example.com", "active": True}]})

    def test_verify_is_read_only_and_sanitized(self):
        calls = []
        def opener(request, timeout=0):
            calls.append((request.full_url, request.method, timeout))
            if request.full_url.endswith('/account'):
                return Response({'user_id': 4, 'plan': [], 'email': 'private@example.com', 'relay': {'password': 'sensitive-response'}})
            return self.opener(request, timeout)
        result = provider.verify(self.config, self.project, opener)
        self.assertEqual(result["authenticated"], True); self.assertEqual(result["sender_verified"], True)
        self.assertNotIn("fixture-value", json.dumps(result))
        self.assertNotIn('sensitive-response', json.dumps(result))
        self.assertNotIn('private@example.com', json.dumps(result))
        self.assertEqual(calls, [(provider.BREVO_ACCOUNT_URL, 'GET', 15), (provider.BREVO_SENDERS_URL, 'GET', 15)])

    def test_oversized_and_malformed_response_rejected(self):
        for raw in (b'x' * (provider.MAX_RESPONSE_BYTES + 1), b'{broken', b'[]'):
            response = Response({}); response.body = raw
            result = provider.verify(self.config, self.project, lambda *a, **k: response)
            self.assertFalse(result['authenticated'])

    def test_redirect_response_rejected_without_credential_forwarding(self):
        class Redirect:
            status = 302
            def read(self, size=-1): return b'{}'
            def __enter__(self): return self
            def __exit__(self, *args): pass
        result = provider.verify(self.config, self.project, lambda *a, **k: Redirect())
        self.assertFalse(result['authenticated'])

    def test_path_traversal_and_directory_reference_rejected(self):
        with self.assertRaises(ValueError):
            provider.validate_config({**self.config, 'credential_ref': str(self.root / '..' / 'outside.env')})
        with self.assertRaises(ValueError):
            provider.read_credential({**self.config, 'credential_ref': str(self.root)}, self.project)

    def test_parent_symlink_rejected(self):
        owned = self.root / 'owned'; owned.mkdir()
        secret = owned / '.env'; secret.write_text('BREVO_KEY=fixture-value'); secret.chmod(0o600)
        link = self.root / 'alias'; link.symlink_to(owned, target_is_directory=True)
        with self.assertRaises(ValueError):
            provider.read_credential({**self.config, 'credential_ref': str(link / '.env')}, self.project)

    def test_fifo_cannot_block_verification(self):
        fifo = self.root / 'pipe'; os.mkfifo(fifo, 0o600)
        with self.assertRaises(ValueError):
            provider.read_credential({**self.config, 'credential_ref': str(fifo)}, self.project)

    def test_configuration_accepts_references_only(self):
        for config in ({**self.config, 'api_key': 'forbidden'},
                       {**self.config, 'sender_email': 'owner@localhost'},
                       {**self.config, 'credential_name': 'ÄPI_KEY'}):
            with self.assertRaises(ValueError): provider.validate_config(config)

    def test_bad_http_redirect_network_oversize_and_json_fail_closed(self):
        for error in (provider.urllib.error.HTTPError("x", 401, "", {}, io.BytesIO()), provider.urllib.error.URLError("x")):
            result = provider.verify(self.config, self.project, lambda *a, error=error, **k: (_ for _ in ()).throw(error))
            self.assertFalse(result["authenticated"])
        result = provider.verify(self.config, self.project, lambda *a, **k: Response({"user_id": 1, "plan": []}) if a[0].full_url.endswith("/account") else Response({"senders": []}))
        self.assertFalse(result["sender_verified"])

    def test_validation_paths_permissions_and_symlink(self):
        with self.assertRaises(ValueError): provider.read_credential({**self.config, "credential_ref": "/etc/passwd"}, self.project)
        self.cred.chmod(0o644)
        with self.assertRaises(ValueError): provider.read_credential(self.config, self.project)
        self.cred.chmod(0o600)
        link = self.root / "link"; link.symlink_to(self.cred)
        with self.assertRaises(ValueError): provider.read_credential({**self.config, "credential_ref": str(link)}, self.project)

    def test_stale_task_and_handler_persists_only_safe_result(self):
        conn = Conn({"id": 4, "project_id": 8, "local_path": str(self.root), "classification": "engagement", "lifecycle": "active", "value": json.dumps(self.config)})
        result = provider.handle({"params": {"brand_id": 4, "config_digest": "0" * 64}}, lambda: conn)
        self.assertFalse(result["ok"]); self.assertEqual(conn.commits, 0)
        conn = Conn({"id": 4, "project_id": 8, "local_path": str(self.root), "classification": "engagement", "lifecycle": "active", "value": json.dumps(self.config)})
        with mock.patch.object(provider, "verify", return_value={"authenticated": True, "sender_verified": True, "checked_at": "now", "error": None}):
            result = provider.handle({"params": {"brand_id": 4, "config_digest": self.digest}}, lambda: conn)
        self.assertTrue(result["ok"]); self.assertEqual(conn.commits, 1); self.assertNotIn("fixture-value", result["content"])


if __name__ == "__main__": unittest.main()
