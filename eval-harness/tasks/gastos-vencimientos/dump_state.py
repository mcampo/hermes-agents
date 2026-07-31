#!/usr/bin/env python3
"""Capture the reviewed full evaluation Sheet baseline in formula mode."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import google_helper as helper


def dump(write: bool = False) -> tuple[int, int]:
    if not write:
        raise ValueError("refusing to replace original_sheet.json without explicit --write")
    config = helper.load_task_config()
    expected = helper.load_expected_fixture()
    helper.validate_config(config)
    helper.validate_expected_fixture(expected)
    credentials = helper.get_credentials(config["google"]["token_path"])
    services = helper.get_services(credentials)
    identity = helper.verify_sheet_identity(services["sheets"], config)
    if identity.get("locale") != "es_AR":
        raise RuntimeError(f"evaluation spreadsheet locale must be es_AR, got {identity.get('locale')!r}")
    values = helper.read_sheet_formulas(
        services["sheets"],
        config["sheets"]["spreadsheet_id"],
        config["sheets"]["worksheet_title"],
    )
    helper.validate_original_sheet(values)
    target = helper.TASK_DIR / "fixtures" / "original_sheet.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, prefix=target.name + ".", suffix=".tmp", delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(values, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    saved = helper.load_original_sheet()
    if saved != values:
        raise RuntimeError("saved original_sheet.json does not read back exactly")
    rows, cols = helper.sheet_dimensions(saved)
    formulas = sum(
        1 for row in saved for value in row if isinstance(value, str) and value.startswith("=")
    )
    print(
        f"Captured {rows} rows x {cols} columns from {identity['spreadsheet_title']} / "
        f"{identity['title']} (sheetId {identity['sheetId']}); formulas={formulas}"
    )
    return rows, cols


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="replace the reviewed baseline fixture")
    args = parser.parse_args()
    if not args.write:
        parser.error("--write is required")
    dump(write=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
