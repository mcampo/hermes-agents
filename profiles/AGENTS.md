# Profile Source Conventions

`profiles/<name>/` is the canonical, repository-side definition of a Hermes
profile. Edit these files in Git, not in the live profile on the RPi.

Keep each profile's deployment surface explicit. For Mojo, the deployer owns
only:

- `config.yaml`
- `SOUL.md`
- `cron/jobs.json`
- `scripts/`
- `skills/custom/`

`.env.example` documents required secret names and setup instructions only. It
must contain no values and is not a replacement for the live `.env`.

Do not commit `.env`, `auth.json`, OAuth credentials, tokens, passwords,
conversation exports, databases, caches, `__pycache__/`, or bytecode. Bundled
Hermes skills remain remote-managed; custom skills belong under
`skills/custom/`.

Deployments may use a dirty worktree for verification, but the repository is
not a recovery point until the definition is committed and tagged. Deploy
scripts must be additive: overwrite the allowlisted definition files, never
mirror-delete the profile, and preserve runtime/user data.

Keep profile-specific scripts direct. Do not add a generic profile deployer,
distribution manifest, rollback layer, or CI for this workflow.
