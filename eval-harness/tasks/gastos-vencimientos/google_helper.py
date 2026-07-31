"""Shared Google, fixture, safety, and scoring helpers for the task."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.header import decode_header, make_header
from pathlib import Path
from typing import Any, Iterable

TASK_DIR = Path(__file__).resolve().parent
HARNESS_DIR = TASK_DIR.parent.parent
RUNTIME_PATH = HARNESS_DIR / "results" / "runtime" / "gastos-vencimientos" / "run_state.json"
BENCHMARK_MANIFEST_PATH = TASK_DIR / "benchmark-manifest.json"
TASK_SKILL_DIR = TASK_DIR / "skill"
INSTALLED_EVAL_SKILL_DIR = Path(
    "/home/mcampo/.hermes/profiles/eval/skills/gastos-vencimientos"
)

EVAL_ACCOUNT = "mcampo.agents@gmail.com"
EVAL_SPREADSHEET_ID = "1Qvybe0z_QoI698DRfP1uCjF9f0BcrWLuriaw976mOZs"
EVAL_WORKSHEET_TITLE = "Aux - Previsión"
EVAL_SHEET_ID = 1359523290
EVAL_DRIVE_ROOT_ID = "1zpLE3gXabspesoSPjkO-gGJDZZmF1zXk"
EVAL_DRIVE_ROOT_NAME = "Hermes Eval - Vencimientos"
EXPECTED_PROMPT = "Process unread due-date emails per skill 'gastos-vencimientos'."
EXPECTED_SKILLS = ["gastos-vencimientos", "google-workspace"]
EXPECTED_WEIGHTS = {
    "sheet_target_dispatch": 0.10,
    "due_day_manual_auto": 0.10,
    "ars_semantics": 0.15,
    "usd_semantics": 0.10,
    "drive_archival": 0.20,
    "gmail_lifecycle": 0.15,
    "multi_service_completeness": 0.05,
    "no_collateral_changes": 0.10,
    "final_report": 0.05,
}
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]
FOLDER_MIME = "application/vnd.google-apps.folder"


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_task_config() -> dict:
    value = _load_json(TASK_DIR / "config.json")
    if not isinstance(value, dict):
        raise ValueError("config.json must contain an object")
    return value


def load_expected_fixture() -> dict:
    value = _load_json(TASK_DIR / "fixtures" / "expected.json")
    if not isinstance(value, dict):
        raise ValueError("expected.json must contain an object")
    return value


def load_original_sheet() -> list[list[Any]]:
    value = _load_json(TASK_DIR / "fixtures" / "original_sheet.json")
    if not isinstance(value, list):
        raise ValueError("original_sheet.json must contain a two-dimensional array")
    return value


def load_benchmark_manifest() -> dict:
    value = _load_json(BENCHMARK_MANIFEST_PATH)
    if not isinstance(value, dict):
        raise ValueError("benchmark-manifest.json must contain an object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def skill_tree_sha256(skill_dir: Path) -> str:
    """Match benchmark-manifest.json's sorted sha256sum-record method."""
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"skill directory does not exist: {skill_dir}")
    files = sorted(
        path
        for path in skill_dir.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    )
    records = b"".join(
        f"{file_sha256(path)}  {path.relative_to(skill_dir).as_posix()}\n".encode("utf-8")
        for path in files
    )
    return hashlib.sha256(records).hexdigest()


