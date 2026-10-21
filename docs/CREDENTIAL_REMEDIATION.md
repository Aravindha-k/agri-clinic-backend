# Credential & Data Exposure Remediation

Status: **prepared, not executed.** All rotation/history-rewrite actions are
operator tasks — do not perform without explicit approval.

## Findings (verified without printing values)

1. **`render.production.env`** — present in the working tree, **gitignored and
   never committed** (confirmed via `git check-ignore` + `git ls-files` +
   `git log --all`). It contains Render Postgres connection material left over
   from the archived Render deployment. Even uncommitted, the *Render
   Postgres password may have been shared/stored in plaintext* and the earlier
   audit flagged a Render credential as exposed.

2. **Committed DB dumps** — `agri_backup.dump`, `agri_backup.sql`,
   `agri_full_backup.sql` are **tracked in Git history** (commit `bc1ea93`,
   "AWS deployment ready"). These dumps likely contain production data,
   including user rows and **password hashes**. The repo may be private, but
   the files are in history permanently until rewritten.

3. `.gitignore` now also covers `*.dump` / `*.sql` to prevent recurrence.

## Remediation plan (operator actions, in order)

### A. Rotate credentials (no repo change needed)

- [ ] Render Postgres: rotate the database password (Render dashboard →
      database → reset password). Render path is archived, but rotate anyway —
      treat anything in `render.production.env` as compromised.
- [ ] AWS/EC2 Postgres (`agri_clinic_db`): rotate the `DB_USER` password and
      update server `.env` + restart `agri-backend.service` during a window.
- [ ] `OPS_BACKUP_ENCRYPTION_KEY` GitHub secret: rotate if the dumps' exposure
      window overlaps its use.
- [ ] Any Django `SECRET_KEY` that ever lived in a committed file: rotate.
      (Current `.env` is untracked — verify no secret was ever committed by
      searching history: `git log -p --all -S'SECRET_KEY=' -- '*.env*'`
      shows presence only, not values.)

### B. Remove committed dumps from the repo

```bash
# Remove from tracking but keep local copies
git rm --cached agri_backup.dump agri_backup.sql agri_full_backup.sql
git commit -m "chore: untrack database dumps"
```

Files remain in **history** — to purge fully (requires coordination +
force-push; **not authorized here**):

```bash
git filter-repo --invert-paths \
  --path agri_backup.dump --path agri_backup.sql --path agri_full_backup.sql
# then force-push all branches; every clone must re-clone or reset.
```

Until history is rewritten, assume the data inside those dumps is exposed.

### C. Verify nothing else is tracked

```bash
git ls-files | grep -E '\.(env|dump|sql|pem|ppk|key)$'
# Expect: only *.example templates and safe seed fixtures.
```

## Acceptance criteria

- `git ls-files` shows no dumps/env files.
- Render + AWS DB passwords rotated; server `.env` updated; service verified.
- History rewrite ticketed/scheduled (needs owner approval for force-push).
