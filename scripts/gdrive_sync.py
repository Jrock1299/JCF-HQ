#!/usr/bin/env python3
"""
gdrive_sync.py — mirror /root/.openclaw/CLAUDE.md and Vault/**/*.md to a Google
Drive folder ("JCF HQ Vault"), so Claude (chat) can read current project state
via the Google Drive connector without manual pasting.

Auth:      OAuth user credentials (token.json minted by gdrive_auth.py),
           auto-refreshed. Least-privilege scope: drive.file.
Structure: Drive mirrors the local tree — CLAUDE.md at the folder root, and
           Vault/agents/, Vault/decisions/, ... as nested subfolders.
Efficient: only changed files are re-uploaded (SHA-256 content hash vs manifest).
Logging:   appends to logs/gdrive_sync.log.

Usage:
    /root/.openclaw/venv/bin/python3 scripts/gdrive_sync.py            # real sync
    /root/.openclaw/venv/bin/python3 scripts/gdrive_sync.py --dry-run  # plan only,
                                                    no API calls, no creds needed
"""
import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

OPENCLAW   = Path('/root/.openclaw')
CRED_DIR   = OPENCLAW / 'credentials' / 'gdrive'
TOKEN      = CRED_DIR / 'token.json'
MANIFEST   = OPENCLAW / 'state' / 'gdrive_sync_manifest.json'
LOG_PATH   = OPENCLAW / 'logs' / 'gdrive_sync.log'
ALERT_SENTINEL = OPENCLAW / 'state' / 'gdrive_auth_alert.sent'
ALLOWFROM  = OPENCLAW / 'credentials' / 'telegram-default-allowFrom.json'
OWNER_CHAT_FALLBACK = '797062420'   # owner Telegram chat id (from allowFrom)
ROOT_NAME  = 'JCF HQ Vault'
SCOPES     = ['https://www.googleapis.com/auth/drive.file']
FOLDER_MIME = 'application/vnd.google-apps.folder'
FILE_MIME   = 'text/markdown'

log = logging.getLogger('gdrive_sync')


def _setup_logging() -> None:
    # File-only so cron's `>> log 2>&1` redirect doesn't double-write INFO lines.
    # User-facing summaries use print() and appear on the terminal for manual runs.
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_PATH)
    fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    log.addHandler(fh)


# ── File discovery + hashing ────────────────────────────────────────────────────

def _files_to_sync() -> list[Path]:
    """CLAUDE.md at root + every .md under Vault/ (sorted, structure preserved)."""
    files: list[Path] = []
    claude = OPENCLAW / 'CLAUDE.md'
    if claude.exists():
        files.append(claude)
    vault = OPENCLAW / 'Vault'
    if vault.is_dir():
        files.extend(sorted(vault.rglob('*.md')))
    return files


def _rel(local: Path) -> str:
    """Path relative to /root/.openclaw, POSIX — the Drive-side identity key."""
    return local.relative_to(OPENCLAW).as_posix()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── Manifest ────────────────────────────────────────────────────────────────────

def _load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text())
        except Exception as e:
            log.warning('manifest unreadable (%s) — starting fresh', e)
    return {'root_folder_id': None, 'folders': {}, 'files': {}}


def _save_manifest(m: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(m, indent=2))
    tmp.replace(MANIFEST)


# ── Auth-expiry Telegram alert (via the openclaw gateway) ───────────────────────

def _owner_chat_id() -> str:
    try:
        ids = json.loads(ALLOWFROM.read_text()).get('allowFrom') or []
        if ids:
            return str(ids[0])
    except Exception:
        pass
    return OWNER_CHAT_FALLBACK