def benchmark_integrity_errors(
    pinned_manifest: dict,
    *,
    installed_skill_dir: Path = INSTALLED_EVAL_SKILL_DIR,
) -> list[str]:
    errors: list[str] = []
    try:
        current_manifest = load_benchmark_manifest()
        if current_manifest != pinned_manifest:
            errors.append("benchmark-manifest.json changed after task discovery")
    except Exception as exc:
        errors.append(f"benchmark-manifest.json unavailable: {exc}")

    checks = (
        ("expected fixture", TASK_DIR / "fixtures" / "expected.json", "expected_json_sha256"),
        ("validator", TASK_DIR / "validator.py", "validator_sha256"),
        ("Google helper", TASK_DIR / "google_helper.py", "google_helper_sha256"),
    )
    for label, path, key in checks:
        expected_hash = pinned_manifest.get(key)
        if not isinstance(expected_hash, str) or not expected_hash:
            errors.append(f"manifest is missing {key}")
            continue
        try:
            actual_hash = file_sha256(path)
        except Exception as exc:
            errors.append(f"{label} unavailable: {exc}")
            continue
        if actual_hash != expected_hash:
            errors.append(f"{label} SHA-256 mismatch: expected {expected_hash}, got {actual_hash}")

    expected_skill_hash = pinned_manifest.get("evaluation_skill_tree_sha256")
    if not isinstance(expected_skill_hash, str) or not expected_skill_hash:
        errors.append("manifest is missing evaluation_skill_tree_sha256")
        return errors
    for label, path in (
        ("task-local skill", TASK_SKILL_DIR),
        ("installed eval skill", installed_skill_dir),
    ):
        try:
            actual_hash = skill_tree_sha256(path)
        except Exception as exc:
            errors.append(f"{label} unavailable: {exc}")
            continue
        if actual_hash != expected_skill_hash:
            errors.append(
                f"{label} SHA-256 mismatch: expected {expected_skill_hash}, got {actual_hash}"
            )
    return errors


def load_runtime_state(path: Path = RUNTIME_PATH) -> dict:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise ValueError("run_state.json must contain an object")
    return value


