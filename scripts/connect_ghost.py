#!/usr/bin/env python3
"""Create/reuse one Ghost integration; retain its key only in the engagement env."""
import argparse
import http.client
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', required=True)
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    env = root / 'apps/blog/.env'
    if not root.is_relative_to(Path('/home/agency/engagements')) or not env.is_file():
        raise RuntimeError('An existing engagement blog environment is required')
    values = dict(line.split('=', 1) for line in env.read_text().splitlines()
                  if '=' in line and not line.startswith('#'))
    # Reuse the engagement's already-tested local administration transport.
    import importlib.util
    spec = importlib.util.spec_from_file_location('blog_admin', root / 'apps/blog/scripts/manage.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    api = module.Admin()
    api.login(values)
    name = 'Agency OS reviewed publishing'
    integrations = api.request('GET', 'integrations/?include=api_keys&limit=all')['integrations']
    matches = [entry for entry in integrations if entry['name'] == name]
    if len(matches) > 1:
        raise RuntimeError('Duplicate integration names require operator review')
    integration = matches[0] if matches else api.request('POST', 'integrations/?include=api_keys',
        {'integrations': [{'name': name, 'description': 'Publishes individually approved Agency OS articles. No newsletters.'}]})['integrations'][0]
    keys = [key for key in integration.get('api_keys', []) if key['type'] == 'admin']
    if len(keys) != 1:
        raise RuntimeError('Ghost did not return exactly one Admin key')
    secret = keys[0]['secret']
    value = secret if secret.startswith(keys[0]['id'] + ':') else keys[0]['id'] + ':' + secret
    existing = values.get('BLOG_AGENCY_ADMIN_KEY')
    if existing == keys[0]['id'] + ':' + value:
        # Correct a duplicated key-id encoding, not the key or its permissions.
        text = env.read_text().replace('BLOG_AGENCY_ADMIN_KEY=' + existing,
                                       'BLOG_AGENCY_ADMIN_KEY=' + value)
        fd = os.open(env, os.O_WRONLY | os.O_TRUNC)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, text.encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        existing = value
    if existing and existing != value:
        raise RuntimeError('Existing credential differs; refusing replacement')
    if not existing:
        # Generated credentials never pass through terminal output or source patches.
        fd = os.open(env, os.O_WRONLY | os.O_APPEND)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, ('\nBLOG_AGENCY_ADMIN_KEY=' + value + '\n').encode())
            os.fsync(fd)
        finally:
            os.close(fd)
    print(json.dumps({'integration': name, 'credential_stored': True, 'rotated': False}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Ghost connection setup failed. No credential values were logged.')
