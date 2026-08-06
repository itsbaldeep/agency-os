"""Gmail API client for sending and tracking emails."""

import base64, json, os, sys, time, urllib.request, urllib.parse

from . import gmail_auth


def _get_access_token(campaign_id):
    """Get a valid access token (refreshing if needed) for a campaign."""
    conn = gmail_auth.get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT gmail_token FROM job_campaigns WHERE id=%s", (campaign_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            return None
        token = gmail_auth.decrypt_token(row[0])
        if not token:
            return None

        if token.get("expires_at", 0) < time.time() + 60:
            refresh = token.get("refresh_token")
            if not refresh:
                return None
            new_token = gmail_auth.refresh_token(refresh)
            new_token["refresh_token"] = refresh
            new_token["expires_at"] = time.time() + new_token.get("expires_in", 3600)
            encrypted = gmail_auth.encrypt_token(new_token)
            cur.execute("UPDATE job_campaigns SET gmail_token=%s WHERE id=%s", (encrypted, campaign_id))
            conn.commit()
            token = new_token

        return token.get("access_token")
    finally:
        conn.close()


def send_email(campaign_id, to_email, subject, body_text, cc=None):
    """Send an email via Gmail API. Returns (ok, gmail_message_id_or_error)."""
    access_token = _get_access_token(campaign_id)
    if not access_token:
        return False, "No Gmail token — run gmail_auth.py first"

    # Determine sender from the token's user
    profile = _gmail_api_get(access_token, "https://gmail.googleapis.com/gmail/v1/users/me/profile")
    if not profile:
        return False, "Could not get Gmail profile"
    from_email = profile.get("emailAddress", "me")

    # Build RFC 2822 message
    msg_lines = [
        f"From: {from_email}",
        f"To: {to_email}",
        f"Subject: {subject}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
        "Content-Transfer-Encoding: base64",
        "",
        base64.b64encode(body_text.encode("utf-8")).decode(),
    ]
    if cc:
        msg_lines.insert(3, f"Cc: {cc}")

    raw_msg = base64.urlsafe_b64encode("\r\n".join(msg_lines).encode()).decode()

    result = _gmail_api_post(
        access_token,
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        {"raw": raw_msg},
    )
    if result and result.get("id"):
        return True, result["id"]
    return False, str(result)


def track_thread(campaign_id, gmail_message_id):
    """Track a sent email's status (opened, replied) by checking the thread."""
    access_token = _get_access_token(campaign_id)
    if not access_token:
        return {}

    msg = _gmail_api_get(
        access_token,
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{gmail_message_id}?format=metadata",
    )
    if not msg:
        return {}

    thread_id = msg.get("threadId")
    if not thread_id:
        return {}

    thread = _gmail_api_get(
        access_token,
        f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}?format=minimal",
    )
    if not thread:
        return {}

    messages = thread.get("messages", [])
    return {
        "thread_id": thread_id,
        "total_messages": len(messages),
        "has_reply": len(messages) > 1,
        "last_message_date": messages[-1].get("internalDate") if messages else None,
    }


def list_inbox(campaign_id, max_results=10, query=None):
    """List recent inbox messages."""
    access_token = _get_access_token(campaign_id)
    if not access_token:
        return []

    url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults={max_results}"
    if query:
        url += "&q=" + urllib.parse.quote(query)

    result = _gmail_api_get(access_token, url)
    return result.get("messages", []) if result else []


def _gmail_api_get(access_token, url):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        print(f"[gmail] GET error {e.code}: {body}", flush=True)
        return None
    except Exception as e:
        print(f"[gmail] GET error: {e}", flush=True)
        return None


def _gmail_api_post(access_token, url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        print(f"[gmail] POST error {e.code}: {body}", flush=True)
        return None
    except Exception as e:
        print(f"[gmail] POST error: {e}", flush=True)
        return None
