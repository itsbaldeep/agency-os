#!/usr/bin/env python3
"""Inspect or deliberately configure the single owned TrueApply GA4 property."""
import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from seo_measurement import SERVICE_ACCOUNT_FILE, sign_jwt

PROPERTY = "properties/553391253"
STREAM = PROPERTY + "/dataStreams/15744559959"
BASE = "https://analyticsadmin.googleapis.com/"
EVENTS = ("sign_up", "kit_completed")


def edit_token():
    account = json.loads(Path(SERVICE_ACCOUNT_FILE).read_text())
    issued = int(time.time())
    assertion = sign_jwt({"alg": "RS256", "typ": "JWT"}, {
        "iss": account["client_email"],
        "scope": "https://www.googleapis.com/auth/analytics.edit",
        "aud": "https://oauth2.googleapis.com/token", "iat": issued, "exp": issued + 3600,
    }, account["private_key"])
    request = urllib.request.Request("https://oauth2.googleapis.com/token", data=
        urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                "assertion": assertion}).encode())
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)["access_token"]


def api(token, path, method="GET", payload=None):
    if not path.startswith(("v1alpha/" + STREAM + "/", "v1beta/" + PROPERTY + "/")):
        raise ValueError("GA4 resource is not allowlisted")
    request = urllib.request.Request(BASE + path, method=method,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def configure(token, *, apply=False, request=api, snapshot=None):
    settings_path = "v1alpha/" + STREAM + "/enhancedMeasurementSettings"
    events_path = "v1beta/" + PROPERTY + "/keyEvents"
    before = {"settings": request(token, settings_path),
              "key_events": request(token, events_path + "?pageSize=200")}
    if before["key_events"].get("nextPageToken"):
        raise ValueError("key event inventory exceeds bounded coverage")
    if snapshot:
        snapshot(before)
    if not apply:
        return {"mode": "inspect", "automatic_measurement_enabled":
                before["settings"].get("streamEnabled", False), "key_events":
                [item.get("eventName") for item in before["key_events"].get("keyEvents", [])]}
    if not snapshot:
        raise ValueError("a pre-change snapshot is required")
    if before["settings"].get("streamEnabled", False) is not False:
        request(token, settings_path + "?updateMask=stream_enabled", "PATCH",
                {"streamEnabled": False})
    existing = {item.get("eventName") for item in before["key_events"].get("keyEvents", [])}
    for event in EVENTS:
        if event not in existing:
            request(token, events_path, "POST", {"eventName": event,
                    "countingMethod": "ONCE_PER_EVENT"})
    after = request(token, settings_path)
    current_events = request(token, events_path + "?pageSize=200")
    current_names = {item.get("eventName") for item in current_events.get("keyEvents", [])}
    if after.get("streamEnabled", False) is not False or not set(EVENTS) <= current_names:
        raise ValueError("GA4 configuration read-back did not verify")
    return {"mode": "apply", "configuration_verified": True,
            "automatic_measurement_enabled": False, "key_events": list(EVENTS),
            "collection_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    directory = Path("/home/agency/backups/releases/trueapply-ga4")
    def snapshot(payload):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + ".json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle)
    try:
        result = configure(edit_token(), apply=args.apply, snapshot=snapshot)
    except urllib.error.HTTPError as error:
        result = {"status": "blocked", "http_status": error.code,
                  "required": "TrueApply property Editor access" if error.code == 403 else
                              "Inspect the owned GA4 API availability"}
    except Exception as error:
        result = {"status": "failed", "error_type": type(error).__name__}
    print(json.dumps(result))
    return 1 if result.get("status") in {"failed", "blocked"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
