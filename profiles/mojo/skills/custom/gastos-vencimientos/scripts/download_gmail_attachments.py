#!/usr/bin/env python3
"""
Download every attachment from a Gmail message.

Usage:
    download_gmail_attachments.py --message-id MSG_ID [--output-dir DIR] [--user me]

Output: JSON to stdout, list of {filename, path, size, mimeType}.

Why this exists: the google-workspace skill's `gmail get` returns an empty
body for messages whose content lives in attachments (the common case for
system-generated emails like expensas, facturas, recibos). This script
walks the payload tree, calls the Gmail attachments endpoint, and decodes
the base64url-encoded data straight to disk.

Dependency:
    Imports google_api.build_service from the mojo-profile google-workspace skill
    (~/.hermes/profiles/mojo/skills/productivity/google-workspace/scripts/).

Uses the same OAuth token:
    - Token:       ~/.hermes/google_token.json
    - Client sec:  ~/.hermes/google_client_secret.json
    - Venv python: $HOME/.hermes/.venv/bin/python
"""

import argparse
import base64
import json
import os
import re
import sys
import tempfile

# Google Workspace API wrapper lives in the mojo profile.
sys.path.insert(0, os.path.expanduser(
    '~/.hermes/profiles/mojo/skills/productivity/google-workspace/scripts'
))
from google_api import build_service  # type: ignore


def _sanitize_filename(filename: str) -> str:
    """Return a safe filename, replacing dangerous patterns.

    - Strips directory separators (/ and \\) and parent references (..)
    - Rejects absolute paths
    - Drops characters that are not safe for cross-platform filenames
    - Falls back to a hash-based name if the result would be empty
    - Truncates to a reasonable length
    """
    if not filename or not filename.strip():
        return "attachment"

    # If the filename is an absolute path, discard it entirely.
    if os.path.isabs(filename):
        return "attachment"

    # Keep only the last path component (basename), discarding any
    # directory traversal injected via MIME filename.
    safe = os.path.basename(filename)

    # Strip out any remaining null bytes and leading dots/hyphens
    # that could hide a file on Linux or be interpreted as flags.
    safe = safe.replace("\0", "")
    safe = safe.lstrip(".-")

    # Remove characters that are unsafe across platforms.
    # Allow: alphanumeric, period, hyphen, underscore, space,
    # and common Spanish accented characters for service names.
    safe = re.sub(r"[^\w .áéíóúñÁÉÍÓÚÑ(),-]", "", safe, flags=re.UNICODE)

    # Collapse multiple spaces / dots into one.
    safe = re.sub(r"\.{2,}", ".", safe)
    safe = re.sub(r"\s{2,}", " ", safe)
    safe = safe.strip()

    if not safe:
        safe = "attachment"

    # Truncate to a reasonable length, preserving the extension.
    MAX_NAME = 200
    if len(safe) > MAX_NAME:
        base, ext = os.path.splitext(safe)
        safe = base[: MAX_NAME - len(ext)] + ext

    return safe


def _resolve_unique_path(output_dir: str, filename: str) -> str:
    """Return an output path that does not collide with existing files.

    If ``filename`` already exists in ``output_dir``, appends a numeric suffix
    before the extension to avoid collisions.
    """
    candidate = os.path.join(output_dir, filename)
    if not os.path.exists(candidate):
        return candidate
    base, ext = os.path.splitext(filename)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(output_dir, f"{base}_{i}{ext}")
        i += 1
    return candidate


def walk_attachments(service, user_id, message_id, part, output_dir, saved):
    """Recursively find every part with an attachmentId and download it."""
    body = part.get("body") or {}
    if body.get("attachmentId"):
        att_id = body["attachmentId"]
        filename = part.get("filename") or f"attachment_{att_id[:8]}"
        att = (
            service.users()
            .messages()
            .attachments()
            .get(userId=user_id, messageId=message_id, id=att_id)
            .execute()
        )
        data = base64.urlsafe_b64decode(att["data"])
        safe_name = _sanitize_filename(filename)
        out_path = _resolve_unique_path(output_dir, safe_name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(out_path, flags, 0o600), "wb") as f:
            f.write(data)
        saved.append(
            {
                "filename": filename,
                "safe_filename": safe_name,
                "path": out_path,
                "size": len(data),
                "mimeType": part.get("mimeType", "application/octet-stream"),
            }
        )
    for sub in part.get("parts") or []:
        walk_attachments(service, user_id, message_id, sub, output_dir, saved)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--message-id", required=True, help="Gmail message ID")
    parser.add_argument("--output-dir", default=None, help="Where to write attachment files (default: a private temporary directory)")
    parser.add_argument("--user", default="me", help="Gmail userId (default: me)")
    args = parser.parse_args()

    if args.output_dir is None:
        args.output_dir = tempfile.mkdtemp(prefix="gastos-vencimientos-")
    else:
        os.makedirs(args.output_dir, exist_ok=True)
    service = build_service("gmail", "v1")
    msg = (
        service.users()
        .messages()
        .get(userId=args.user, id=args.message_id, format="full")
        .execute()
    )

    saved = []
    walk_attachments(service, args.user, args.message_id, msg.get("payload") or {}, args.output_dir, saved)

    print(json.dumps(saved, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