def _load_cell_range_module():
    path = TASK_DIR / "skill" / "scripts" / "cell_range.py"
    spec = importlib.util.spec_from_file_location("gastos_eval_cell_range", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import canonical range helper at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CELL_RANGE_MODULE = _load_cell_range_module()
SERVICE_ROWS = dict(_CELL_RANGE_MODULE.SERVICE_ROWS)
MONTH_BLOCKS = dict(_CELL_RANGE_MODULE.MONTH_BLOCKS)


def canonical_range(service: str, month: str) -> str:
    return _CELL_RANGE_MODULE.cell_range(service, month)


def validate_config(config: dict) -> None:
    if config.get("prompt") != EXPECTED_PROMPT:
        raise ValueError("config prompt does not match the approved prompt")
    if config.get("skills") != EXPECTED_SKILLS:
        raise ValueError("config skills must be gastos-vencimientos then google-workspace")
    if config.get("timeout") != 900:
        raise ValueError("config timeout must be 900 seconds")
    google = config.get("google")
    gmail = config.get("gmail")
    sheets = config.get("sheets")
    drive = config.get("drive")
    if not all(isinstance(section, dict) for section in (google, gmail, sheets, drive)):
        raise ValueError("config google/gmail/sheets/drive sections are required")
    if not google.get("token_path"):
        raise ValueError("config google.token_path is required")
    if gmail.get("account") != EVAL_ACCOUNT or gmail.get("label") != "eval":
        raise ValueError("config Gmail account/label does not match the eval corpus")
    if gmail.get("expected_count") != 5:
        raise ValueError("config Gmail expected_count must be 5")
    query = gmail.get("query", "")
    production_query = gmail.get("production_query", "")
    if not query.startswith("label:eval is:unread ") or "newer_than:30d" in query:
        raise ValueError("configured evaluation Gmail query is not isolated")
    if not production_query.startswith("is:unread newer_than:30d ") or "label:eval" in production_query:
        raise ValueError("configured production query is malformed")
    if sheets != {
        "spreadsheet_id": EVAL_SPREADSHEET_ID,
        "worksheet_title": EVAL_WORKSHEET_TITLE,
        "sheet_id": EVAL_SHEET_ID,
    }:
        raise ValueError("configured Sheet identity is not the approved evaluation resource")
    if drive != {"root_name": EVAL_DRIVE_ROOT_NAME, "root_id": EVAL_DRIVE_ROOT_ID}:
        raise ValueError("configured Drive identity is not the approved evaluation resource")


def validate_expected_fixture(expected: dict) -> None:
    if expected.get("fixture_revision") != "eval-label-v2-july":
        raise ValueError("unexpected fixture_revision")
    if expected.get("expected_email_count") != 5 or expected.get("expected_all_read") is not True:
        raise ValueError("expected fixture must describe five final-read messages")
    if expected.get("scoring_weights") != EXPECTED_WEIGHTS:
        raise ValueError("fixture scoring weights do not match the approved rubric")
    items = expected.get("expected_items")
    if not isinstance(items, list) or len(items) != 5:
        raise ValueError("expected_items must contain exactly five entries")
    discriminators: set[str] = set()
    ranges: list[str] = []
    artifact_count = 0
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"expected_items[{index}] must be an object")
        discriminator = item.get("subject_contains")
        if not isinstance(discriminator, str) or not discriminator.strip():
            raise ValueError(f"expected_items[{index}] has no subject discriminator")
        key = discriminator.casefold()
        if key in discriminators:
            raise ValueError(f"duplicate subject discriminator: {discriminator}")
        discriminators.add(key)
        if not isinstance(item.get("type"), str) or not item["type"]:
            raise ValueError(f"expected_items[{index}] has no dispatch type")
        if not isinstance(item.get("expected_final_unread"), bool):
            raise ValueError(f"expected_items[{index}] has invalid final unread state")
        rows = item.get("expected_sheet_rows")
        files = item.get("expected_drive_files")
        if not isinstance(rows, list) or not isinstance(files, list):
            raise ValueError(f"expected_items[{index}] rows/files must be arrays")
        if not files:
            raise ValueError(f"expected_items[{index}] is missing expected Drive artifacts")
        for row in rows:
            required = {
                "service", "month", "range", "due_day", "manual_auto",
                "ars_raw", "ars_formatted", "usd_raw", "usd_formatted",
            }
            if not isinstance(row, dict) or not required.issubset(row):
                raise ValueError(f"malformed expected row for {discriminator}")
            service, month, a1_range = row["service"], row["month"], row["range"]
            if service not in SERVICE_ROWS:
                raise ValueError(f"unknown service in fixture: {service}")
            if month not in MONTH_BLOCKS:
                raise ValueError(f"month outside Junio-Diciembre: {month}")
            if a1_range != canonical_range(service, month):
                raise ValueError(f"noncanonical range for {service}/{month}: {a1_range}")
            if a1_range in ranges:
                raise ValueError(f"duplicate target range: {a1_range}")
            ranges.append(a1_range)
            if not isinstance(row["due_day"], int) or not 1 <= row["due_day"] <= 31:
                raise ValueError(f"invalid due day for {service}/{month}")
            if row["manual_auto"] not in ("", "M", "A"):
                raise ValueError(f"invalid M/A for {service}/{month}")
        for artifact in files:
            if not isinstance(artifact, dict) or set(artifact) != {"name", "year", "month"}:
                raise ValueError(f"malformed expected Drive artifact for {discriminator}")
            if not all(isinstance(artifact[key], str) and artifact[key] for key in artifact):
                raise ValueError(f"empty expected Drive artifact field for {discriminator}")
            if artifact["month"] not in MONTH_BLOCKS:
                raise ValueError(f"Drive artifact month outside Junio-Diciembre: {artifact['month']}")
            if not re.fullmatch(r"20\d{2}", artifact["year"]):
                raise ValueError(f"invalid Drive artifact year: {artifact['year']}")
            artifact_count += 1
    allowed = expected.get("allowed_sheet_ranges")
    if not isinstance(allowed, list) or sorted(allowed) != sorted(ranges):
        raise ValueError("allowed_sheet_ranges must equal the complete canonical row set")
    if artifact_count == 0:
        raise ValueError("fixture must contain expected Drive artifacts")


def validate_original_sheet(original: Any) -> None:
    if not isinstance(original, list) or not original:
        raise ValueError("original_sheet must be a non-empty two-dimensional array")
    for index, row in enumerate(original):
        if not isinstance(row, list):
            raise ValueError(f"original_sheet row {index + 1} is not an array")
        for value in row:
            if not isinstance(value, (str, int, float, bool)) and value is not None:
                raise ValueError(f"unsupported sheet value type: {type(value).__name__}")


