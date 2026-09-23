import http.client
import socket
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import public_fetch


class _Response:
    def __init__(self, status=200, body=b"ok", headers=None):
        self.status = status
        self._body = body
        self._headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        self.closed = False

    def getheader(self, name, default=None):
        return self._headers.get(name.lower(), default)

    def read(self, amount=-1):
        if amount < 0:
            return self._body
        return self._body[:amount]

    def close(self):
        self.closed = True


class _Connection:
    responses = []
    instances = []

    def __init__(self, host, port, timeout, family, address):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.family = family
        self.address = address
        self.request_args = None
        self.closed = False
        self.response = self.responses.pop(0)
        self.instances.append(self)

    def request(self, method, target, headers=None):
        self.request_args = (method, target, headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class _Socket:
    def __init__(self):
        self.timeout = None
        self.connected = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def connect(self, address):
        self.connected = address

    def setsockopt(self, *_args):
        pass

    def close(self):
        self.closed = True


class _TLSContext:
    def __init__(self):
        self.server_hostname = None
        self.wrapped = None

    def wrap_socket(self, sock, server_hostname=None):
        self.server_hostname = server_hostname
        self.wrapped = sock
        return sock


class PublicFetchTests(unittest.TestCase):
    def setUp(self):
        _Connection.responses = []
        _Connection.instances = []

    def test_private_initial_host_rejected_before_transport(self):
        with patch.object(public_fetch.socket, "getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443)),
        ]) as resolve, patch.object(public_fetch, "_request") as request:
            result = public_fetch.fetch("https://private.example/")
        self.assertEqual(result, {"ok": False, "error": "non_public_address"})
        resolve.assert_called_once()
        request.assert_not_called()

    def test_private_redirect_rejected_and_not_fetched(self):
        _Connection.responses = [
            _Response(302, headers={"Location": "https://internal.example/"}),
        ]

        def resolve(host, port, **kwargs):
            address = "93.184.216.34" if host == "public.example" else "127.0.0.1"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

        with patch.object(public_fetch.socket, "getaddrinfo", side_effect=resolve) as dns, \
             patch.object(public_fetch, "_PinnedHTTPConnection", _Connection):
            result = public_fetch.fetch("http://public.example/")
        self.assertEqual(result, {"ok": False, "error": "non_public_address"})
        self.assertEqual(dns.call_count, 2)
        self.assertEqual(len(_Connection.instances), 1)

    def test_dns_result_is_pinned_once_per_hop(self):
        _Connection.responses = [_Response(200, b"safe")]
        with patch.object(public_fetch.socket, "getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
        ]) as dns, patch.object(public_fetch, "_PinnedHTTPConnection", _Connection):
            result = public_fetch.fetch("http://public.example/")
        self.assertTrue(result["ok"])
        dns.assert_called_once_with("public.example", 80,
                                    family=socket.AF_UNSPEC,
                                    type=socket.SOCK_STREAM)
        self.assertEqual(_Connection.instances[0].address, "93.184.216.34")

    def test_body_limit_rejects_content_length_and_stream_overflow(self):
        _Connection.responses = [_Response(200, b"x", headers={"Content-Length": "4"})]
        with patch.object(public_fetch.socket, "getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
        ]), patch.object(public_fetch, "_PinnedHTTPConnection", _Connection):
            result = public_fetch.fetch("http://public.example/", max_bytes=3)
        self.assertEqual(result, {"ok": False, "error": "body_too_large"})

        _Connection.responses = [_Response(200, b"xxxx")]
        with patch.object(public_fetch.socket, "getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
        ]), patch.object(public_fetch, "_PinnedHTTPConnection", _Connection):
            result = public_fetch.fetch("http://public.example/", max_bytes=3)
        self.assertEqual(result, {"ok": False, "error": "body_too_large"})

    def test_https_keeps_hostname_for_sni_and_host_header(self):
        _Connection.responses = [_Response(200, b"ok", headers={"Content-Type": "text/html"})]
        with patch.object(public_fetch.socket, "getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ]), patch.object(public_fetch, "_PinnedHTTPSConnection", _Connection):
            result = public_fetch.fetch("https://public.example/path?q=1")
        self.assertTrue(result["ok"])
        connection = _Connection.instances[0]
        self.assertEqual(connection.host, "public.example")
        self.assertEqual(connection.address, "93.184.216.34")
        self.assertEqual(connection.request_args[0], "GET")
        self.assertEqual(connection.request_args[1], "/path?q=1")
        self.assertEqual(connection.request_args[2]["Host"], "public.example")

    def test_real_https_connection_pins_ip_but_uses_hostname_for_sni(self):
        sock = _Socket()
        context = _TLSContext()
        with patch.object(public_fetch.ssl, "create_default_context", return_value=context), \
             patch.object(public_fetch, "_connect_socket", return_value=sock) as connect:
            connection = public_fetch._PinnedHTTPSConnection(
                "public.example", 443, 25, socket.AF_INET, "93.184.216.34")
            connection.connect()
        connect.assert_called_once_with(socket.AF_INET, "93.184.216.34", 443, 25, None)
        self.assertEqual(context.server_hostname, "public.example")
        self.assertEqual(connection.host, "public.example")

    def test_errors_do_not_echo_url(self):
        with patch.object(public_fetch.socket, "getaddrinfo", side_effect=OSError("secret.example/path")):
            result = public_fetch.fetch("https://secret.example/path?token=hidden")
        self.assertEqual(result, {"ok": False, "error": "dns_failed"})
        self.assertNotIn("secret", str(result))
        self.assertNotIn("hidden", str(result))


if __name__ == "__main__":
    unittest.main()
