#!/usr/bin/env python3
"""
Caddy on-demand TLS ask endpoint.
Returns 200 if the hostname is live in the dns_records table, 403 otherwise.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import psycopg2
import os

DB = "host=100.64.0.1 port=5432 dbname=agencyos user=agency password=" + \
     os.environ.get("POSTGRES_PASSWORD", "")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        domain = qs.get("domain", [""])[0]
        try:
            conn = psycopg2.connect(DB)
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM dns_records WHERE subdomain=%s AND state='live'",
                (domain,)
            )
            allowed = cur.fetchone() is not None
            conn.close()
        except Exception as e:
            print(f"DB error: {e}")
            allowed = False
        code = 200 if allowed else 403
        self.send_response(code)
        self.end_headers()

    def log_message(self, *args):
        pass  # silence access log

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 9999), Handler).serve_forever()
