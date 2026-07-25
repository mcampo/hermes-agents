# Tasks: Evaluation Harness Framework

**Input**: Design documents from `eval-harness/specs/`

**Prerequisites**: plan.md (required), harness-spec.md (required), task-spec.md (required)

**Organization**: Tasks are grouped by phase and user story to enable incremental implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the new project structure and bootstrap scripts

- [ ] T001 Create directory structure: `eval-harness/src/`, `eval-harness/tasks/`, `eval-harness/results/`, `eval-harness/results/sessions/`
- [ ] T002 [P] Create `eval-harness/run.sh` wrapper script that invokes `~/.hermes/.venv-google/bin/python src/harness.py "$@"` relative to its directory
- [ ] T003 [P] Create `eval-harness/README.md` with quick-start instructions referencing the `run.sh` wrapper

**Checkpoint**: Directory structure exists, `run.sh` is executable

---

## Phase 2: Core Modules (Blocking Prerequisites)

**Purpose**: Build the foundational modules that all user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 [US1] Create `eval-harness/src/config.py` — Load and parse `config.json`. Must handle model configuration objects with `model`, `provider`, and optional `reasoning_effort` fields. Expose `load_config()` and `load_api_key()` functions. Config path: `eval-harness/config.json`
- [ ] T005 [US1] Create `eval-harness/config.json` — Global harness configuration. Schema: `models` (array of `{model, provider, reasoning_effort?}`), `runs` (int, default 1), `eval_profile` (string), `gmail_label` (string). Do NOT include task-specific prompts or skills — those live in `tasks/<name>/config.json`
- [x] T006 [US1] Create `eval-harness/src/executor.py` — Hermes CLI execution wrapper. Function `run_hermes(model, provider, reasoning_effort, prompt, skills, profile, timeout) -> {session_id, output, exit_code, elapsed}`. Must call `hermes config set agent.reasoning_effort <effort>` if configured, then construct `hermes -p <profile> chat -q "<prompt>" -m <model> --provider <provider> -s <skill1> -s <skill2> ... -Q` command. Extract session ID from `-Q` output (first line `session_id: <ID>`, fallback regex `\b(\d{8}_\d{6}_[a-f0-9]{6})\b`). Handle `subprocess.TimeoutExpired` and general exceptions
- [ ] T007 [US1] Create `eval-harness/src/metrics.py` — Query `~/.hermes/profiles/<profile>/state.db` `sessions` table by session ID. Return dict with all token columns, tool/api/message counts, timestamps, and computed fields (`total_tokens`, `elapsed_seconds`, `reasoning_effort` extracted from `model_config` JSON → `reasoning_config.effort`)

**Checkpoint**: Core modules loadable, `executor.py` can construct and run a `hermes` command, `metrics.py` can query state.db

---

## Phase 3: User Story 2 — Task Selection 🎯

**Goal**: Dynamic task discovery and selection from `tasks/` directories

**Independent Test**: Create a dummy task directory, run the harness with `--tasks <name>`, and verify only that task is discovered

- [ ] T008 [US2] Create `eval-harness/src/task_registry.py` — Scan `eval-harness/tasks/*/config.json` at startup. For each valid task directory, load `config.json` and dynamically import `reset.py` (expecting a `reset()` function) and `validator.py` (expecting a `validate()` function). Return a list of `Task` objects with attributes: `name`, `prompt`, `skills`, `timeout`, `config`, `reset()`, `validate()`. Expose `discover_tasks(tasks_dir) -> list[Task]` and `filter_tasks(tasks, names) -> list[Task]`
- [ ] T009 [US2] Create `eval-harness/src/task_registry.py` list functionality — `list_tasks(tasks) -> str` that prints a formatted table of all discovered tasks showing name, prompt preview (truncated to 60 chars), and skill count

---

## Phase 4: User Story 1 — Multi-Model Evaluation Execution 🎯 MVP

**Goal**: The core evaluation loop that runs model configurations sequentially and records the full 26-field metrics schema

**Independent Test**: Run the harness with one model, one task, one run, and verify a complete CSV row is written

### 4a: Cost Tracking (US5 prerequisite)

- [ ] T010 [US5] Create `eval-harness/src/cost_tracker.py` — Define `CostTracker` abstract base class with methods: `snapshot_before() -> float`, `snapshot_after() -> float`, `calculate_cost(model, metrics) -> float`, `needs_post_run_wait() -> bool`. Implement `OpenRouterCostTracker` (balance snapshot via `/api/v1/key` with retry logic), `DeepSeekCostTracker` (returns `estimated_cost_usd` from session metrics, since Hermes already calculates this using its built-in pricing tables), and `NullCostTracker` (returns 0.0 for unknown providers). Factory function: `create_cost_tracker(provider, api_key) -> CostTracker`

### 4b: Results Persistence (US6 prerequisite)

