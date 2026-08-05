# Mojo Profile

Canonical repository definition for the single live `mojo` Hermes profile.
The last-tested Hermes version was `v0.20.0 (2026.8.3)`; Hermes is not
pinned by this profile.

## Source Layout

The intended repository-owned definition is:

```text
profiles/mojo/
├── .env.example
├── README.md
├── RESTORE.md
├── SOUL.md
├── config.yaml
├── deploy
├── setup-backup
├── cron/
│   └── jobs.json
├── scripts/
├── skills/
│   └── custom/
│       └── gastos-vencimientos/
└── ops/
    ├── backup
    ├── hermes-mojo-backup.service
    └── hermes-mojo-backup.timer
```

The definition files here were imported from the live Mojo source. Do not
create placeholder config, soul, cron, script, or skill content. Private
values in the custom skill are externalized to the live `.env`; the imported
behavior and remaining source are preserved. The imported paths are:

- `config.yaml`
- `SOUL.md`
- `scripts/daily_weather.py`
- `cron/jobs.json`
- `skills/custom/gastos-vencimientos/` from the live Mojo skill
- `.env.example`, containing secret names and setup/retrieval instructions but
  no values

The Mojo `gastos-vencimientos` skill is distinct from the eval-harness copy.
Keep its Mojo behavior here; private recipient/resource/password values are
externalized to the live `.env` rather than stored in Git. Do not reconcile it
with the eval-harness copy.

Do not add `distribution.yaml`. This profile uses the repository deployer,
not Hermes distribution install/update.

## Ownership

`deploy` syncs only `config.yaml`, `SOUL.md`, `cron/jobs.json`, `scripts/`, and
`skills/custom/`. `.env.example` is repository documentation and is not copied
over the live `.env`.

The remote profile remains authoritative for runtime and user data, including
`.env`, `auth.json`, memories, sessions, databases, logs, caches, gateway
state, bundled skills, and custom skills absent from this repository. Matching
repository-owned files are overwritten. Nothing is mirror-deleted.

The one-time migration cleanup is intentionally manual and happens only after
the imported custom skill has been deployed and byte-verified. Remove the old
`skills/productivity/gastos-vencimientos` path only then. The six rejected
local skills from the handoff must also be removed manually; `deploy` never
performs destructive cleanup.

## Deploy

Prerequisites: local `ssh` and `rsync`; SSH access to the RPi; and Hermes at
`$HOME/.local/bin/hermes` on the RPi.

The default SSH target is `hermes.local`. Override the target with one
environment variable:

```bash
HERMES_MOJO_SSH_TARGET=user@host profiles/mojo/deploy
```

Normal deployment:

```bash
profiles/mojo/deploy
```

If the remote `mojo` profile does not exist, the script runs
`hermes profile create mojo` without `--no-skills`, preserving Hermes bundled
skill bootstrap. It then:

1. Runs a custom-skill-only rsync dry run with deletion reporting. Any
   remote-only `skills/custom/` content is printed for review.
2. Syncs the explicit repository allowlist additively. The real sync never
   passes `--delete`.
3. Restarts the gateway with
   `$HOME/.local/bin/hermes -p mojo gateway restart`.

The dry-run `--delete` is reporting-only. It cannot remove remote content;
the actual sync preserves remote-only custom skills and all runtime files.
An existing conversation may need a new session or `/reset` to consume a
changed `SOUL.md` or skill.

The script refuses to run while intended runtime source paths are absent. It
does not export, stage, roll back, require a clean worktree, or deploy a
generic profile.

## Backup

Run `setup-backup` on the RPi, not the workstation. It uses the existing
bundled Google Workspace wrapper to create or reuse `Hermes Backups/mojo`,
prompts for the alert recipient, stores both outside Git in
`~/.config/hermes/mojo-backup.env`, and installs a user-level systemd timer for
06:00 `America/Argentina/Buenos_Aires`.

```bash
profiles/mojo/setup-backup
systemctl --user status hermes-mojo-backup.timer
journalctl --user -u hermes-mojo-backup.service
```

The job stops Mojo only when it was running, exports a named profile archive,
validates it, uploads through the existing wrapper, keeps 7 daily and 4 weekly
restore points, trashes aged-out Drive files, and sends one failure email after
attempting to restore the gateway. The local archive is removed only after a
confirmed upload; one failed archive is retained for diagnosis or retry.

## Initial Migration Notes

Import source copies before destructive live cleanup. The initial live Mojo
skill source is `skills/productivity/gastos-vencimientos/`, copied to
`profiles/mojo/skills/custom/gastos-vencimientos/`. Do not replace it with
`eval-harness/tasks/gastos-vencimientos/skill/`.

The old local paths to remove after verification are:

- `skills/autonomous-ai-agents/cron-jobs`
- `skills/autonomous-ai-agents/hermes-profile-lifecycle`
- `skills/autonomous-ai-agents/hermes-usage-audit`
- `skills/productivity/argentina-shopping-research`
- `skills/productivity/product-research`
- `skills/software-development/model-comparison`

Do not version bundled `google-workspace` as custom source. Generated
`__pycache__` files are not source.
