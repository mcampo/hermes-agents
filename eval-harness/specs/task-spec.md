# Feature Specification: Evaluation Task Interface

**Feature Branch**: `eval-task-spec`

**Created**: 2026-07-17

**Status**: Approved

**Input**: User description: "let's add a spec for what each individual task implementation should have at a minimum"

---

## Purpose

This specification defines the minimal interface and structural contract that every individual evaluation task must implement to be integrated with the Evaluation Harness Framework. Task implementations must isolate their reset logic, execution configuration, validation rules, and success fixtures to ensure modularity.

---

## Minimal Task Directory Layout

Every evaluation task must live inside its own subdirectory within the repository's `tasks` directory, adhering to the following minimal layout:

```text
tasks/[task-name]/
├── reset.*          # Executable script or code module to clear and baseline the environment
├── validator.*      # Script or code module to run validation checks and output scores
├── fixtures/        # Folder containing expectations and reference datasets
│   └── expected.*   # Machine-readable expected outcomes (e.g. expected.json)
└── config.json      # Metadata containing the prompt, required skills, and constraints
```

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Environment State Reset Hook (Priority: P1)

Each task must provide a reliable state reset mechanism to ensure runs are executed from a clean baseline.

**Why this priority**: Required to prevent carry-over data contamination between evaluation iterations.

**Independent Test**: Put mock files or modified records in the task's target environment, trigger the reset hook, and verify that the environment is restored to its exact baseline state.

**Acceptance Scenarios**:
1. **Given** an environment altered by a previous agent run, **When** the harness invokes the task's `reset` hook, **Then** all modified values, uploaded files, or email read-states are reverted or deleted, returning the environment to its initial test baseline.

---

### User Story 2 - Execution Payload Configuration (Priority: P1)

Each task must provide a configuration file declaring the prompt string, required skills, timeout limits for the Hermes Agent CLI, and any optional task-specific parameters (such as resource IDs, search tags, or API credentials) needed for execution and validation.

**Why this priority**: Enforces metadata segregation so that the harness does not contain hard-coded, task-specific parameters or identifiers.

**Independent Test**: Load the task's config file containing both default framework fields and custom keys, and verify the harness and validator can parse the entire configuration successfully.

**Acceptance Scenarios**:
1. **Given** a task configuration file (`config.json`), **When** read by the harness, **Then** it must provide:
   - `prompt`: The exact prompt query to be passed to the agent.
   - `skills`: An array of required skills/toolsets to enable.
   - `timeout` (optional): Task-specific maximum execution duration in seconds.
2. **Given** a task requiring specific environment parameterization (e.g., target spreadsheet IDs, search tags, or custom API credentials), **When** reading `config.json`, **Then** the configuration can optionally provide these custom keys in a task-specific metadata structure, which is accessible to the task's execution and validation scripts.

---

### User Story 3 - Accuracy Validation and Score Computation (Priority: P1)

Each task must implement custom validation logic that compares the final state of the environment against expected fixtures, producing a normalized score and detailed validation reports.

**Why this priority**: Standardizes verification metrics across diverse tasks (e.g., matching sheets, scraping, file systems).

**Independent Test**: Feed the validator correct, partially correct, and incorrect final environment states, and assert the output scores match the expected percentages.

**Acceptance Scenarios**:
1. **Given** a completed task run, **When** the harness invokes the task's `validator`, **Then** the validator returns a standardized floating-point accuracy score between `0.0` (complete failure) and `1.0` (perfect match).
2. **Given** the validation execution, **When** compiling results, **Then** the validator outputs a detailed log string of checks passed/failed, which populates the `validation_details` field in the harness schema.

---

### User Story 4 - Machine-Readable Expected Fixtures (Priority: P2)

Each task must supply reference fixtures representing the expected outcomes to support validation scoring.

**Why this priority**: Decouples validation code from hard-coded assertion datasets.

**Independent Test**: Verify that the fixture file exists and matches the format required by the task validator.

**Acceptance Scenarios**:
1. **Given** a task implementation, **When** inspecting the `fixtures` directory, **Then** there is a structured data file (e.g. JSON, CSV, or YAML) listing the expected final state entries (such as cell values, uploaded filenames, or read states) for comparison.

## Optional Harness Traceability Configuration

A task that needs an executed benchmark sidecar may declare these optional,
task-agnostic fields in `config.json`:

```json
{
  "benchmark_metadata": {
    "manifest_path": "benchmark-manifest.json",
    "include": ["fixture_revision", "scoring_revision"]
  },
  "runtime_artifacts": {
    "TASK_LEDGER_DIR": "ledgers"
  }
}
```

`manifest_path` is relative to the task directory and `include` is an explicit
allowlist of top-level JSON fields. The harness snapshots only those fields
before model execution. `runtime_artifacts` maps task-defined environment
variables directly to relative directory categories; the harness allocates a
distinct directory for every run and passes it to the model process. These
fields are optional, so tasks without them keep the minimal interface and do
not receive benchmark sidecars or runtime directories.
