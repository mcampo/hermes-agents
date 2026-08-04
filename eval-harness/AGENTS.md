# Eval Harness — Agent Rules & Project Context

## Project Overview

This is an **evaluation harness** for the `hermes` AI agent CLI. It runs configurable evaluation tasks against different LLM models, captures metrics (tokens, cost, latency), validates outputs, and persists results to CSV and Google Sheets.

The harness runs on a **headless Raspberry Pi** (`mcampo@hermes.local`) where the `hermes` CLI is installed at `~/.local/bin/hermes`.

**Note**: The core `hermes-agent` source code repository is checked out at `../hermes-agent` (a sibling directory to this repo). You can reference it to understand how the `hermes` CLI, profiles, or internal APIs behave.
## Spec-Driven Development

This project follows a **spec-driven development workflow**. Before making code changes:

1. **Read the specs first** in `specs/` — they are the source of truth:
   - `harness-spec.md` — User stories and acceptance criteria
   - `plan.md` — Architecture, config schemas, execution flow, and module contracts
   - `tasks.md` — Implementation task checklist organized by phase
   - `task-spec.md` — Task contract specification (how eval tasks are structured)
2. **Update specs before code** — When adding features or changing behavior, update the spec files first, get user approval, then implement.

## Deployment & Execution

- **Deploying the Harness**: When the user requests to deploy the harness, use `rsync` to sync it to `mcampo@hermes.local:/home/mcampo/eval-harness`. Exclude `.git`, `__pycache__`, `.venv`, and `node_modules`.
  ```bash
  rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='.venv' --exclude='node_modules' \
    /home/mcampo/projects/hermes-agents/eval-harness/ mcampo@hermes.local:/home/mcampo/eval-harness/
  ```
- **Running the Harness**: When the user requests to run the harness, execute it on the remote Pi via SSH:
  ```bash
  ssh mcampo@hermes.local "/home/mcampo/eval-harness/run.sh [args]"
  ```
  Common args: `--tasks mock-echo --runs 1`, `--dry-run`, `--list-tasks`
- **Deploy before running**: Always deploy first if code has changed since the last deploy.

## Key Architecture Details

- **Entry point**: `run.sh` → `src/harness.py`
- **Python runtime on RPi**: `~/.hermes/.venv/bin/python` (venv with `gspread` and `google-auth`)
- **Config**: `config.json` at the project root defines models, runs, eval profile, and optional Google Sheets config
- **Results**: Written to `eval_results.csv` locally and optionally appended to Google Sheets

### Source Modules (`src/`)

| Module | Purpose |
|---|---|
| `harness.py` | Main orchestrator — iterates tasks × models × runs |
| `config.py` | Loads `config.json`, parses model configs and sheets config |
| `executor.py` | Wraps `hermes` CLI subprocess calls, extracts session IDs |
| `task_registry.py` | Discovers tasks from `tasks/*/config.json` |
| `metrics.py` | Reads token/cost metrics from `~/.hermes/profiles/eval/state.db` |
| `cost_tracker.py` | Abstract cost tracking with provider-specific strategies |
| `results.py` | CSV writer with the 26-field schema (`FIELDNAMES`) |
| `sheets.py` | Google Sheets persistence + `generate_google_token` helper |
| `session_logger.py` | Exports chat transcripts from `state.db` |

### Google Sheets Authentication

- The harness uses a **pre-authorized OAuth2 token file** (`authorized_user.json`), NOT service account or runtime OAuth flows.
- `config.json` → `google_sheets.token_path` points to the token file (e.g. `~/.hermes/authorized_user.json`).
- To generate the token on a local machine with a browser: `python src/sheets.py <client_secret_path> <token_output_path>`
- The client secrets file is at `~/.hermes/google_client_secret.json` (OAuth2 Client Secrets format, not service account).

### Adding New Eval Tasks

Tasks are auto-discovered from `tasks/*/config.json`. Each task directory must contain:
- `config.json` — prompt, skills, optional timeout
- `reset.py` — `reset()` function to clear environment before each run
- `validator.py` — `validate()` function returning `{score: float, details: list[str]}`
- `fixtures/` — Optional reference data for validation

## Important Gotchas

- The RPi runs commands via **non-interactive SSH**, so `~/.bashrc` is not sourced. `run.sh` explicitly adds `$HOME/.local/bin` to `$PATH`.
- The `hermes` CLI is installed at `/home/mcampo/.local/bin/hermes` on the Pi.
- Always use **absolute imports** in `src/` modules (not relative imports like `from .module`).
