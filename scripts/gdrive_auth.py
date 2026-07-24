#!/usr/bin/env python3
"""
gdrive_auth.py — one-time OAuth consent to mint a Drive refresh token for the
JCF HQ Vault sync (see gdrive_sync.py).

Prereq: place your OAuth *Desktop app* client JSON at
    /root/.openclaw/credentials/gdrive/client_secret.json

Run (once) with the openclaw venv python:
    /root/.openclaw/venv/bin/python3 /root/.openclaw/scripts/gdrive_auth.py

It prints an authorization URL. Open it in any browser logged in as the Google
account that owns the target Drive, approve access, then paste back the `code`
value from the (intentionally failing) http://localhost redirect. This writes
token.json — which holds the long-lived refresh token — next to the client JSON.

Uses the least-privilege `drive.file` scope: this app can only see/manage the
files IT creates, never the rest of your Drive.
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from google_auth_oauthlib.flow import InstalledAppFlow

CRED_DIR   = Path('/root/.openclaw/credentials/gdrive')
CLIENT_SEC = CRED_DIR / 'client_secret.json'
TOKEN      = CRED_DIR / 'token.json'
SCOPES     = ['https://www.googleapis.com/auth/drive.file']


def main() -> None:
    if not CLIENT_SEC.exists():
        sys.exit(
            f'ERROR: {CLIENT_SEC} not found.\n'
            f'Download your OAuth "Desktop app" client JSON from Google Cloud '
            f'Console (APIs & Services -> Credentials) and save it there first.'
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SEC), SCOPES)
    # Headless VPS: use a loopback redirect + manual code paste (no browser here).
    flow.redirect_uri = 'http://localhost'
    auth_url, _ = flow.authorization_url(
        access_type='offline',        # request a refresh token
        prompt='consent',             # force refresh_token issuance every time
        include_granted_scopes='true',
    )

    print('\n' + '=' * 70)
    print('STEP 1  Open this URL in a browser (logged in as the Drive owner):\n')
    print('   ' + auth_url + '\n')
    print('STEP 2  Approve access. Your browser will then try to load a')
    print('        http://localhost/?code=... page that FAILS to open —')
    print('        that is expected and fine.')
    print('STEP 3  Copy the `code=` value from that page\'s address bar')
    print('        (or just paste the entire redirected URL below).')
    print('=' * 70 + '\n')

    raw = input('Paste code (or full redirect URL): ').strip()
    code = raw
    if 'code=' in raw:
        code = parse_qs(urlparse(raw).query).get('code', [raw])[0]

    flow.fetch_token(code=code)
    creds = flow.credentials

    if not creds.refresh_token:
        print(
            '\nWARNING: Google did not return a refresh_token. Revoke this app at\n'
            'https://myaccount.google.com/permissions and re-run so a fresh\n'
            'refresh token is issued (needed for unattended cron syncing).',
            file=sys.stderr,
        )

    CRED_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(creds.to_json())
    os.chmod(TOKEN, 0o600)
    print(f'\n[OK] Saved {TOKEN} (refresh token stored, mode 600).')
    print('You can now run: /root/.openclaw/venv/bin/python3 '
          '/root/.openclaw/scripts/gdrive_sync.py')


if __name__ == '__main__':
    main()
