#!/usr/bin/env python3
"""Validate observable eval Sheet, Drive, Gmail, and final-report state."""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import google_helper as helper


_PINNED_BENCHMARK_MANIFEST = helper.load_benchmark_manifest()


def _failure(message: str) -> dict:
    return {"score": 0.0, "details": [message]}


def _item_message(item: dict, runtime_messages: list[dict]) -> dict:
    discriminator = item["subject_contains"].casefold()
    matches = [
        message for message in runtime_messages
        if discriminator in str(message.get("subject", "")).casefold()
    ]
    if len(matches) != 1:
        raise ValueError(
            f"runtime subject discriminator {item['subject_contains']!r} matched {len(matches)} messages"
        )
    return matches[0]


def _row_status(row: dict, formulas: list[list[Any]], formatted: list[list[Any]]) -> dict[str, Any]:
    actual_raw = helper.get_range_values(formulas, row["range"])[0]
    actual_formatted = helper.get_range_values(formatted, row["range"])[0]
    target = any(value not in (None, "") for value in actual_raw)
    return {
        "raw": actual_raw,
        "formatted": actual_formatted,
        "target": target,
        "due": target and helper.normalize_number(actual_raw[0]) == helper.normalize_number(row["due_day"]),
        "manual_auto": target and str(actual_raw[1] or "") == row["manual_auto"],
        "ars": target and helper.amount_semantics_match(
            actual_raw[2], actual_formatted[2], row["ars_raw"], row["ars_formatted"]
        ),
        "usd": target and helper.amount_semantics_match(
            actual_raw[3], actual_formatted[3], row["usd_raw"], row["usd_formatted"]
        ),
    }


def _expected_file_path(artifact: dict) -> str:
    return f"{artifact['year']}/{artifact['month']}/{artifact['name']}"


def _created_after(entry: dict, started_at: str) -> bool:
    try:
        created = datetime.fromisoformat(entry["created_time"].replace("Z", "+00:00"))
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        return created >= started
    except (KeyError, TypeError, ValueError):
        return True


_FINAL_REPORT_START = re.compile(
    r"(?im)^[ \t]*(?:✅|⚠️|❌|\[SILENT\]|(?:issues?|problemas?|sin procesar|processed|procesad(?:o|os|a|as)|completed|completad(?:o|os|a|as))\b)"
)


_NEGATED_ISSUE_PHRASE = re.compile(
    r"(?i)\b(?:no|without|sin)\s+(?:known\s+)?(?:issues?|problems?|errors?|problemas?|errores?)\b"
)
_POSITIVE_ISSUE_MARKER = re.compile(
    r"(?i)(?:\b(?:issues?|problems?|errors?|failed?|failures?|unprocessed|unread|sin\s+procesar|no\s+(?:pude|pudo|procesad[oa]s?)|fall[oó]|fallaron|vencid[oa]s?|expir(?:ed|ad[oa]s?))\b|⚠️|❌)"
)


def _has_positive_issue_claim(output: str) -> bool:
    """Ignore only explicit negations; keep all genuine issue markers strict."""
    without_negated_phrases = _NEGATED_ISSUE_PHRASE.sub("", output)
    return bool(_POSITIVE_ISSUE_MARKER.search(without_negated_phrases))


def _final_response(agent_output: str) -> str:
    """Discard Hermes review/tool transcript content when it precedes a final reply."""
    output = agent_output.strip()
    if not output:
        return ""
    if "review diff" not in output.casefold() and "┊ review diff" not in output.casefold():
        return output
    starts = list(_FINAL_REPORT_START.finditer(output))
    if not starts:
        return ""
    return output[starts[-1].start():].strip()


def _transaction_order_failure(
    agent_output: str,
    expected: dict,
    row_statuses: dict[str, dict],
    drive_by_path: dict[str, list[dict]],
    runtime: dict,
) -> str | None:
    lines = [line.casefold() for line in agent_output.splitlines()]
    failure_words = re.compile(r"\b(error|fail|failed|fall[oó]|vencid[oa]|expired|no pude|no se pudo)\b")
    early_step_words = re.compile(r"\b(descarg|download|extra|parse|pdf|adjunto|attachment|drive|upload|subir)\w*")
    for item in expected["expected_items"]:
        tokens = {
            item["type"].replace("_", " ").casefold(),
            item["subject_contains"].casefold(),
        }
        relevant_failures = [
            line for line in lines
            if any(token in line for token in tokens) and failure_words.search(line) and early_step_words.search(line)
        ]
        if not relevant_failures:
            continue
        new_artifact = any(
            _created_after(entry, runtime["started_at"])
            for artifact in item["expected_drive_files"]
            for entry in drive_by_path.get(_expected_file_path(artifact), [])
        )
        changed_row = any(
            helper.get_range_values(runtime["sheet_baseline"], row["range"])[0] != row_statuses[row["range"]]["raw"]
            for row in item["expected_sheet_rows"]
        )
        if new_artifact or changed_row:
            return (
                f"HARD FAIL [transaction_order] {item['subject_contains']}: output reports an earlier "
                "required-step failure but a later Sheet/archive mutation is observable"
            )
    return None


