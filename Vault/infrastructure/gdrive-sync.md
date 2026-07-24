# 🔁 Google Drive Vault Mirror

**Added:** 2026-07-24
**Purpose:** Mirror `CLAUDE.md` + `Vault/**/*.md` to a Google Drive folder
(**"JCF HQ Vault"**) so Claude (chat) can read current project state via the
Google Drive connector — no manual pasting of updates.

## Pieces
| Piece | Path |
|---|---|
| Sync script | `scripts/gdrive_sync.py` |
| One-time OAuth | `scripts/gdrive_auth.py` |
| Cron wrapper | `scripts/run_gdrive_sync.sh` |
| Credentials (gitignored) | `credentials/gdrive/client_secret.json` + `token.json` |
| Change manifest | `state/gdrive_sync_manifest.json` |
| Log | `logs/gdrive_sync.log` |
| Python | `venv/bin/python3` (google libs live in the venv — system Python is PEP-668 managed) |

## Why OAuth, not a service account
The Google account is a **personal `@gmail.com`**. Service accounts have no
storage quota in consumer Drive, so SA-owned uploads fail with
`storageQuotaExceeded` — even into a folder shared with them. OAuth *user*
credentials make the VPS act as the account owner: files are owned by the user,
live in the user's Drive, and are directly readable by the connector.

- **Scope:** `drive.file` (least privilege — the app only sees files it created).
- **Refresh-token durability:** only long-lived if the OAuth consent screen is
  **published to "In production."** In "Testing" status Google expires refresh
  tokens after 7 days, which would silently break the cron weekly.

## How the sync works
1. Discover `CLAUDE.md` + every `Vault/**/*.md` (34 files at creation).
2. SHA-256 each; compare to the manifest. Unchanged → skip (near-zero API calls
   on idle runs). Changed → update the existing Drive file by id. New → create.
3. Mirror the local tree: root folder **"JCF HQ Vault"**, with `Vault/agents/`,
   `Vault/decisions/`, `Vault/sessions/`, `Vault/strategies/`,
   `Vault/infrastructure/`, `Vault/agents/_benched/` as nested subfolders.
4. Manifest (`state/gdrive_sync_manifest.json`) caches folder ids + per-file
   `{id, hash}` so structure isn't rebuilt each run. Loss of the manifest is
   safe — the script re-discovers app-created folders/files by name.

`gdrive_sync.py --dry-run` plans actions (create/update/skip) with **no API
calls and no credentials** — used to validate discovery + change-detection.

## Trigger: cron (not a post-commit hook)
`#HOLD */30 * * * * scripts/run_gdrive_sync.sh` — **held** until OAuth is set up;
remove `#HOLD` to activate.

Chosen over a post-commit hook because:
- Vault edits land from **either** the VPS or the laptop; a git hook only fires
  on the machine doing the commit and would need creds present there.
- No commit latency; Drive API hiccups don't block commits.
- Self-healing — a failed run just retries on the next tick.
- Hash-based skip makes idle 30-min runs cheap.

## One-time setup (Jase — manual)
See the session note [[../sessions/2026-07-24]] for the click-by-click Google
Cloud Console runbook. Summary:
1. Cloud Console → new/at existing project → **enable the Google Drive API**.
2. **OAuth consent screen:** External; add yourself as a test user; **Publish to
   Production** (for durable refresh tokens).
3. **Credentials → OAuth client ID → Desktop app** → download JSON →
   save as `credentials/gdrive/client_secret.json` on the VPS.
4. Run `gdrive_auth.py` once → open the URL, approve, paste the code → mints
   `token.json`.
5. Run `gdrive_sync.py` once to verify, then remove `#HOLD` on the cron line.

## Related
- Documented in [[../../CLAUDE.md]] §4e.
- [[config]] — openclaw.json config-edit rules (never sed; use `openclaw config`).
