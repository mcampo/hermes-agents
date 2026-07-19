# Evaluation Harness

A modular, task-agnostic evaluation harness framework that dynamically discovers evaluation tasks from a `tasks/` directory, supports per-model reasoning effort configurations, uses provider-specific cost-tracking strategies, and outputs a standardized 26-field metrics schema.

## Architecture

The harness is divided into:
- **`src/harness.py`**: Main orchestrator loop
- **`src/task_registry.py`**: Dynamic discovery of tasks from `tasks/*/config.json`
- **`src/executor.py`**: Wraps the `hermes` CLI
- **`src/cost_tracker.py`**: Factory and strategies for provider-specific cost calculation
- **`src/metrics.py` & `src/session_logger.py`**: Reads `state.db` to extract token metrics and chat transcripts
- **`src/results.py`**: Writes outputs to a CSV file

## Quick Start

Run the evaluation harness using the wrapper script:

```bash
# Run a dry run to see the plan
./run.sh --dry-run

# List all discovered tasks
./run.sh --list-tasks

# Run a specific task with all models configured in config.json
./run.sh --tasks mock-echo --runs 1
```

For more details, see the specifications in `specs/`.

## Installation (Optional)

If you are using Google Sheets persistence, install the required dependencies inside your virtual environment using `uv` (or `pip`):

```bash
# Activate your virtual environment first, then:
uv pip install -r requirements.txt
```