def validate_runtime_state(runtime: dict, expected: dict) -> None:
    required = {
        "fixture_revision", "started_at", "gmail_history_id", "messages",
        "sheet_baseline", "resource_ids",
    }
    if not required.issubset(runtime):
        raise ValueError(f"runtime state missing keys: {sorted(required - set(runtime))}")
    if runtime["fixture_revision"] != expected["fixture_revision"]:
        raise ValueError("runtime fixture revision does not match expected fixture")
    messages = runtime["messages"]
    if not isinstance(messages, list) or len(messages) != expected["expected_email_count"]:
        raise ValueError("runtime state must contain exactly five resolved messages")
    ids = [message.get("id") for message in messages if isinstance(message, dict)]
    subjects = [message.get("subject") for message in messages if isinstance(message, dict)]
    if len(ids) != len(set(ids)) or any(not value for value in ids + subjects):
        raise ValueError("runtime message IDs/subjects must be non-empty and unique")
    resource_ids = runtime["resource_ids"]
    if resource_ids != {
        "spreadsheet_id": EVAL_SPREADSHEET_ID,
        "sheet_id": EVAL_SHEET_ID,
        "drive_root_id": EVAL_DRIVE_ROOT_ID,
    }:
        raise ValueError("runtime resource IDs do not match evaluation resources")
    validate_original_sheet(runtime["sheet_baseline"])
    if not str(runtime["gmail_history_id"]).isdigit():
        raise ValueError("runtime Gmail history ID is malformed")


def validate_static_data(config: dict, expected: dict, original: list[list[Any]]) -> None:
    validate_config(config)
    validate_expected_fixture(expected)
    validate_original_sheet(original)


