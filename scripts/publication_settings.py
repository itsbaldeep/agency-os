"""Non-secret, project-scoped publishing connections shared by UI and worker."""
import json
import hashlib
import os
from pathlib import Path


def destination_digest(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def project_destination(project_id):
    path = Path(os.environ.get('AGENCY_PUBLICATION_CONFIG',
                '/agency-config/publication.json' if Path('/agency-config').exists()
                else str(Path(__file__).resolve().parents[1] / 'config/publication.json')))
    try:
        data = json.loads(path.read_text())
        config = data.get(str(project_id), {})
        return dict(config) if isinstance(config, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}
