#!/usr/bin/env python3
"""Reset the isolated evaluation Sheet, Drive root, and Gmail corpus."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import google_helper as helper


def reset() -> None:
    manifest = helper.load_benchmark_manifest()
    integrity_errors = helper.benchmark_integrity_errors(manifest)
    if integrity_errors:
        raise RuntimeError(
            "benchmark integrity failed before reset: " + " | ".join(integrity_errors)
        )

    config = helper.load_task_config()
    expected = helper.load_expected_fixture()
    original = helper.load_original_sheet()
    helper.validate_static_data(config, expected, original)

    credentials = helper.get_credentials(config["google"]["token_path"])
    services = helper.get_services(credentials)
    gmail, drive, sheets = services["gmail"], services["drive"], services["sheets"]

    profile = helper.get_gmail_profile(gmail)
    if str(profile.get("emailAddress", "")).casefold() != config["gmail"]["account"].casefold():
        raise RuntimeError(
            f"authenticated Gmail account is {profile.get('emailAddress')!r}, not the eval account"
        )
    label = helper.resolve_gmail_label(gmail, config["gmail"]["label"])
    sheet_identity = helper.verify_sheet_identity(sheets, config)
    if sheet_identity.get("locale") != "es_AR":
        raise RuntimeError(f"evaluation spreadsheet locale is not es_AR: {sheet_identity.get('locale')!r}")
    helper.verify_drive_root_identity(drive, config)

    label_messages = helper.list_eval_messages(gmail, f"label:{config['gmail']['label']}")
    resolved = helper.resolve_expected_messages(label_messages, expected)
    fixture_ids = {message["id"] for message in resolved}
    allow_production_overlap = (
        os.environ.get("GASTOS_VENCIMIENTOS_ALLOW_PRODUCTION_OVERLAP") == "1"
    )

    production_messages = helper.list_eval_messages(gmail, config["gmail"]["production_query"])
    production_overlap = fixture_ids & {message["id"] for message in production_messages}
    if production_overlap and not allow_production_overlap:
        raise RuntimeError(
            "evaluation corpus overlaps the production Gmail query: "
            + ", ".join(sorted(production_overlap))
        )
    if production_overlap:
        print(
            "WARNING: operator override accepted for current production-query "
            "overlap: " + ", ".join(sorted(production_overlap))
        )

    production_eligibility_query = config["gmail"]["production_query"].removeprefix(
        "is:unread "
    ).strip()
    production_eligible_messages = helper.list_eval_messages(
        gmail, production_eligibility_query
    )
    production_eligible_overlap = fixture_ids & {
        message["id"] for message in production_eligible_messages
    }
    if production_eligible_overlap and not allow_production_overlap:
        raise RuntimeError(
            "evaluation corpus would overlap the production Gmail query after "
            "reset marks it unread: "
            + ", ".join(sorted(production_eligible_overlap))
        )
    if production_eligible_overlap:
        print(
            "WARNING: operator override accepted because production automation "
            "is confirmed inactive; fixture IDs would otherwise overlap after "
            "being marked unread: "
            + ", ".join(sorted(production_eligible_overlap))
        )

    helper.restore_sheet(
        sheets,
        config["sheets"]["spreadsheet_id"],
        config["sheets"]["worksheet_title"],
        original,
    )
    helper.trash_drive_descendants(drive, config["drive"]["root_id"])
    remaining_drive = helper.list_drive_tree(drive, config["drive"]["root_id"])
    if remaining_drive:
        raise RuntimeError(
            "evaluation Drive root is not empty after cleanup: "
            + ", ".join(entry["relative_path"] for entry in remaining_drive)
        )

    helper.mark_messages_unread(gmail, fixture_ids)
    query_messages = helper.list_eval_messages(gmail, config["gmail"]["query"])
    query_ids = {message["id"] for message in query_messages}
    if query_ids != fixture_ids:
        raise RuntimeError(
            f"evaluation query returned IDs {sorted(query_ids)}, expected {sorted(fixture_ids)}"
        )
    label_states = helper.get_message_label_states(gmail, fixture_ids)
    not_unread = sorted(message_id for message_id, state in label_states.items() if not state["unread"])
    if not_unread:
        raise RuntimeError(f"fixture messages are not unread after reset: {not_unread}")

    history_id = helper.get_gmail_profile_history_id(gmail)
    final_sheet = helper.read_sheet_formulas(
        sheets,
        config["sheets"]["spreadsheet_id"],
        config["sheets"]["worksheet_title"],
    )
    if final_sheet != original:
        raise RuntimeError("evaluation Sheet changed during reset final verification")
    if helper.list_drive_tree(drive, config["drive"]["root_id"]):
        raise RuntimeError("evaluation Drive root changed during reset final verification")

    runtime = {
        "fixture_revision": expected["fixture_revision"],
        "started_at": helper.utc_now_iso(),
        "gmail_history_id": history_id,
        "messages": [
            {
                "id": message["id"],
                "subject": message["subject"],
                "subject_contains": message["subject_contains"],
                "fixture_type": message["fixture_type"],
                "baseline_label_ids": label_states[message["id"]]["label_ids"],
            }
            for message in resolved
        ],
        "sheet_baseline": final_sheet,
        "resource_ids": {
            "spreadsheet_id": config["sheets"]["spreadsheet_id"],
            "sheet_id": config["sheets"]["sheet_id"],
            "drive_root_id": config["drive"]["root_id"],
        },
    }
    helper.validate_runtime_state(runtime, expected)
    helper.write_runtime_state(runtime)
    written = helper.load_runtime_state()
    if written != runtime:
        raise RuntimeError("runtime state did not read back exactly after atomic write")
    print(
        "Reset complete: evaluation Sheet restored, evaluation Drive root empty, "
        f"{len(fixture_ids)} fixture messages unread, runtime state={helper.RUNTIME_PATH}"
    )


if __name__ == "__main__":
    reset()
