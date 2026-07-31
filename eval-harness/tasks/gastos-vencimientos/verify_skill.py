#!/usr/bin/env python3
"""Static isolation guard for the gastos-vencimientos evaluation skill."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EVAL_SPREADSHEET_ID = "1Qvybe0z_QoI698DRfP1uCjF9f0BcrWLuriaw976mOZs"
EVAL_SHEET_ID = "1359523290"
EVAL_DRIVE_ROOT_ID = "1zpLE3gXabspesoSPjkO-gGJDZZmF1zXk"
EVAL_DRIVE_ROOT_NAME = "Hermes Eval - Vencimientos"
REQUIRED_QUERY_PREFIX = "label:eval is:unread"
EVAL_PYTHON = "/home/mcampo/.hermes/.venv-google/bin/python"
BATCH_SCRIPT = "/home/mcampo/.hermes/profiles/eval/skills/gastos-vencimientos/scripts/process_batch.py"
MANDATORY_BATCH_COMMAND = f"{EVAL_PYTHON} {BATCH_SCRIPT}"
SHELL_DEPENDENT_BATCH_COMMAND = f"$GAPI_PY {BATCH_SCRIPT}"
FORBIDDEN = (
    "newer_than:30d",
    "/profiles/mojo/",
    "1FlO3LLSWQmTRoKL8WFeYQKQ-GZWU3HW4zbKgfFuHPqw",
    "1VH_BTfYHqaLn_6u2Fi4hqNt00rKDY1Qu",
    "192915875",
)


def verify_skill(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    required_files = (
        "SKILL.md",
        "references/pdf-regex-cookbook.md",
        "references/quick-lookup.md",
        "scripts/cell_range.py",
        "scripts/download_gmail_attachments.py",
        "scripts/extract_items.py",
        "scripts/item_planner.py",
        "scripts/prepare_item.py",
        "scripts/process_batch.py",
        "scripts/commit_item.py",
        "scripts/render_report.py",
        "scripts/row_builders.py",
        "scripts/save_gmail_eml.py",
    )
    missing = [name for name in required_files if not (skill_dir / name).is_file()]
    if missing:
        errors.append(f"missing required files: {', '.join(missing)}")

    files = sorted(path for path in skill_dir.rglob("*") if path.is_file())
    combined_parts: list[str] = []
    for path in files:
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            errors.append(f"generated file present: {path.relative_to(skill_dir)}")
            continue
        try:
            combined_parts.append(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            errors.append(f"non-text file present: {path.relative_to(skill_dir)}")
    combined = "\n".join(combined_parts)
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8") if (skill_dir / "SKILL.md").is_file() else ""

    for value in (
        EVAL_SPREADSHEET_ID,
        EVAL_SHEET_ID,
        EVAL_DRIVE_ROOT_ID,
        EVAL_DRIVE_ROOT_NAME,
        REQUIRED_QUERY_PREFIX,
    ):
        if value not in skill_text:
            errors.append(f"SKILL.md missing required evaluation value: {value}")
    if MANDATORY_BATCH_COMMAND not in skill_text:
        errors.append("SKILL.md mandatory batch command must use the absolute evaluation venv interpreter")
    if SHELL_DEPENDENT_BATCH_COMMAND in skill_text:
        errors.append("SKILL.md mandatory batch command must not depend on $GAPI_PY")
    for value in FORBIDDEN:
        if value in combined:
            errors.append(f"forbidden production value/path present: {value}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "skill_dir",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parent / "skill",
    )
    args = parser.parse_args()
    errors = verify_skill(args.skill_dir.resolve())
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"PASS: isolated evaluation skill verified at {args.skill_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
