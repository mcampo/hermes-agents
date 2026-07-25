# Feature Specification: Evaluation Harness Framework

**Feature Branch**: `eval-harness-spec`

**Created**: 2026-07-16

**Status**: Approved

**Input**: User description: "help me create a spec file for the eval harness in the style of Agentic Spec-Driven Development (SDD)"

---

## Purpose

The Evaluation Harness Framework provides automated, repeatable, and isolated comparison of LLM agent performance across models on registered evaluation tasks. The framework utilizes the **Hermes Agent CLI** as the exclusive task executor engine, orchestrating state resets, agent execution, cost/token tracking, results validation, and session logging in a task-agnostic manner.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Multi-Model Evaluation Execution (Priority: P1)

Evaluate LLM agents across selected model configurations (combining model identifier and optional reasoning effort level) by executing tasks using the Hermes Agent CLI, logging performance and resource utilization metrics.

**Why this priority**: Core purpose of the framework is to enable comparative benchmarking of agent models under identical execution parameters.

**Required Metrics Schema**:
For each task run iteration, the harness must capture and record the following metrics:
*   **Metadata**:
    *   `timestamp` (number): Unix epoch timestamp of run start.
    *   `datetime` (ISO string): ISO 8601 representation of run start time.
    *   `provider`: LLM provider/routing channel used.
    *   `model`: Name/identifier of the model being evaluated.
    *   `reasoning_effort`: Level of reasoning effort configured (e.g., high, low, none).
    *   `config_name`: Unique configuration name, combining model name and reasoning effort.
    *   `task`: Name/identifier of the evaluation task executed.
    *   `run_number`: The specific run/iteration index.
    *   `session_id`: Unique identifier of the agent session trace.
*   **Execution & Token metrics**:
    *   `input_tokens`: Total input/context tokens consumed.
    *   `output_tokens`: Total output/generated tokens consumed.
    *   `cache_read_tokens`: Total tokens read from cache.
    *   `cache_write_tokens`: Total tokens written to cache.
    *   `reasoning_tokens`: Tokens spent on model reasoning.
    *   `total_tokens`: Total tokens overall (`input + output + cache_read + cache_write`).
    *   `api_calls`: Total count of model API requests.
    *   `tool_calls`: Total count of tool invocations performed by the agent.
    *   `message_count`: Total message count in the conversation.
    *   `elapsed_seconds`: Total runtime of the agent execution in seconds.
*   **Cost metrics**:
    *   `estimated_cost` (usd): Cost of the run in USD, estimated locally or from session history.
    *   `actual_cost` (usd): True financial cost in USD, tracked using provider-specific cost strategies. For providers where Hermes already computes an accurate cost estimate (e.g. DeepSeek), `actual_cost` reuses the session's `estimated_cost_usd` value.
*   **Validation metrics**:
    *   `validation_score`: Accuracy/success score between `0.0` and `1.0`.
    *   `validation_details`: String describing validation results and check outcomes.
*   **Artifacts & Logs**:
    *   `agent_output`: The text response/content output of the agent execution.
    *   `transcript_path`: The file system path to the exported JSON session transcript (as defined in User Story 7).

**Independent Test**: Configure the harness with a set of test model configurations (including reasoning effort settings), execute a run, and verify execution logs are written for each configuration.

**Acceptance Scenarios**:
1. **Given** a list of target model configurations, **When** executing the harness, **Then** the harness evaluates each configuration sequentially by running task commands via the `hermes` CLI and records all metrics defined in the Required Metrics Schema in the output results database/file.
2. **Given** a model configured multiple times with different reasoning effort levels (e.g. `deepseek-v4-flash` with `high` effort and `xhigh` effort), **When** executing the harness, **Then** the harness executes evaluations for both configurations independently, logging their respective reasoning effort values and config names.
3. **Given** a dry-run flag, **When** invoking the harness, **Then** it prints a summary plan showing which model configurations (including their effort levels) will be run without executing any actual agent tasks.
4. **Given** a custom timeout configuration, **When** running the evaluation, **Then** individual `hermes` CLI agent executions are terminated if they exceed the timeout limit.

---

### User Story 2 - Task Selection (Priority: P1)

Select and filter which registered evaluation tasks to run.

**Why this priority**: Developers must be able to target specific tasks or run subset combinations rather than being forced to run the full suite.

**Independent Test**: Verify that executing with specific task filters runs only those tasks.

**Acceptance Scenarios**:
1. **Given** multiple registered evaluation tasks, **When** starting a run filtering by task names, **Then** only the selected tasks are evaluated, and others are skipped.
2. **Given** a list command or flag, **When** querying the harness, **Then** it displays all registered tasks available for evaluation.

---

### User Story 3 - Configurable Run Iterations (Priority: P1)

Configure the harness to execute the selected tasks multiple times per model.

**Why this priority**: Running a task multiple times is necessary to collect statistically significant performance and cost metrics by averaging over multiple runs.

**Independent Test**: Configure the harness to execute with a specific run count, and verify that the harness runs exactly that number of iterations.