def _alert_auth_expired(detail: str) -> None:
    """Telegram-alert the owner that the Drive token died, via the gateway
    (`openclaw message send`). Throttled to once per outage by a sentinel file
    so the 30-min cron doesn't spam once expired."""
    if ALERT_SENTINEL.exists():
        return
    msg = (
        '🔧 JCF HQ — Google Drive Vault sync AUTH EXPIRED.\n\n'
        'The OAuth refresh token was rejected — Testing-mode tokens expire ~7 '
        'days after issuance. Vault→Drive sync is PAUSED until you re-auth.\n\n'
        'Re-auth (in an HQ session):\n'
        '  /root/.openclaw/venv/bin/python3 /root/.openclaw/scripts/gdrive_auth.py\n'
        'then run gdrive_sync.py to confirm.'
    )
    try:
        r = subprocess.run(
            ['openclaw', 'message', 'send', '--channel', 'telegram',
             '--target', _owner_chat_id(), '--message', msg],
            capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            ALERT_SENTINEL.parent.mkdir(parents=True, exist_ok=True)
            ALERT_SENTINEL.write_text(detail[:200])
            log.info('auth-expiry Telegram alert sent to owner')
        else:
            log.error('auth-expiry alert send failed: %s',
                      (r.stderr or r.stdout or '')[:200])
    except Exception as e:
        log.error('auth-expiry alert exception: %s', e)


def _clear_auth_alert() -> None:
    """Reset the alert throttle once creds are healthy — a future expiry
    re-alerts."""
    try:
        ALERT_SENTINEL.unlink()
    except FileNotFoundError:
        pass


# ── Drive credentials + service ─────────────────────────────────────────────────

def _service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError
    from googleapiclient.discovery import build

    if not TOKEN.exists():
        sys.exit(f'ERROR: {TOKEN} missing — run gdrive_auth.py once first.')
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as e:
                # Testing-mode refresh tokens die after ~7 days -> alert + pause.
                _alert_auth_expired(str(e))
                log.error('token refresh failed (%s) — Drive sync paused '
                          'until re-auth', e)
                sys.exit(2)
            TOKEN.write_text(creds.to_json())
            os.chmod(TOKEN, 0o600)
            log.info('access token refreshed')
        else:
            _alert_auth_expired('credentials present but not refreshable')
            sys.exit('ERROR: credentials invalid and not refreshable — '
                     're-run gdrive_auth.py.')
    _clear_auth_alert()  # creds healthy -> reset the alert throttle
    return build('drive', 'v3', credentials=creds, cache_discovery=False)


# ── Drive folder helpers ────────────────────────────────────────────────────────

def _folder_exists(svc, fid: str) -> bool:
    from googleapiclient.errors import HttpError
    try:
        meta = svc.files().get(fileId=fid, fields='id,trashed').execute()
        return not meta.get('trashed', False)
    except HttpError:
        return False


def _find_child(svc, name: str, parent_id: str | None, folder: bool) -> str | None:
    """Find a non-trashed child (folder or file) by name under parent."""
    q = [f"name = {json.dumps(name)}", 'trashed = false']
    q.append(f"mimeType {'=' if folder else '!='} '{FOLDER_MIME}'")
    if parent_id:
        q.append(f"'{parent_id}' in parents")
    resp = svc.files().list(
        q=' and '.join(q), spaces='drive',
        fields='files(id,name)', pageSize=10,
    ).execute()
    files = resp.get('files', [])
    return files[0]['id'] if files else None


def _create_folder(svc, name: str, parent_id: str | None) -> str:
    body = {'name': name, 'mimeType': FOLDER_MIME}
    if parent_id:
        body['parents'] = [parent_id]
    fid = svc.files().create(body=body, fields='id').execute()['id']
    log.info('created folder %r (id=%s)', name, fid)
    return fid


def _ensure_root(svc, m: dict) -> str:
    fid = m.get('root_folder_id')
    if fid and _folder_exists(svc, fid):
        return fid
    fid = _find_child(svc, ROOT_NAME, None, folder=True) \
        or _create_folder(svc, ROOT_NAME, None)
    m['root_folder_id'] = fid
    return fid


def _ensure_dir(svc, m: dict, root_id: str, rel_dir: str) -> str:
    """Ensure a POSIX dir path (e.g. 'Vault/agents') exists under root; cache ids."""
    if rel_dir in ('', '.'):
        return root_id
    cache = m.setdefault('folders', {})
    if rel_dir in cache and _folder_exists(svc, cache[rel_dir]):
        return cache[rel_dir]
    parent_rel, name = os.path.split(rel_dir)
    parent_id = _ensure_dir(svc, m, root_id, parent_rel)
    fid = _find_child(svc, name, parent_id, folder=True) \
        or _create_folder(svc, name, parent_id)
    cache[rel_dir] = fid
    return fid


# ── Sync ────────────────────────────────────────────────────────────────────────

def _plan(m: dict) -> list[tuple[str, Path, str]]:
    """Return [(action, path, hash)] where action in {create, update, skip}."""
    plan = []
    known = m.get('files', {})
    for p in _files_to_sync():
        rel = _rel(p)
        h = _sha256(p)
        rec = known.get(rel)
        if not rec or 'id' not in rec:
            plan.append(('create', p, h))
        elif rec.get('hash') != h:
            plan.append(('update', p, h))
        else:
            plan.append(('skip', p, h))
    return plan


def dry_run() -> int:
    m = _load_manifest()
    plan = _plan(m)
    n = {'create': 0, 'update': 0, 'skip': 0}
    print(f'DRY RUN — {len(plan)} file(s); manifest: '
          f'{"present" if MANIFEST.exists() else "none (all would be created)"}\n')
    for action, p, h in plan:
        n[action] += 1
        print(f'  {action.upper():6} {_rel(p):40} {h[:12]}')
    print(f'\n  create={n["create"]}  update={n["update"]}  skip={n["skip"]}')
    print('  (no API calls made, no credentials required)')
    return 0


def _upload(svc, m: dict, root_id: str, action: str, path: Path, h: str) -> None:
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError

    rel = _rel(path)
    drive_dir = os.path.dirname(rel)                 # '' for CLAUDE.md
    parent_id = _ensure_dir(svc, m, root_id, drive_dir)
    media = MediaFileUpload(str(path), mimetype=FILE_MIME, resumable=False)
    rec = m.setdefault('files', {}).get(rel, {})
    name = path.name

    try:
        if action == 'update' and rec.get('id'):
            svc.files().update(fileId=rec['id'], media_body=media).execute()
            fid = rec['id']
        else:
            fid = svc.files().create(
                body={'name': name, 'parents': [parent_id]},
                media_body=media, fields='id',
            ).execute()['id']
    except HttpError as e:
        # Stale id (file removed in Drive) -> recreate.
        if action == 'update' and getattr(e, 'resp', None) is not None \
                and e.resp.status in (404, 403):
            log.warning('%s: stale id, recreating', rel)
            fid = svc.files().create(
                body={'name': name, 'parents': [parent_id]},
                media_body=media, fields='id',
            ).execute()['id']
        else:
            raise
    m['files'][rel] = {'id': fid, 'hash': h}
    log.info('%s %s (id=%s)', action, rel, fid)


def sync() -> int:
    started = datetime.now(timezone.utc)
    m = _load_manifest()
    plan = _plan(m)
    changed = [x for x in plan if x[0] != 'skip']
    log.info('sync start — %d file(s), %d changed', len(plan), len(changed))

    # Validate creds first, even on no-change runs — this is how we notice the
    # ~7-day Testing-mode token death promptly and alert. Cheap: the refresh
    # only hits the network when the access token needs its ~hourly renewal;
    # _service() alerts + exits(2) if the refresh token itself is dead.
    svc = _service()

    if not changed and m.get('root_folder_id'):
        log.info('nothing changed — up to date (root=%s)', m['root_folder_id'])
        return 0

    root_id = _ensure_root(svc, m)
    _save_manifest(m)  # persist root/folder ids early

    ok = err = 0
    for action, path, h in plan:
        if action == 'skip':
            continue
        try:
            _upload(svc, m, root_id, action, path, h)
            ok += 1
        except Exception as e:
            err += 1
            log.error('FAILED %s %s: %s', action, _rel(path), e)
        _save_manifest(m)

    dur = (datetime.now(timezone.utc) - started).total_seconds()
    link = f'https://drive.google.com/drive/folders/{root_id}'
    log.info('sync done — %d uploaded, %d skipped, %d errors, %.1fs | %s',
             ok, len(plan) - len(changed), err, dur, link)
    print(f'\nDrive folder: {link}')
    return 1 if err else 0


def main() -> int:
    ap = argparse.ArgumentParser(description='Sync Vault + CLAUDE.md to Google Drive')
    ap.add_argument('--dry-run', action='store_true',
                    help='plan only; no API calls, no credentials needed')
    args = ap.parse_args()
    _setup_logging()
    return dry_run() if args.dry_run else sync()


if __name__ == '__main__':
    sys.exit(main())
