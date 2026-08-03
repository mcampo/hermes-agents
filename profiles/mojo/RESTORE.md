# Mojo Restore

This is a command-oriented recovery procedure, not an automatic restore
script. Archives may contain sensitive conversations, memories, sessions, and
profile databases even though primary Hermes credential files such as `.env`
and `auth.json` are excluded.

Use `hermes.local` below, or set the same target override used by deployment:

```bash
export HERMES_MOJO_SSH_TARGET=hermes.local
```

## Recovery Order

1. Install the current Hermes release on the RPi/recovery target. Do not
   assume the archived Hermes version is still installed.
2. Download the selected `mojo` archive manually from Drive to that target,
   or transfer it there securely. Do not put the archive or its extracted
   contents in Git.
3. Import it on the target as `mojo` before the profile exists:

   ```bash
   ssh "${HERMES_MOJO_SSH_TARGET:-hermes.local}" '$HOME/.local/bin/hermes profile import /path/to/mojo-YYYY-MM-DD.tar.gz --name mojo'
   ```

   The named-profile export contains profile data such as memories, sessions,
   and databases, but excludes `.env` and `auth.json`.

4. Clone this repository on the workstation and deploy the repository-owned
   definition. This makes Git-owned config, soul, cron, scripts, and custom
   skills authoritative over the archive copy:

   ```bash
   git clone <private-repository-url> hermes-agents
   cd hermes-agents
   profiles/mojo/deploy
   ```

   Set `HERMES_MOJO_SSH_TARGET` first if the recovery target is not
   `hermes.local`.

5. Restore or re-authorize credentials on the RPi using the names and
   instructions in `profiles/mojo/.env.example`. Keep actual values only in
   the remote `.env`; never add them to Git. The normal interactive setup can
   be launched remotely with:

   ```bash
   ssh "${HERMES_MOJO_SSH_TARGET:-hermes.local}" '$HOME/.local/bin/hermes -p mojo setup'
   ```

6. Reinstall the backup job after the backup portion of this profile is
   present. Run this on the RPi/recovery target from its checkout of this
   repository, not on the workstation:

   ```bash
    ssh "${HERMES_MOJO_SSH_TARGET:-hermes.local}" \
      'cd /path/to/hermes-agents && profiles/mojo/setup-backup'
   ```

   If the repository is not cloned on the target, transfer the repository
   checkout there first. The command stores the Drive folder ID and alert
   recipient under `~/.config/hermes/mojo-backup.env`, outside Git.

7. Verify the recovered profile:

   ```bash
   ssh "${HERMES_MOJO_SSH_TARGET:-hermes.local}" '$HOME/.local/bin/hermes profile show mojo'
   ssh "${HERMES_MOJO_SSH_TARGET:-hermes.local}" '$HOME/.local/bin/hermes -p mojo skills list'
   ssh "${HERMES_MOJO_SSH_TARGET:-hermes.local}" '$HOME/.local/bin/hermes -p mojo gateway restart'
   ```

   Confirm the `mojo` alias, gateway, memories and sessions, cron declarations,
   and discovery of `skills/custom/gastos-vencimientos/`. A new session or
   `/reset` may be needed before an existing conversation sees changed
   definition files.

Do not delete unrelated profiles or data as part of recovery. If the archive
was imported into an already-populated machine, stop and resolve the profile
name collision before taking any destructive action.
