#!/usr/bin/env python3
"""Commit one prepared Gmail transaction in upload→write→verify→read order."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SPREADSHEET_ID = "1Qvybe0z_QoI698DRfP1uCjF9f0BcrWLuriaw976mOZs"
DRIVE_ROOT_ID = "1zpLE3gXabspesoSPjkO-gGJDZZmF1zXk"
DRIVE_ROOT_NAME = "Hermes Eval - Vencimientos"
FOLDER_MIME = "application/vnd.google-apps.folder"


def _pad(values: list[Any] | None, size: int = 4) -> list[Any]:
    result = list(values or [])
    return (result + [""] * size)[:size]


def _normalize_number(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float, Decimal)):
        decimal_value = Decimal(str(value))
    else:
        text = str(value).strip().replace("\u00a0", "").replace(" ", "")
        text = text.replace("US$", "").replace("U$S", "").replace("$", "")
        text = re.sub(r"[^0-9,.-]", "", text)
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            decimal_value = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"cannot normalize number: {value!r}") from exc
    if decimal_value == 0:
        return "0"
    return format(decimal_value.normalize(), "f")


def _formula(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _read_range(sheets, item: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    formulas = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=item["sheet_range"],
        valueRenderOption="FORMULA",
    ).execute().get("values", [])
    numeric = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=item["sheet_range"],
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute().get("values", [])
    return _pad(formulas[0] if formulas else []), _pad(numeric[0] if numeric else [])


def target_state(sheets, item: dict[str, Any]) -> str:
    formulas, numeric = _read_range(sheets, item)
    if all(value in (None, "") for value in formulas):
        return "empty"
    expected = _pad(item["row"][0])
    expected_numeric = _pad(item["expected_numeric_row"])
    checks = [
        _normalize_number(numeric[0]) == _normalize_number(expected_numeric[0]),
        str(formulas[1] or "") == str(expected[1] or ""),
    ]
    if str(expected[2]).startswith("="):
        checks.append(_formula(formulas[2]) == _formula(expected[2]))
    else:
        checks.append(_normalize_number(numeric[2]) == _normalize_number(expected_numeric[2]))
    checks.append(_normalize_number(numeric[3]) == _normalize_number(expected_numeric[3]))
    return "matches" if all(checks) else "conflict"


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _find_child(drive, parent_id: str, name: str, mime_type: str | None = None) -> list[dict]:
    clauses = [
        f"'{_escape_query(parent_id)}' in parents",
        f"name='{_escape_query(name)}'",
        "trashed=false",
    ]
    if mime_type:
        clauses.append(f"mimeType='{_escape_query(mime_type)}'")
    response = drive.files().list(
        q=" and ".join(clauses),
        spaces="drive",
        pageSize=100,
        fields="files(id,name,mimeType,webViewLink,parents,trashed)",
    ).execute()
    return response.get("files", [])


def _ensure_folder(drive, parent_id: str, name: str) -> dict:
    matches = _find_child(drive, parent_id, name, FOLDER_MIME)
    if len(matches) > 1:
        raise RuntimeError(f"duplicate Drive folders named {name!r} under {parent_id}")
    if matches:
        return matches[0]
    return drive.files().create(
        body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
        fields="id,name,mimeType,webViewLink,parents",
        supportsAllDrives=True,
    ).execute()


def _ensure_archive(drive, parent_id: str, archive: dict[str, str]) -> dict:
    matches = _find_child(drive, parent_id, archive["name"])
    if len(matches) > 1:
        raise RuntimeError(f"duplicate Drive files named {archive['name']!r}")
    if matches:
        entry = matches[0]
        if entry.get("mimeType") == FOLDER_MIME:
            raise RuntimeError(f"archive name collides with a folder: {archive['name']}")
        return {**entry, "status": "existing"}
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(archive["local_path"], resumable=False)
    entry = drive.files().create(
        body={"name": archive["name"], "parents": [parent_id]},
        media_body=media,
        fields="id,name,mimeType,webViewLink,parents",
        supportsAllDrives=True,
    ).execute()
    return {**entry, "status": "uploaded"}


def _verify_root(drive) -> None:
    root = drive.files().get(
        fileId=DRIVE_ROOT_ID,
        fields="id,name,mimeType,trashed",
        supportsAllDrives=True,
    ).execute()
    if (
        root.get("id") != DRIVE_ROOT_ID
        or root.get("name") != DRIVE_ROOT_NAME
        or root.get("mimeType") != FOLDER_MIME
        or root.get("trashed") is True
    ):
        raise RuntimeError("configured evaluation Drive root identity failed")


def _upload_archives(
    drive, items: list[dict[str, Any]], uploaded: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    _verify_root(drive)
    folder_cache: dict[tuple[str, str], str] = {}
    uploaded = uploaded if uploaded is not None else []
    for item in items:
        for archive in item["archives"]:
            year_key = (DRIVE_ROOT_ID, archive["year"])
            if year_key not in folder_cache:
                folder_cache[year_key] = _ensure_folder(drive, DRIVE_ROOT_ID, archive["year"])["id"]
            year_id = folder_cache[year_key]
            month_key = (year_id, archive["month"])
            if month_key not in folder_cache:
                folder_cache[month_key] = _ensure_folder(drive, year_id, archive["month"])["id"]
            entry = _ensure_archive(drive, folder_cache[month_key], archive)
            uploaded.append({
                "item_type": item["type"],
                "service": item["service"],
                "name": archive["name"],
                "year": archive["year"],
                "month": archive["month"],
                "id": entry["id"],
                "url": entry.get("webViewLink") or f"https://drive.google.com/file/d/{entry['id']}/view",
                "status": entry["status"],
            })
    return uploaded


def _write_rows(sheets, items: list[dict[str, Any]], states: dict[str, str]) -> None:
    data = [
        {"range": item["sheet_range"], "majorDimension": "ROWS", "values": item["row"]}
        for item in items
        if states[item["sheet_range"]] == "empty"
    ]
    if not data:
        return
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "USER_ENTERED", "data": data},
    ).execute()


def commit_transaction(
    manifest: dict[str, Any],
    *,
    gmail,
    drive,
    sheets,
) -> dict[str, Any]:
    ledger: dict[str, Any] = {
        "ledger_version": 1,
        "message_id": manifest.get("message_id", ""),
        "subject": manifest.get("subject", ""),
        "status": "failed",
        "steps": [],
        "artifacts": [],
        "items": [],
    }
    try:
        items = manifest.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("transaction manifest contains no items")
        if any(item.get("message_id") != manifest.get("message_id") for item in items):
            raise ValueError("item message_id differs from transaction message_id")
        ledger["items"] = [
            {
                "type": item["type"],
                "service": item["service"],
                "due_date": item["due_date"],
                "sheet_range": item["sheet_range"],
                "row": item["row"],
            }
            for item in items
        ]
        states = {item["sheet_range"]: target_state(sheets, item) for item in items}
        conflicts = [a1 for a1, state in states.items() if state == "conflict"]
        if conflicts:
            raise RuntimeError("conflicting target rows: " + ", ".join(conflicts))
        ledger["steps"].append({"name": "target_pre_read", "status": "ok", "states": states})

        _upload_archives(drive, items, ledger["artifacts"])
        ledger["steps"].append({"name": "drive_upload", "status": "ok"})

        _write_rows(sheets, items, states)
        ledger["steps"].append({"name": "sheet_write", "status": "ok"})
        verification = {item["sheet_range"]: target_state(sheets, item) for item in items}
        if any(state != "matches" for state in verification.values()):
            raise RuntimeError(f"Sheet readback mismatch: {verification}")
        ledger["steps"].append({"name": "sheet_verify", "status": "ok"})

        gmail.users().messages().modify(
            userId="me",
            id=manifest["message_id"],
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
        ledger["steps"].append({"name": "gmail_mark_read", "status": "ok"})
        ledger["status"] = "success"
    except Exception as exc:
        ledger["error"] = f"{type(exc).__name__}: {exc}"
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    with Path(args.manifest).open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    google_scripts = os.path.expanduser(
        "~/.hermes/profiles/eval/skills/productivity/google-workspace/scripts"
    )
    sys.path.insert(0, google_scripts)
    from google_api import build_service  # type: ignore
    ledger = commit_transaction(
        manifest,
        gmail=build_service("gmail", "v1"),
        drive=build_service("drive", "v3"),
        sheets=build_service("sheets", "v4"),
    )
    print(json.dumps(ledger, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if ledger["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
