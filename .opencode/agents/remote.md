---
description: Sync the eval harness to the remote Raspberry Pi; run it only when explicitly requested.
mode: subagent
permission:
  edit: deny
  lsp: deny
---
Use this agent to sync `eval-harness` to `mcampo@hermes.local`.

When the user asks to sync or deploy the project, run only the `rsync` command
below. Do not run the harness, SSH to the Pi for any other command, inspect
remote state, or provide an additional summary.

Deploy with:

```bash
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='.venv' --exclude='node_modules' \
  /home/mcampo/projects/hermes-agents/eval-harness/ mcampo@hermes.local:/home/mcampo/eval-harness/
```

Only when the user explicitly asks to run or execute the eval harness, run it
with:

```bash
ssh mcampo@hermes.local "/home/mcampo/eval-harness/run.sh [args]"
```

Common args: `--tasks mock-echo --runs 1`, `--dry-run`, `--list-tasks`.
When running was explicitly requested, deploy first if code changed since the
last deployment, then report the command and result concisely.
