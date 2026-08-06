#!/usr/bin/env python3
"""Run once to create job search database tables in the existing Postgres."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from worker import get_conn
from jobs.schema import run

conn = get_conn()
try:
    run(conn)
    print("Job search schema setup complete.")
finally:
    conn.close()