**Acceptance Scenarios**:
1. **Given** a specific execution run count configured (e.g., via CLI or config), **When** running the evaluation harness, **Then** it runs each selected task and model pair for that exact number of iterations and indexes each run.
2. **Given** no execution count is explicitly configured, **When** running the evaluation harness, **Then** it defaults to 1 run iteration.

---

### User Story 4 - Environment State Isolation & Reset (Priority: P1)

Reset the environment state prior to task execution to prevent data contamination between runs.

**Why this priority**: Required to guarantee repeatable, clean-slate evaluation conditions.

**Independent Test**: Populate the target environment with mock data, run the reset hook, and verify that the environment is restored to a clean state.

**Acceptance Scenarios**:
1. **Given** an evaluation task with a registered state-reset hook, **When** beginning an evaluation run, **Then** the harness executes the reset hook before initiating the agent to ensure all test resources are cleared.

---

### User Story 5 - Provider-Agnostic Cost and Token Tracking (Priority: P2)

Calculate financial costs of evaluation sessions using cost-tracking strategies tailored to each provider's capabilities, recognizing that each provider may require implementing its own strategy.

**Why this priority**: Essential for comparing the financial efficiency of different agent configurations and routing providers.

**Independent Test**: Register multiple mock providers requiring different cost strategies, run sessions, and verify each delegates to its corresponding strategy.

**Acceptance Scenarios**:
1. **Given** a provider requiring a balance-snapshot cost strategy, **When** executing a run, **Then** the harness delegates to that specific strategy, querying account balances before and after the session (with a configurable delay for API reconciliation) to capture exact actual usage cost.
2. **Given** a provider where Hermes already computes an accurate cost estimate in `estimated_cost_usd` (e.g. DeepSeek), **When** executing a run, **Then** the harness's cost tracker reads the session's `estimated_cost_usd` value directly from the database metrics instead of duplicating the pricing calculation.
3. **Given** multiple different providers configured in the harness, **When** running evaluations, **Then** the harness dynamically matches and executes the specific cost strategy implemented for each provider.

---

### User Story 6 - Automated Results Verification & Scoring (Priority: P1)

Validate task outputs against expected fixtures, generate a normalized accuracy score, and populate the validation-related fields in the session metrics schema.

**Why this priority**: Provides objective, standardized metrics for assessing agent success.

**Independent Test**: Register a mock task validator with mock expected results, and check that correct/incorrect outputs yield expected scores between 0.0 and 1.0.

**Acceptance Scenarios**:
1. **Given** a completed task run, **When** verifying the results, **Then** the harness triggers the task's custom validator to compare actual outputs against expected fixtures.
2. **Given** the validation results, **When** compiling evaluation metrics, **Then** the harness generates a normalized accuracy score between 0.0 (completely incorrect) and 1.0 (perfectly correct), populates `validation_score` and `validation_details` in the metrics record, and logs detailed validation breakdowns.

---

### User Story 7 - Session Logging and Trace Export (Priority: P2)

Save normalized session logs and traces to enable execution review and debugging, and record the destination path in the metrics schema.

**Why this priority**: Crucial for troubleshooting failed agent runs and analyzing decision-making behavior.

**Independent Test**: Confirm a standard JSON log containing messages, tool actions, and model reasoning is created in the results directory after execution.

**Acceptance Scenarios**:
1. **Given** a completed evaluation run, **When** logging the session, **Then** the harness extracts raw database traces, normalizes them, writes a structured JSON transcript file to the results directory, and records the file path in `transcript_path` within the session metrics schema.

---

### User Story 8 - Google Sheets Persistence (Priority: P2)

Persist evaluation results directly to a Google Spreadsheet.

**Why this priority**: While local CSV storage is functional, a centralized Google Spreadsheet enables easier collaboration, filtering, and cross-session tracking for remote teams without requiring file uploads.

**Prerequisites**: The harness runs on a headless Raspberry Pi without a browser. Google Sheets authentication requires a one-time OAuth2 authorization flow performed on a local machine with a browser. This flow produces an `authorized_user.json` token file that must be copied to the RPi before running the harness with Google Sheets enabled.

**Independent Test**: Verify that executing with a Google Sheets configuration and a valid token file adds a row matching the exact 26-column schema to the specified spreadsheet, and that providing an empty sheet automatically initializes the header row.

**Acceptance Scenarios**:
1. **Given** a `google_sheets` configuration in the global `config.json` pointing to a valid `authorized_user.json` token file, **When** executing a run, **Then** the harness appends the exact 26-field metrics schema to the remote spreadsheet.
2. **Given** a completely empty Google Sheet, **When** executing a run, **Then** the harness initializes it with a header row of the 26-field names before appending the first result.
3. **Given** a network or authentication failure during Google Sheets persistence, **When** executing a run, **Then** the harness logs a warning to the console and continues without crashing, preserving the local CSV backup.
4. **Given** a local machine with a browser and the `google_client_secret.json` file, **When** running the `generate_google_token` helper from `sheets.py`, **Then** it performs the OAuth2 flow and writes the `authorized_user.json` token file that can be copied to the RPi.