def get_credentials(token_path: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    expanded = Path(os.path.expanduser(token_path))
    if not expanded.is_file():
        raise FileNotFoundError(f"Google OAuth token not found: {expanded}")
    info = _load_json(expanded)
    credentials = Credentials.from_authorized_user_info(info, scopes=GOOGLE_SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials.valid:
        raise RuntimeError("Google OAuth credentials are not valid")
    return credentials


def get_services(credentials) -> dict[str, Any]:
    from googleapiclient.discovery import build

    return {
        "gmail": build("gmail", "v1", credentials=credentials, cache_discovery=False),
        "drive": build("drive", "v3", credentials=credentials, cache_discovery=False),
        "sheets": build("sheets", "v4", credentials=credentials, cache_discovery=False),
    }


def _decode_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _header(payload: dict, name: str) -> str:
    for header in payload.get("headers", []):
        if str(header.get("name", "")).casefold() == name.casefold():
            return _decode_header(str(header.get("value", "")))
    return ""


def _list_message_ids(gmail, query: str) -> list[str]:
    ids: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"userId": "me", "q": query, "maxResults": 100}
        if token:
            kwargs["pageToken"] = token
        response = gmail.users().messages().list(**kwargs).execute()
        ids.extend(str(message["id"]) for message in response.get("messages", []))
        token = response.get("nextPageToken")
        if not token:
            break
    return sorted(set(ids))


def list_eval_messages(gmail, query: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for message_id in _list_message_ids(gmail, query):
        response = gmail.users().messages().get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["Subject", "From", "Date"],
        ).execute()
        payload = response.get("payload", {})
        messages.append({
            "id": message_id,
            "thread_id": str(response.get("threadId", "")),
            "subject": _header(payload, "Subject"),
            "from": _header(payload, "From"),
            "date": _header(payload, "Date"),
            "label_ids": sorted(str(value) for value in response.get("labelIds", [])),
            "snippet": str(response.get("snippet", "")),
        })
    return sorted(messages, key=lambda item: (item["subject"].casefold(), item["id"]))


def resolve_expected_messages(messages: list[dict], expected: dict) -> list[dict]:
    if len(messages) != expected["expected_email_count"]:
        raise ValueError(
            f"eval label contains {len(messages)} messages; expected {expected['expected_email_count']}"
        )
    resolved: list[dict] = []
    used_ids: set[str] = set()
    for item in expected["expected_items"]:
        discriminator = item["subject_contains"].casefold()
        matches = [message for message in messages if discriminator in message["subject"].casefold()]
        if len(matches) != 1:
            raise ValueError(
                f"subject discriminator {item['subject_contains']!r} matched {len(matches)} messages"
            )
        message = dict(matches[0])
        if message["id"] in used_ids:
            raise ValueError("multiple fixture entries resolved to the same Gmail message")
        used_ids.add(message["id"])
        message["fixture_type"] = item["type"]
        message["subject_contains"] = item["subject_contains"]
        resolved.append(message)
    return sorted(resolved, key=lambda item: item["subject_contains"].casefold())


def resolve_gmail_label(gmail, name: str) -> dict:
    labels = gmail.users().labels().list(userId="me").execute().get("labels", [])
    matches = [label for label in labels if str(label.get("name", "")).casefold() == name.casefold()]
    if len(matches) != 1:
        raise ValueError(f"Gmail label {name!r} matched {len(matches)} labels")
    return matches[0]


def mark_messages_unread(gmail, message_ids: Iterable[str]) -> None:
    ids = sorted(set(str(value) for value in message_ids))
    if not ids:
        raise ValueError("refusing to mutate an empty Gmail message set")
    gmail.users().messages().batchModify(
        userId="me", body={"ids": ids, "addLabelIds": ["UNREAD"]}
    ).execute()


def get_message_label_states(gmail, message_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for message_id in sorted(set(str(value) for value in message_ids)):
        response = gmail.users().messages().get(
            userId="me", id=message_id, format="minimal"
        ).execute()
        labels = sorted(str(value) for value in response.get("labelIds", []))
        states[message_id] = {"label_ids": labels, "unread": "UNREAD" in labels}
    return states


def get_gmail_profile(gmail) -> dict:
    return gmail.users().getProfile(userId="me").execute()


def get_gmail_profile_history_id(gmail) -> str:
    value = str(get_gmail_profile(gmail).get("historyId", ""))
    if not value.isdigit():
        raise ValueError(f"invalid Gmail profile history ID: {value!r}")
    return value


def get_gmail_label_change_details(gmail, start_history_id: str) -> dict[str, set[str]]:
    changes: dict[str, set[str]] = {}
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "userId": "me",
            "startHistoryId": str(start_history_id),
            "historyTypes": ["labelAdded", "labelRemoved"],
            "maxResults": 100,
        }
        if token:
            kwargs["pageToken"] = token
        response = gmail.users().history().list(**kwargs).execute()
        for history in response.get("history", []):
            for key, prefix in (("labelsAdded", "+"), ("labelsRemoved", "-")):
                for entry in history.get(key, []):
                    message_id = str(entry.get("message", {}).get("id", ""))
                    if not message_id:
                        continue
                    labels = entry.get("labelIds", [])
                    changes.setdefault(message_id, set()).update(prefix + str(label) for label in labels)
        token = response.get("nextPageToken")
        if not token:
            break
    return {key: changes[key] for key in sorted(changes)}



def quote_sheet_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def sheet_identity(sheets, spreadsheet_id: str, worksheet_title: str) -> dict:
    response = sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        includeGridData=False,
        fields="spreadsheetId,properties(title,locale),sheets(properties(sheetId,title,gridProperties))",
    ).execute()
    matches = [
        sheet["properties"] for sheet in response.get("sheets", [])
        if sheet.get("properties", {}).get("title") == worksheet_title
    ]
    if len(matches) != 1:
        raise ValueError(f"worksheet {worksheet_title!r} matched {len(matches)} tabs")
    return {
        "spreadsheet_id": str(response.get("spreadsheetId", "")),
        "spreadsheet_title": str(response.get("properties", {}).get("title", "")),
        "locale": str(response.get("properties", {}).get("locale", "")),
        **matches[0],
    }


