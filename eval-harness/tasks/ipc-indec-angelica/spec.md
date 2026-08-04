# Task Specification: ipc-indec-angelica

**Created**: 2026-07-20

**Status**: Draft

**Skill Under Test**: `ipc-indec-angelica` (installed at `~/.hermes/profiles/eval/skills/ipc-indec-angelica/`)

**Depends on Skill**: `google-workspace` (required by the skill for Google Sheets interaction)

---

## Purpose

Evaluate how well different LLM models can execute the `ipc-indec-angelica` skill end-to-end. The skill instructs the agent to:

1. Determine the correct data month (previous month) and target cell (current month's column).
2. Locate and download the latest INDEC IPC technical report PDF.
3. Extract the **National Total Monthly % Variation** from the PDF.
4. Write a `=HYPERLINK()` formula to the correct cell in the "Angelica" Google Sheet.
5. Verify the write and output a confirmation message in Argentine Spanish.

This task exercises web navigation, PDF parsing, Google Sheets interaction, date reasoning, and locale-aware formula construction — making it a comprehensive real-world benchmark.

---

## Fixed Parameters

| Parameter            | Value                                              |
|----------------------|----------------------------------------------------|
| Spreadsheet ID       | `1Qvybe0z_QoI698DRfP1uCjF9f0BcrWLuriaw976mOZs`    |
| Target Tab           | Current execution year (e.g., `2026`)              |
| Target Row           | Row 15 (`"Variación mensual IPC"` in Column A)     |
| Target Column        | Current execution month (Spanish name in Row 1)    |
| Spreadsheet Locale   | `es_AR` (semicolon `;` as formula arg separator)   |
| Python venv          | `/home/mcampo/.hermes/.venv/bin/python`            |

---

## Prompt

```
Update the spreadsheet with the monthly INDEC IPC variation, following the 'ipc-indec-angelica' skill.
```

---

## Skills

- `ipc-indec-angelica`
- `google-workspace`

---

## Environment Baseline (Reset Contract)

Before each evaluation run, `reset.py` must restore the target cell to its clean placeholder state so that consecutive runs don't collide or trigger the skill's safety-check abort.

### Reset steps

1. **Identify the target cell**: Current year's tab, current month's column, row 15.
2. **Clear the cell**: Write the placeholder value `0.00%` to the target cell using the `google-workspace` skill's Sheets API (via the `$GAPI` CLI or the `gspread` library under the designated venv).
3. **Verify**: Read back the cell to confirm it contains `0.00%`.

> **Why `0.00%`?** The skill's own safety check reads the cell before writing and aborts if it already contains a "real value" (anything other than `0.00%`). Resetting to `0.00%` guarantees the skill's write path is exercised.

---

## Acceptance Criteria

A run is considered **fully successful (score 1.0)** when all of the following hold after the agent finishes:

1. **Cell is populated**: The target cell (year tab, current-month column, row 15) is no longer the `0.00%` placeholder.
2. **Contains a HYPERLINK formula**: The cell's raw formula matches the pattern `=HYPERLINK("..."; "X.X%")` (semicolon separator, not comma).
3. **Percentage value is valid**: The displayed text is a decimal number followed by `%` (e.g., `2,1%`, `0,8%`), using a comma as the decimal separator.
4. **URL points to INDEC**: The hyperlink URL contains `indec.gob.ar`.
5. **Correct month data**: The percentage matches the value published in the INDEC PDF for the previous month's National Total IPC variation. *(Note: this check requires the expected value to be set in `fixtures/expected.json` before each evaluation cycle.)*

---

## Validation Scoring Rubric

The validator awards partial credit based on individual checks:

| Check                          | Weight | Description                                                                 |
|--------------------------------|--------|-----------------------------------------------------------------------------|
| Cell not empty / not `0.00%`   | 0.20   | The agent wrote *something* to the target cell.                             |
| HYPERLINK formula present      | 0.20   | Cell contains `=HYPERLINK(...)` with semicolon separator.                   |
| Valid percentage format         | 0.20   | Displayed value matches `X,X%` pattern (comma decimal, `%` suffix).           |
| INDEC URL in hyperlink          | 0.20   | The hyperlink URL contains `indec.gob.ar`.                                  |
| Correct percentage value        | 0.20   | Extracted value matches the expected value from `fixtures/expected.json`.    |

**Final score** = sum of weights for all passing checks (range `0.0` – `1.0`).

---

## Fixtures

### `fixtures/expected.json`

Must be updated before each evaluation cycle with the correct expected values for the current period:

```json
{
  "spreadsheet_id": "1Qvybe0z_QoI698DRfP1uCjF9f0BcrWLuriaw976mOZs",
  "target_tab": "2026",
  "target_row": 15,
  "target_column_month": "Julio",
  "expected_value": "2,1%",
  "expected_url_contains": "indec.gob.ar"
}
```

> **Note**: `target_column_month` and `expected_value` are execution-date dependent and must be refreshed each month before running the evaluation.

---

## Timeout

Recommended: **600 seconds** (10 minutes). The task involves web requests, PDF download/parsing, and multiple Google Sheets API calls.

---

## Failure Modes to Watch

| Scenario                                    | Expected Agent Behavior                       |
|---------------------------------------------|-----------------------------------------------|
| INDEC PDF not yet published for the month   | Agent writes `"N/A"` to the cell              |
| Target cell already has a real value         | Agent aborts and notifies (safety check)       |
| Agent uses comma instead of semicolon        | Cell shows `#ERROR!` (formula parse failure)   |
| Agent writes to wrong month column           | Validator detects column mismatch              |
| Agent confuses "Minimo hora" with target row | Wrong row gets populated                       |