def _final_report_passes(
    agent_output: str,
    all_artifacts_pass: bool,
    expected: dict,
    drive_by_path: dict[str, list[dict]],
) -> tuple[bool, str]:
    output = _final_response(agent_output)
    if not output or output == "[SILENT]":
        return False, "missing non-silent success/issues summary"
    success_marker = bool(re.search(
        r"(?i)(?:\b(?:processed|procesad(?:o|os|a|as)|completed|completad(?:o|os|a|as)|success(?:fully)?|archivad(?:o|os|a|as))\b|✅)",
        output,
    ))
    issue_marker = _has_positive_issue_claim(output)
    summary_ok = success_marker and not issue_marker if all_artifacts_pass else issue_marker
    missing_links: list[str] = []
    absent_artifacts: list[str] = []
    for item in expected["expected_items"]:
        for artifact in item["expected_drive_files"]:
            path = _expected_file_path(artifact)
            entries = drive_by_path.get(path, [])
            if len(entries) != 1:
                absent_artifacts.append(path)
                continue
            entry = entries[0]
            if "drive.google.com" not in output or entry["id"] not in output:
                missing_links.append(path)
    failures: list[str] = []
    if not summary_ok:
        failures.append("summary does not match the observed success/issues state")
    if missing_links:
        failures.append(
            "missing links for present Drive artifacts: "
            + ", ".join(sorted(missing_links, key=str.casefold))
        )
    if failures:
        if absent_artifacts:
            failures.append(
                "observed absent or non-unique expected artifacts: "
                + ", ".join(sorted(absent_artifacts, key=str.casefold))
            )
        return False, "; ".join(failures)
    reason = "summary matches observed state and links every present expected Drive artifact"
    if absent_artifacts:
        reason += "; observed absent or non-unique expected artifacts: " + ", ".join(
            sorted(absent_artifacts, key=str.casefold)
        )
    return True, reason