- [ ] T012 [US6] Create `eval-harness/src/results.py` — `save_result_csv(row, csv_path)` that appends a dict matching the 26-field metrics schema to a CSV file. Fieldnames: `timestamp`, `datetime`, `provider`, `model`, `reasoning_effort`, `config_name`, `task`, `run_number`, `session_id`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`, `total_tokens`, `api_calls`, `tool_calls`, `message_count`, `elapsed_seconds`, `estimated_cost`, `actual_cost`, `validation_score`, `validation_details`, `agent_output`, `transcript_path`. Creates header row on first write

### 4c: Session Logging (US7)

- [ ] T013 [US7] Create `eval-harness/src/session_logger.py` — Function `dump_session(session_id, output_dir, profile) -> Path`. Reads `messages` table from `state.db`, normalizes tool calls and reasoning fields, writes structured JSON transcript to `<output_dir>/<session_id>.json`. Must accept profile name to resolve correct `state.db` path

### 4d: Main Orchestrator (US1, US3, US4)

- [x] T014 [US1][US3][US4] Create `eval-harness/src/harness.py` — Main evaluation orchestrator. Implements the loop: `for task → for run_num → for model_config`. For each iteration: (1) invoke `task.reset()`, (2) `tracker.snapshot_before()`, (3) `executor.run_hermes(...)` setting config effort prior to chat, (4) optional post-run wait, (5) compute actual cost, (6) `metrics.get_session_metrics()`, (7) `task.validate()`, (8) `session_logger.dump_session()`, (9) build 26-field metrics row, (10) `results.save_result_csv()`. CLI args: `--models` (substring filter), `--tasks` (name filter), `--runs` (iteration count, default from config), `--timeout` (default 600), `--dry-run`, `--list-tasks`

**Checkpoint**: MVP — `./run.sh --tasks <name> --models <model> --runs 1` executes a full cycle and writes a CSV row

---

## Phase 5: Mock Task for Harness Testing 🎯

**Goal**: Create a minimal mock task that exercises the full harness pipeline without requiring real external services

The mock task asks Hermes a simple deterministic question (e.g., "echo the exact phrase: HARNESS_TEST_OK") and validates that the expected output appears in the agent response. This enables end-to-end harness verification without external API dependencies (Google Sheets, Drive, Gmail, etc.).

- [ ] T015 [US2] Create `eval-harness/tasks/mock-echo/config.json` — Task configuration: `{"prompt": "Reply with exactly: HARNESS_TEST_OK", "skills": [], "timeout": 60}`
- [ ] T016 [US4] Create `eval-harness/tasks/mock-echo/reset.py` — No-op reset (the mock task has no external state). Implements `reset()` as a function that returns immediately
- [ ] T017 [US6] Create `eval-harness/tasks/mock-echo/validator.py` — Implements `validate() -> {score: float, details: list[str]}`. Checks that the agent output contains the expected phrase from `fixtures/expected.json`. Returns `1.0` if the exact phrase is found, `0.0` otherwise
- [ ] T018 [P] Create `eval-harness/tasks/mock-echo/fixtures/expected.json` — `{"expected_output": "HARNESS_TEST_OK"}`

**Checkpoint**: Mock task discoverable, resettable, and validatable via the harness

---

## Phase 6: Verification

**Purpose**: End-to-end validation and documentation

- [ ] T019 Run full dry-run: `./run.sh --dry-run` — verify plan output shows all model configs × tasks × runs
- [ ] T020 Run single-model single-task: `./run.sh --tasks mock-echo --runs 1` — verify complete CSV row with all 26 fields populated
- [ ] T021 Run with reasoning effort variants: configure two entries for the same model with different effort levels, verify both produce independent results rows
- [ ] T022 [P] Verify `--list-tasks` outputs all discovered tasks
- [ ] T023 [P] Update `eval-harness/README.md` with final usage examples and architecture overview


---

## Phase 7: Google Sheets Integration (US8)

**Purpose**: Persist evaluation results directly to a Google Spreadsheet using a pre-authorized OAuth2 token file.

**Prerequisites**: A one-time OAuth2 authorization flow must be performed on a local machine with a browser to generate the `authorized_user.json` token file. This token file is then copied to the RPi.

- [ ] T024 [US8] Update `eval-harness/src/config.py` — Update `load_sheets_config()` to parse the `google_sheets` object with `spreadsheet_id`, `sheet_name`, and `token_path` (replacing `credentials_path`). Returns `None` if the block is absent.
- [ ] T025 [US8] Update `eval-harness/src/sheets.py` — Rewrite `append_result_to_sheet(row, spreadsheet_id, sheet_name, token_path)` to authenticate using a pre-authorized token file via `gspread.auth.authorize` with `google.oauth2.credentials.Credentials`. No OAuth flow at runtime. Must reuse `FIELDNAMES` from `results.py` to order columns. If the sheet is completely empty, write the header row first. Wrap in try/except, log warnings on failure without raising.
- [ ] T025b [US8] Add `generate_google_token(client_secret_path, token_output_path)` helper function to `sheets.py`. This function runs the `gspread.oauth()` flow (which opens a browser) and writes `authorized_user.json` to `token_output_path`. Intended to be run once on a local machine with a browser. Also add a `if __name__ == "__main__"` block so `sheets.py` can be invoked directly as `python src/sheets.py <client_secret_path> <token_output_path>`.
- [ ] T026 [US8] Update `eval-harness/src/harness.py` — After calling `save_result_csv(row, ...)`, load the sheets config via `load_sheets_config()`, and if present, call `append_result_to_sheet(...)` passing `token_path` instead of `credentials_path`.
- [ ] T026b [US8] Update `eval-harness/config.json` — Change `credentials_path` to `token_path` pointing to `/home/mcampo/.hermes/authorized_user.json`.
- [ ] T027 [US8] Verify Google Sheets integration: Generate token locally via `python src/sheets.py`, copy `authorized_user.json` to RPi, run `./run.sh --tasks mock-echo --runs 1` and confirm the 26-field row appears in the spreadsheet. Then test with an invalid `token_path` and confirm the harness logs a warning but completes without crashing.

**Checkpoint**: Running with `google_sheets` config and a valid token file correctly populates a spreadsheet with matching column layout to `eval_results.csv`, auto-initializes header on empty sheet, and does not crash if token is missing or network is unavailable.