def verify_sheet_identity(sheets, config: dict) -> dict:
    identity = sheet_identity(
        sheets, config["sheets"]["spreadsheet_id"], config["sheets"]["worksheet_title"]
    )
    if identity["spreadsheet_id"] != EVAL_SPREADSHEET_ID:
        raise ValueError("Google returned the wrong evaluation Spreadsheet ID")
    if identity.get("title") != EVAL_WORKSHEET_TITLE or identity.get("sheetId") != EVAL_SHEET_ID:
        raise ValueError("Google returned the wrong evaluation worksheet identity")
    return identity


def _read_sheet(sheets, spreadsheet_id: str, worksheet_title: str, render: str) -> list[list[Any]]:
    response = sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=quote_sheet_title(worksheet_title),
        majorDimension="ROWS",
        valueRenderOption=render,
        dateTimeRenderOption="FORMATTED_STRING",
    ).execute()
    return [list(row) for row in response.get("values", [])]


def read_sheet_formulas(sheets, spreadsheet_id: str, worksheet_title: str) -> list[list[Any]]:
    return _read_sheet(sheets, spreadsheet_id, worksheet_title, "FORMULA")


def read_sheet_formatted(sheets, spreadsheet_id: str, worksheet_title: str) -> list[list[Any]]:
    return _read_sheet(sheets, spreadsheet_id, worksheet_title, "FORMATTED_VALUE")


def sheet_dimensions(values: list[list[Any]]) -> tuple[int, int]:
    return len(values), max((len(row) for row in values), default=0)



def rectangularize(values: list[list[Any]], rows: int, cols: int) -> list[list[Any]]:
    return [
        [(values[r][c] if r < len(values) and c < len(values[r]) else "") for c in range(cols)]
        for r in range(rows)
    ]


def restore_sheet(
    sheets,
    spreadsheet_id: str,
    worksheet_title: str,
    values: list[list[Any]],
) -> None:
    validate_original_sheet(values)
    rows, cols = sheet_dimensions(values)
    if rows < 1 or cols < 1:
        raise ValueError("refusing to restore an empty sheet snapshot")
    quoted = quote_sheet_title(worksheet_title)
    sheets.spreadsheets().values().batchClear(
        spreadsheetId=spreadsheet_id, body={"ranges": [quoted]}
    ).execute()
    target = f"{quoted}!A1:{_CELL_RANGE_MODULE.num_to_col(cols)}{rows}"
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=target,
        valueInputOption="USER_ENTERED",
        body={"majorDimension": "ROWS", "values": values},
    ).execute()
    current = read_sheet_formulas(sheets, spreadsheet_id, worksheet_title)
    if rectangularize(current, rows, cols) != rectangularize(values, rows, cols):
        raise RuntimeError("evaluation sheet formula-mode restore verification failed")
    extra_diffs = compare_sheet_with_allowlist(values, current, [])
    if extra_diffs:
        raise RuntimeError(f"evaluation sheet restore differs outside snapshot: {extra_diffs[0]}")


_A1_RE = re.compile(
    r"^(?:(?:'((?:[^']|'')+)'|([^!]+))!)?([A-Za-z]+)(\d+):([A-Za-z]+)(\d+)$"
)


def parse_a1_range(value: str) -> tuple[str | None, int, int, int, int]:
    match = _A1_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"malformed A1 range: {value}")
    quoted_title, bare_title, start_col, start_row, end_col, end_row = match.groups()
    title = quoted_title.replace("''", "'") if quoted_title is not None else bare_title
    sr, er = int(start_row), int(end_row)
    sc, ec = _CELL_RANGE_MODULE.col_to_num(start_col), _CELL_RANGE_MODULE.col_to_num(end_col)
    if sr < 1 or er < sr or ec < sc:
        raise ValueError(f"invalid A1 range bounds: {value}")
    return title, sr, sc, er, ec


