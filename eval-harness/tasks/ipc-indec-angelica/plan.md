# Implementation Plan: ipc-indec-angelica Evaluation Task

**Date**: 2026-07-20 | **Spec**: [spec.md](spec.md)

**Input**: Task specification for evaluating models against the `ipc-indec-angelica` Hermes skill.

## Summary

Implement a self-contained evaluation task that tests whether an LLM agent can execute the `ipc-indec-angelica` skill correctly. The task sends a natural-language prompt to the agent, then validates the result by reading the target Google Sheet cell and checking five weighted criteria: cell population, HYPERLINK formula presence, percentage format, INDEC URL, and correct value.

Both `reset.py` and `validator.py` need direct Google Sheets API access (via `gspread`) to manipulate and inspect the target cell. A shared helper module (`sheets_helper.py`) centralizes authentication and cell-location logic to avoid duplication.

## Technical Context

**Language/Version**: Python 3.11+

**Dependencies**: `gspread`, `google-auth` (available in `~/.hermes/.venv/`)

**Authentication**: Pre-authorized OAuth2 token file at `~/.hermes/google_token.json` (same token used by the harness's Google Sheets persistence)

**Target Platform**: Linux (Raspberry Pi), aarch64

**Constraints**: Scripts run under `~/.hermes/.venv/bin/python` which has `gspread` and `google-auth` pre-installed.

---

## Architecture & Data Flow

### Task Directory Layout

```text
tasks/ipc-indec-angelica/
├── spec.md              # Task specification (this plan's source)
├── plan.md              # This file
├── tasks.md             # Implementation task breakdown
├── config.json          # Prompt, skills, timeout, and custom sheets metadata
├── sheets_helper.py     # Shared auth + cell-location utilities
├── reset.py             # Resets target cell to 0.00% placeholder
├── validator.py         # 5-check weighted validation against Google Sheets
└── fixtures/
    └── expected.json    # Manually populated expected IPC value per cycle
```

### config.json Schema

```json
{
  "prompt": "Update the spreadsheet with the monthly INDEC IPC variation, following the 'ipc-indec-angelica' skill.",
  "skills": ["ipc-indec-angelica", "google-workspace"],
  "timeout": 600,
  "sheets": {
    "spreadsheet_id": "1Qvybe0z_QoI698DRfP1uCjF9f0BcrWLuriaw976mOZs",
    "target_row": 15,
    "target_row_label": "Variación mensual IPC",
    "token_path": "~/.hermes/google_token.json"
  }
}
```

The standard fields (`prompt`, `skills`, `timeout`) satisfy the harness task contract. The custom `sheets` object provides spreadsheet access parameters for `reset.py` and `validator.py`.

### fixtures/expected.json Schema

```json
{
  "target_tab": "2026",
  "target_column_month": "Julio",
  "expected_value": "2,1%",
  "expected_url_contains": "indec.gob.ar"
}
```

> **Manually populated** before each evaluation cycle with the correct IPC percentage and target cell locations for the current period.

### sheets_helper.py — Shared Utilities

Centralizes two concerns used by both `reset.py` and `validator.py`:

1. **Authentication**: Load the `authorized_user.json` token file and return an authenticated `gspread.Client`.
2. **Cell location**: Given the spreadsheet ID from config and the target tab and month from `fixtures/expected.json`, determine the target cell coordinates (year tab, target-month column, row 15).

```python
# Public interface
def get_sheets_client(token_path: str) -> gspread.Client
def get_target_cell_coords(expected_fixture: dict) -> dict  # Returns {tab: "2026", column_name: "Julio", col_index: 7, row: 15}
def load_task_config() -> dict  # Loads config.json from the task directory
def load_expected_fixture() -> dict # Loads expected.json from the task directory
```

**Column resolution**: Row 1 of the year tab contains month headers. The helper reads row 1 and finds the 1-indexed column position matching the month's Spanish name provided in the fixture.

### reset.py — Environment Reset

```python
def reset() -> None:
    1. Load config.json and fixtures/expected.json
    2. Authenticate via sheets_helper.get_sheets_client(token_path)
    3. Resolve target cell via sheets_helper.get_target_cell_coords(expected)
    4. Open spreadsheet → year tab → write "0.00%" to (row 15, month column)
    5. Read back the cell and assert it equals "0.00%"
    6. Print confirmation to stdout
```

### validator.py — Validation & Scoring

```python
def validate(agent_output: str) -> dict:
    1. Load config.json + fixtures/expected.json
    2. Authenticate and resolve target cell (same as reset)
    3. Read cell displayed value: worksheet.acell(a1_notation)
    4. Read cell formula:        worksheet.acell(a1_notation, value_render_option='FORMULA')
    5. Run 5 checks, accumulating score and details:

    Check 1 (0.20): cell_value != "" and cell_value != "0.00%"
    Check 2 (0.20): formula starts with "=HYPERLINK(" and contains ";"
    Check 3 (0.20): displayed value matches regex r"^\d+(,\d+)?%$"
    Check 4 (0.20): formula URL contains "indec.gob.ar"
    Check 5 (0.20): displayed value == expected.json["expected_value"]

    6. Return {"score": sum_of_weights, "details": [...]}
```

**Cell reading strategy**: `gspread` supports two render options:
- `value_render_option='FORMATTED_VALUE'` (default) — returns the displayed text (e.g., `2,1%`)
- `value_render_option='FORMULA'` — returns the raw formula (e.g., `=HYPERLINK("https://..."; "2,1%")`)

Both are needed: formatted value for checks 1, 3, and 5; formula for checks 2 and 4.

---

## Complexity Tracking

| Decision | Why | Simpler Alternative Rejected Because |
|---|---|---|
| Shared `sheets_helper.py` module | Both reset and validator need identical auth + cell-location logic | Duplicating 30+ lines of boilerplate in each script increases maintenance risk |
| Partial scoring (5 × 0.20) | Distinguishes "agent wrote something wrong" from "agent did nothing" | Binary pass/fail gives no signal on partial progress |
| Target tab/month in fixture | Removes brittle date logic from validator, preventing mismatches if task runs around month transitions | Calculating date dynamically in validator is risky |