def validate(agent_output: str) -> dict:
    details: list[str] = []
    try:
        integrity_errors = helper.benchmark_integrity_errors(_PINNED_BENCHMARK_MANIFEST)
    except Exception as exc:
        return _failure(f"HARD FAIL [benchmark_integrity] integrity check failed: {exc}")
    if integrity_errors:
        return _failure(
            "HARD FAIL [benchmark_integrity] benchmark source changed during run: "
            + " | ".join(integrity_errors)
        )
    details.append("PASS [benchmark_integrity] pinned task and installed eval-skill source are unchanged")

    try:
        config = helper.load_task_config()
        expected = helper.load_expected_fixture()
        original = helper.load_original_sheet()
        runtime = helper.load_runtime_state()
        helper.validate_static_data(config, expected, original)
        helper.validate_runtime_state(runtime, expected)
    except Exception as exc:
        return _failure(f"HARD FAIL [state] missing or invalid task/runtime state: {exc}")

    try:
        credentials = helper.get_credentials(config["google"]["token_path"])
        services = helper.get_services(credentials)
        gmail, drive, sheets = services["gmail"], services["drive"], services["sheets"]
        profile = helper.get_gmail_profile(gmail)
        if str(profile.get("emailAddress", "")).casefold() != config["gmail"]["account"].casefold():
            raise RuntimeError("authenticated Gmail account is not the configured eval account")
        helper.verify_sheet_identity(sheets, config)
        helper.verify_drive_root_identity(drive, config)
        formulas = helper.read_sheet_formulas(
            sheets, config["sheets"]["spreadsheet_id"], config["sheets"]["worksheet_title"]
        )
        formatted = helper.read_sheet_formatted(
            sheets, config["sheets"]["spreadsheet_id"], config["sheets"]["worksheet_title"]
        )
        tree = helper.list_drive_tree(drive, config["drive"]["root_id"])
        runtime_ids = [message["id"] for message in runtime["messages"]]
        label_states = helper.get_message_label_states(gmail, runtime_ids)
        label_changes = helper.get_gmail_label_change_details(gmail, runtime["gmail_history_id"])
    except Exception as exc:
        return _failure(f"HARD FAIL [observation] evaluation safety could not be verified: {exc}")

    sheet_differences = helper.compare_sheet_with_allowlist(
        original, formulas, expected["allowed_sheet_ranges"]
    )
    if sheet_differences:
        return _failure(
            "HARD FAIL [sheet_safety] non-allowlisted evaluation cell changed: "
            + " | ".join(sheet_differences)
        )
    details.append("PASS [sheet_safety] no non-allowlisted evaluation Sheet cells changed")

    runtime_id_set = set(runtime_ids)
    outside_changes = sorted(set(label_changes) - runtime_id_set)
    if outside_changes:
        return _failure(
            "HARD FAIL [gmail_safety] label changes observed outside the five fixture messages: "
            + ", ".join(outside_changes)
        )
    details.append("PASS [gmail_safety] Gmail label history is limited to the five fixture messages")

    drive_by_path: dict[str, list[dict]] = {}
    for entry in tree:
        drive_by_path.setdefault(entry["relative_path"], []).append(entry)

    row_statuses: dict[str, dict[str, Any]] = {}
    for item in expected["expected_items"]:
        _item_message(item, runtime["messages"])
        for row in item["expected_sheet_rows"]:
            row_statuses[row["range"]] = _row_status(row, formulas, formatted)

    final_response = _final_response(agent_output)
    order_failure = _transaction_order_failure(
        final_response, expected, row_statuses, drive_by_path, runtime
    )
    if order_failure:
        return _failure(order_failure)

    weights = expected["scoring_weights"]
    score = 0.0

    target_passed = 0
    target_total = 0
    due_ma_passed = 0
    due_ma_total = 0
    ars_passed = 0
    ars_total = 0
    usd_passed = 0
    usd_total = 0
    all_rows_pass = True

    for item in expected["expected_items"]:
        subject = item["subject_contains"]
        for row in item["expected_sheet_rows"]:
            status = row_statuses[row["range"]]
            target_total += 1
            if status["target"]:
                target_passed += 1
                details.append(helper.pass_detail("sheet_target_dispatch", subject, row["range"], status["raw"]))
            else:
                all_rows_pass = False
                details.append(helper.fail_detail("sheet_target_dispatch", subject, row["range"], "populated canonical row", status["raw"]))

            for field, label, expected_value, actual_value in (
                ("due", "due day", row["due_day"], status["raw"][0]),
                ("manual_auto", "M/A", row["manual_auto"], status["raw"][1]),
            ):
                due_ma_total += 1
                if status[field]:
                    due_ma_passed += 1
                    details.append(helper.pass_detail("due_day_manual_auto", subject, label, actual_value))
                else:
                    all_rows_pass = False
                    details.append(helper.fail_detail("due_day_manual_auto", subject, label, expected_value, actual_value))

            ars_total += 1
            if status["ars"]:
                ars_passed += 1
                details.append(helper.pass_detail("ars_semantics", subject, "raw/formatted ARS", (status["raw"][2], status["formatted"][2])))
            else:
                all_rows_pass = False
                details.append(helper.fail_detail("ars_semantics", subject, "raw/formatted ARS", (row["ars_raw"], row["ars_formatted"]), (status["raw"][2], status["formatted"][2])))

            usd_total += 1
            if status["usd"]:
                usd_passed += 1
                details.append(helper.pass_detail("usd_semantics", subject, "raw/formatted USD", (status["raw"][3], status["formatted"][3])))
            else:
                all_rows_pass = False
                details.append(helper.fail_detail("usd_semantics", subject, "raw/formatted USD", (row["usd_raw"], row["usd_formatted"]), (status["raw"][3], status["formatted"][3])))

    score += helper.score_fraction(weights["sheet_target_dispatch"], target_passed, target_total)
    score += helper.score_fraction(weights["due_day_manual_auto"], due_ma_passed, due_ma_total)
    score += helper.score_fraction(weights["ars_semantics"], ars_passed, ars_total)
    score += helper.score_fraction(weights["usd_semantics"], usd_passed, usd_total)

    drive_passed = 0
    drive_total = 0
    all_drive_files_pass = True
    for item in expected["expected_items"]:
        subject = item["subject_contains"]
        for artifact in item["expected_drive_files"]:
            drive_total += 1
            path = _expected_file_path(artifact)
            entries = drive_by_path.get(path, [])
            passed = len(entries) == 1 and entries[0]["mime_type"] != helper.FOLDER_MIME
            if passed:
                drive_passed += 1
                details.append(helper.pass_detail("drive_archival", subject, path, entries[0]["id"]))
            else:
                all_drive_files_pass = False
                details.append(helper.fail_detail("drive_archival", subject, path, "one file", [entry["id"] for entry in entries]))
    score += helper.score_fraction(weights["drive_archival"], drive_passed, drive_total)

    gmail_passed = 0
    gmail_total = 0
    all_gmail_pass = True
    for item in expected["expected_items"]:
        message = _item_message(item, runtime["messages"])
        actual_unread = label_states[message["id"]]["unread"]
        expected_unread = item["expected_final_unread"]
        gmail_total += 1
        if actual_unread == expected_unread:
            gmail_passed += 1
            details.append(helper.pass_detail("gmail_lifecycle", item["subject_contains"], "unread state", actual_unread))
        else:
            all_gmail_pass = False
            details.append(helper.fail_detail("gmail_lifecycle", item["subject_contains"], "unread state", expected_unread, actual_unread))
    score += helper.score_fraction(weights["gmail_lifecycle"], gmail_passed, gmail_total)

    multi_passed = 0
    multi_total = 0
    for item in expected["expected_items"]:
        if item["type"] != "pago_mis_cuentas_digest":
            continue
        message = _item_message(item, runtime["messages"])
        for row in item["expected_sheet_rows"]:
            multi_total += 1
            status = row_statuses[row["range"]]
            row_ok = all(status[key] for key in ("target", "due", "manual_auto", "ars", "usd"))
            artifact_ok = all(len(drive_by_path.get(_expected_file_path(artifact), [])) == 1 for artifact in item["expected_drive_files"])
            gmail_ok = label_states[message["id"]]["unread"] == item["expected_final_unread"]
            if row_ok and artifact_ok and gmail_ok:
                multi_passed += 1
                details.append(helper.pass_detail("multi_service_completeness", item["subject_contains"], row["service"], "processed"))
            else:
                details.append(helper.fail_detail("multi_service_completeness", item["subject_contains"], row["service"], "processed", {"row": row_ok, "drive": artifact_ok, "gmail": gmail_ok}))
    score += helper.score_fraction(weights["multi_service_completeness"], multi_passed, multi_total)

    collateral_passed = 0
    collateral_total = 3
    collateral_passed += 1
    details.append("PASS [no_collateral_changes] evaluation Sheet changes are confined to allowlisted ranges")

    fixture_label_ok = True
    for message in runtime["messages"]:
        baseline_non_unread = set(message["baseline_label_ids"]) - {"UNREAD"}
        current_non_unread = set(label_states[message["id"]]["label_ids"]) - {"UNREAD"}
        changed_labels = label_changes.get(message["id"], set())
        if baseline_non_unread != current_non_unread or any(change.lstrip("+-") != "UNREAD" for change in changed_labels):
            fixture_label_ok = False
            break
    if fixture_label_ok:
        collateral_passed += 1
        details.append("PASS [no_collateral_changes] fixture Gmail messages changed only in UNREAD lifecycle state")
    else:
        details.append("FAIL [no_collateral_changes] fixture Gmail messages have collateral label changes")

    expected_tree = helper.expected_drive_tree_paths(expected)
    actual_tree = helper.actual_drive_paths(tree)
    if actual_tree == expected_tree:
        collateral_passed += 1
        details.append("PASS [no_collateral_changes] evaluation Drive tree exactly matches expected artifacts")
    else:
        details.append(helper.fail_detail("no_collateral_changes", "evaluation Drive", "exact relative tree", expected_tree, actual_tree))
    score += helper.score_fraction(weights["no_collateral_changes"], collateral_passed, collateral_total)

    all_artifacts_pass = all_rows_pass and all_drive_files_pass and all_gmail_pass and multi_passed == multi_total
    report_ok, report_reason = _final_report_passes(agent_output, all_artifacts_pass, expected, drive_by_path)
    if report_ok:
        score += weights["final_report"]
        details.append(f"PASS [final_report] {report_reason}")
    else:
        details.append(f"FAIL [final_report] {report_reason}")

    return {"score": round(score, 2), "details": details}


if __name__ == "__main__":
    print(validate(sys.stdin.read()))
