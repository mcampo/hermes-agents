# Tasks: ipc-indec-angelica Evaluation Task

**Input**: Design documents from `tasks/ipc-indec-angelica/`

**Prerequisites**: spec.md (required), plan.md (required)

**Organization**: Tasks are grouped by phase to enable incremental implementation.

## Format: `[ID] [P?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

---

## Phase 1: Configuration & Fixtures

**Purpose**: Create the static configuration files that define the task contract.

- [ ] T001 [P] Create `tasks/ipc-indec-angelica/config.json` — Task configuration: `{"prompt": "Update the spreadsheet with the monthly INDEC IPC variation, following the 'ipc-indec-angelica' skill.", "skills": ["ipc-indec-angelica", "google-workspace"], "timeout": 600, "sheets": {"spreadsheet_id": "1Qvybe0z_QoI698DRfP1uCjF9f0BcrWLuriaw976mOZs", "target_row": 15, "target_row_label": "Variación mensual IPC", "token_path": "~/.hermes/google_token.json"}}`
- [ ] T002 [P] Create `tasks/ipc-indec-angelica/fixtures/expected.json` — Initial template with placeholder values: `{"target_tab": "2026", "target_column_month": "Julio", "expected_value": "TBD", "expected_url_contains": "indec.gob.ar"}`. Must be manually updated before each evaluation cycle with the correct IPC percentage and target cell locations.

**Checkpoint**: Task is discoverable by the harness via `./run.sh --list-tasks` (config.json exists with valid prompt and skills).

---

## Phase 2: Shared Utilities

**Purpose**: Build the shared Google Sheets helper used by both reset and validator.

**⚠️ CRITICAL**: Phase 3 depends on this module being complete.

- [ ] T003 Create `tasks/ipc-indec-angelica/sheets_helper.py` — Shared utilities module exposing four functions:
  - `load_task_config() -> dict`: Loads and returns the task's `config.json` from the same directory.
  - `load_expected_fixture() -> dict`: Loads and returns the task's `fixtures/expected.json` from the same directory.
  - `get_sheets_client(token_path: str) -> gspread.Client`: Authenticates using the pre-authorized OAuth2 token file via `google.oauth2.credentials.Credentials.from_authorized_user_file()` with Google Sheets and Drive scopes. Returns an authorized `gspread.Client`.
  - `get_target_cell_coords(expected_fixture: dict) -> dict`: Determines the target cell based on the `target_tab` and `target_column_month` provided in the fixture. Returns `{"tab": "2026", "column_name": "Julio", "col_index": 7, "row": 15}`. Uses a static `MONTHS_ES` dictionary mapping Spanish names to column indexes (Column A = labels, Column B = Enero, etc. — to be verified against actual sheet layout).

**Checkpoint**: Helper module importable, `get_target_cell_coords()` returns correct values based on the fixture.

---

## Phase 3: Reset & Validator

**Purpose**: Implement the core task interface scripts.

- [ ] T004 Create `tasks/ipc-indec-angelica/reset.py` — Implements `reset() -> None`. Steps: (1) load task config via `sheets_helper.load_task_config()` and fixture via `sheets_helper.load_expected_fixture()`, (2) authenticate via `sheets_helper.get_sheets_client(token_path)`, (3) resolve target cell via `sheets_helper.get_target_cell_coords(expected_fixture)`, (4) open spreadsheet by ID → open year tab → write `"0.00%"` to target cell (row 15, current month column), (5) read back the cell and print confirmation. Must handle `gspread.exceptions.SpreadsheetNotFound` and `gspread.exceptions.WorksheetNotFound` gracefully with error messages.
- [ ] T005 Create `tasks/ipc-indec-angelica/validator.py` — Implements `validate(agent_output: str) -> dict` returning `{"score": float, "details": list[str]}`. Steps: (1) load `config.json` and `fixtures/expected.json`, (2) authenticate and resolve target cell via `get_target_cell_coords(expected_fixture)`, (3) read cell displayed value (`FORMATTED_VALUE`) and raw formula (`FORMULA` render option) via `gspread`, (4) run 5 weighted checks:
  - Check 1 (0.20): Cell is not empty and not `"0.00%"` — agent wrote something.
  - Check 2 (0.20): Raw formula starts with `=HYPERLINK(` and contains `;` separator.
  - Check 3 (0.20): Displayed value matches regex `r"^\d+(,\d+)?%$"` — valid percentage with comma decimal.
  - Check 4 (0.20): Raw formula URL contains `"indec.gob.ar"`.
  - Check 5 (0.20): Displayed value equals `expected.json["expected_value"]`.
  Return cumulative score and a detail string per check (pass/fail with context). If Google Sheets authentication or access fails, return `{"score": 0.0, "details": ["Sheets access error: ..."]}`.

**Checkpoint**: Both scripts importable, `reset()` callable, `validate("")` returns `{"score": 0.0, "details": [...]}` when cell is still at placeholder.

---

## Phase 4: Verification

**Purpose**: End-to-end validation on the RPi.

- [ ] T006 Deploy task to RPi via rsync and verify discovery: `./run.sh --list-tasks` shows `ipc-indec-angelica`.
- [ ] T007 Populate `fixtures/expected.json` with the correct IPC value for the current period.
- [ ] T008 Run reset manually on RPi: `~/.hermes/.venv-google/bin/python -c "import sys; sys.path.insert(0, '.'); from reset import reset; reset()"` from the task directory. Verify the target cell in Google Sheets reads `0.00%`.
- [ ] T009 Run a single evaluation: `./run.sh --tasks ipc-indec-angelica --runs 1`. Verify:
  - Agent executes the skill workflow (downloads PDF, writes to Sheets).
  - Validator produces a score between 0.0 and 1.0 with meaningful detail strings.
  - CSV row is written with all 26 fields populated.
- [ ] T010 Run reset again after a successful run to confirm it clears the HYPERLINK formula back to `0.00%`.
