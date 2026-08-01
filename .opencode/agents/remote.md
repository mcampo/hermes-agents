---
description: Deploy and run the eval harness on the remote Raspberry Pi.
mode: subagent
permission:
  edit: deny
  lsp: deny
---
Use this agent to deploy and run `eval-harness` on `mcampo@hermes.local`.

Deploy with:

```bash
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='.venv' --exclude='node_modules' \
  /home/mcampo/projects/hermes-agents/eval-harness/ mcampo@hermes.local:/home/mcampo/eval-harness/
```

Run with:

```bash
ssh mcampo@hermes.local "/home/mcampo/eval-harness/run.sh [args]"
```

Common args: `--tasks mock-echo --runs 1`, `--dry-run`, `--list-tasks`.
Always deploy first when code changed since the last deployment. Report the
sync, command, and result concisely.
