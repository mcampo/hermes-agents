#!/usr/bin/env python3
"""
save_gmail_eml.py — download a Gmail message as .eml (RFC822).

Usage:
    ~/.hermes/.venv/bin/python \
        scripts/save_gmail_eml.py \
        --message-id 19ef51fd8ee82795 \
        --output /tmp/aysa.eml

Output JSON on stdout:
    Success: {"status": "saved", "path": "...", "size": ..., "message_id": "..."}
    Error:   {"status": "error", "error": "...", "message_id": "..."} (exit 1)

Uses the same OAuth token (~/.hermes/google_token.json) as google-workspace,
via build_service('gmail', 'v1').

Key pattern:
    msg = svc.users().messages().get(userId='me', id=ID, format='raw').execute()
    raw_bytes = base64.urlsafe_b64decode(msg['raw'])

Pitfalls:
    - base64.urlsafe_b64decode, NOT b64decode (Gmail uses URL-safe alphabet).
    - The output is the raw RFC822 message: MIME headers + body, ready to archive.
    - If format='full' returns body="" — the content is in an attachment.
      For archiving the whole email, ALWAYS use format='raw'.

Dependency:
    Imports google_api.build_service from the mojo-profile google-workspace skill
    (~/.hermes/profiles/mojo/skills/productivity/google-workspace/scripts/).
"""
import argparse
import base64
import json
import os
import sys

# Google Workspace API wrapper lives in the mojo profile.
sys.path.insert(0, os.path.expanduser(
    '~/.hermes/profiles/mojo/skills/productivity/google-workspace/scripts'
))
from google_api import build_service  # noqa: E402


def save_eml(message_id: str, output_path: str) -> dict:
    svc = build_service('gmail', 'v1')
    msg = svc.users().messages().get(userId='me', id=message_id, format='raw').execute()
    raw_bytes = base64.urlsafe_b64decode(msg['raw'])
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(output_path, flags, 0o600), 'wb') as f:
        f.write(raw_bytes)
    return {
        'status': 'saved',
        'message_id': message_id,
        'path': output_path,
        'size': len(raw_bytes),
    }


def main() -> int:
    p = argparse.ArgumentParser(description='Download a Gmail message as .eml')
    p.add_argument('--message-id', required=True, help='Gmail message ID')
    p.add_argument('--output', required=True, help='Output .eml file path')
    args = p.parse_args()
    try:
        result = save_eml(args.message_id, args.output)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(json.dumps({"status": "error", "error": error_msg, "message_id": args.message_id}, indent=2))
        return 1


if __name__ == '__main__':
    sys.exit(main())