def _cell(values: list[list[Any]], row: int, col: int) -> Any:
    if row < len(values) and col < len(values[row]):
        value = values[row][col]
        return "" if value is None else value
    return ""


def compare_sheet_with_allowlist(
    original: list[list[Any]],
    current: list[list[Any]],
    allowed_ranges: Iterable[str],
) -> list[str]:
    allowed: set[tuple[int, int]] = set()
    for value in allowed_ranges:
        title, sr, sc, er, ec = parse_a1_range(value)
        if title not in (None, EVAL_WORKSHEET_TITLE):
            raise ValueError(f"allowlisted range targets another sheet: {value}")
        allowed.update((row - 1, col - 1) for row in range(sr, er + 1) for col in range(sc, ec + 1))
    max_rows = max(len(original), len(current))
    max_cols = max(
        max((len(row) for row in original), default=0),
        max((len(row) for row in current), default=0),
    )
    differences: list[str] = []
    for row in range(max_rows):
        for col in range(max_cols):
            if (row, col) in allowed:
                continue
            before, after = _cell(original, row, col), _cell(current, row, col)
            if before != after:
                differences.append(
                    f"{_CELL_RANGE_MODULE.num_to_col(col + 1)}{row + 1}: expected {before!r}, actual {after!r}"
                )
    return differences


def get_range_values(values: list[list[Any]], a1_range: str) -> list[list[Any]]:
    title, sr, sc, er, ec = parse_a1_range(a1_range)
    if title not in (None, EVAL_WORKSHEET_TITLE):
        raise ValueError(f"range targets unexpected worksheet: {a1_range}")
    return [
        [_cell(values, row - 1, col - 1) for col in range(sc, ec + 1)]
        for row in range(sr, er + 1)
    ]


def normalize_formula(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or ""))
    return text.upper()


def normalize_number(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float, Decimal)):
        decimal_value = Decimal(str(value))
    else:
        text = str(value).strip().replace("\u00a0", "").replace(" ", "")
        negative = text.startswith("(") and text.endswith(")")
        text = text.strip("()")
        text = text.replace("US$", "").replace("ARS", "").replace("$", "")
        text = re.sub(r"[^0-9,.-]", "", text)
        if not text:
            return ""
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        elif text.count(".") > 1 or (text.count(".") == 1 and len(text.rsplit(".", 1)[1]) == 3):
            text = text.replace(".", "")
        if negative:
            text = "-" + text
        try:
            decimal_value = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"cannot normalize Argentine number: {value!r}") from exc
    if decimal_value == 0:
        return "0"
    return format(decimal_value.normalize(), "f")


def raw_amount_matches(actual: Any, expected: Any) -> bool:
    if str(expected).startswith("="):
        return normalize_formula(actual) == normalize_formula(expected)
    return normalize_number(actual) == normalize_number(expected)


def amount_semantics_match(actual_raw: Any, actual_formatted: Any, expected_raw: Any, expected_formatted: Any) -> bool:
    return raw_amount_matches(actual_raw, expected_raw) and normalize_number(actual_formatted) == normalize_number(expected_formatted)


def score_fraction(weight: float, passed: int, total: int) -> float:
    if total <= 0:
        return float(weight)
    if passed < 0 or passed > total:
        raise ValueError("passed checks must be between zero and total")
    return float(Decimal(str(weight)) * Decimal(passed) / Decimal(total))


def pass_detail(category: str, subject: str, check: str, actual: Any) -> str:
    return f"PASS [{category}] {subject}: {check}; actual={actual!r}"


def fail_detail(category: str, subject: str, check: str, expected: Any, actual: Any) -> str:
    return f"FAIL [{category}] {subject}: {check}; expected={expected!r}; actual={actual!r}"


def drive_root_identity(drive, root_id: str) -> dict:
    return drive.files().get(
        fileId=root_id,
        fields="id,name,mimeType,trashed,parents,webViewLink",
        supportsAllDrives=True,
    ).execute()


