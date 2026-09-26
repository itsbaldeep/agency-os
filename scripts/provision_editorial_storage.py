"""Explicit operator provisioning of one isolated public editorial bucket.

Creates a scoped service account, never rotates existing credentials. Credential
output stays in a mode-0600 environment file and never reaches stdout.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def provision(container, bucket, output, access_name, secret_name):
    import re
    if not re.fullmatch(r'[a-z][a-z0-9-]{2,62}', bucket):
        raise ValueError('Invalid dedicated bucket name')
    destination = Path(output)
    if destination.exists():
        raise ValueError('Credential file already exists; refusing to overwrite or rotate')
    policy = {'Version': '2012-10-17', 'Statement': [
        {'Effect': 'Allow', 'Action': ['s3:GetBucketLocation', 's3:ListBucket'], 'Resource': ['arn:aws:s3:::' + bucket]},
        {'Effect': 'Allow', 'Action': ['s3:GetObject', 's3:PutObject'], 'Resource': ['arn:aws:s3:::' + bucket + '/editorial/*']}]}
    public = {'Version': '2012-10-17', 'Statement': [
        {'Effect': 'Allow', 'Principal': {'AWS': ['*']}, 'Action': ['s3:GetObject'], 'Resource': ['arn:aws:s3:::' + bucket + '/editorial/*']}]}
    with tempfile.TemporaryDirectory(prefix='editorial-policy-') as folder:
        for name, data in [('account.json', policy), ('public.json', public)]:
            Path(folder, name).write_text(json.dumps(data))
            subprocess.run(['docker', 'cp', str(Path(folder, name)), container + ':/tmp/editorial-' + name], check=True, capture_output=True)
        # Root credentials already belong to this container. Neither credentials
        # nor the generated service-account response are passed to the chat log.
        command = ('mc alias set editorial-local http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && '
                   'mc mb --ignore-existing editorial-local/' + bucket + ' >/dev/null && '
                   'mc anonymous set-json /tmp/editorial-public.json editorial-local/' + bucket + ' >/dev/null && '
                   'mc admin user svcacct add editorial-local "$MINIO_ROOT_USER" --policy /tmp/editorial-account.json --name editorial-media --json')
        result = subprocess.run(['docker', 'exec', container, 'sh', '-c', command], check=True, capture_output=True, text=True)
        data = json.loads(result.stdout)
        access, secret = data.get('accessKey'), data.get('secretKey')
        if not access or not secret:
            raise RuntimeError('Service account response did not contain credentials')
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(access_name + '=' + access + '\n' + secret_name + '=' + secret + '\n')
    print(json.dumps({'ok': True, 'container': container, 'bucket': bucket, 'credential_file': str(destination), 'scope': 'editorial prefix read/write; anonymous read only'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', required=True)
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--access-name', default='PUBLIC_MEDIA_ACCESS_KEY')
    parser.add_argument('--secret-name', default='PUBLIC_MEDIA_SECRET_KEY')
    args = parser.parse_args()
    try:
        provision(args.container, args.bucket, args.output, args.access_name, args.secret_name)
    except Exception as exc:
        # Subprocess errors can contain credential output, so expose type only.
        raise SystemExit('Provisioning failed: ' + type(exc).__name__)