def verify_drive_root_identity(drive, config: dict) -> dict:
    root = drive_root_identity(drive, config["drive"]["root_id"])
    if (
        str(root.get("id")) != EVAL_DRIVE_ROOT_ID
        or root.get("name") != EVAL_DRIVE_ROOT_NAME
        or root.get("mimeType") != FOLDER_MIME
        or root.get("trashed") is True
    ):
        raise ValueError("Google returned the wrong evaluation Drive root")
    return root


def _drive_children(drive, parent_id: str) -> list[dict]:
    files: list[dict] = []
    token: str | None = None
    escaped = parent_id.replace("'", "\\'")
    while True:
        kwargs: dict[str, Any] = {
            "q": f"'{escaped}' in parents and trashed=false",
            "pageSize": 100,
            "fields": "nextPageToken,files(id,name,mimeType,parents,trashed,webViewLink,createdTime,modifiedTime,size)",
            "orderBy": "name",
            "spaces": "drive",
        }
        if token:
            kwargs["pageToken"] = token
        response = drive.files().list(**kwargs).execute()
        files.extend(response.get("files", []))
        token = response.get("nextPageToken")
        if not token:
            break
    return sorted(files, key=lambda item: (str(item.get("name", "")).casefold(), str(item.get("id", ""))))


def list_drive_tree(drive, root_id: str) -> list[dict]:
    result: list[dict] = []
    queue: list[tuple[str, str, int]] = [(root_id, "", 0)]
    visited = {root_id}
    while queue:
        parent_id, parent_path, depth = queue.pop(0)
        for child in _drive_children(drive, parent_id):
            child_id = str(child.get("id", ""))
            name = str(child.get("name", ""))
            if not child_id or not name:
                raise ValueError("Drive child is missing id or name")
            relative_path = f"{parent_path}/{name}" if parent_path else name
            entry = {
                "id": child_id,
                "name": name,
                "mime_type": str(child.get("mimeType", "")),
                "parent_id": parent_id,
                "relative_path": relative_path,
                "depth": depth + 1,
                "web_view_link": str(child.get("webViewLink", "")),
                "created_time": str(child.get("createdTime", "")),
                "modified_time": str(child.get("modifiedTime", "")),
                "size": str(child.get("size", "")),
            }
            result.append(entry)
            if entry["mime_type"] == FOLDER_MIME:
                if child_id in visited:
                    raise ValueError(f"Drive folder cycle or duplicate detected at {child_id}")
                visited.add(child_id)
                queue.append((child_id, relative_path, depth + 1))
    return sorted(result, key=lambda item: (item["relative_path"].casefold(), item["id"]))


def trash_drive_descendants(drive, root_id: str) -> None:
    if root_id != EVAL_DRIVE_ROOT_ID:
        raise ValueError("refusing to clean a non-evaluation Drive root")
    entries = sorted(list_drive_tree(drive, root_id), key=lambda item: (-item["depth"], item["id"]))
    for entry in entries:
        if entry["id"] == root_id:
            raise RuntimeError("Drive tree unexpectedly contains its root")
        drive.files().update(
            fileId=entry["id"], body={"trashed": True}, supportsAllDrives=True, fields="id,trashed"
        ).execute()


def expected_drive_paths(expected: dict) -> list[str]:
    paths = {
        f"{artifact['year']}/{artifact['month']}/{artifact['name']}"
        for item in expected["expected_items"]
        for artifact in item["expected_drive_files"]
    }
    return sorted(paths, key=str.casefold)


def expected_drive_tree_paths(expected: dict) -> list[str]:
    paths: set[str] = set()
    for item in expected["expected_items"]:
        for artifact in item["expected_drive_files"]:
            paths.add(artifact["year"])
            paths.add(f"{artifact['year']}/{artifact['month']}")
            paths.add(f"{artifact['year']}/{artifact['month']}/{artifact['name']}")
    return sorted(paths, key=str.casefold)


def actual_drive_paths(tree: list[dict]) -> list[str]:
    return sorted((entry["relative_path"] for entry in tree), key=str.casefold)


def write_runtime_state(runtime: dict, path: Path = RUNTIME_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(runtime, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
