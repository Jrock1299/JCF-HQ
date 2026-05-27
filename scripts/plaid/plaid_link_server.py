#!/usr/bin/env python3
import os
import json
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string

# Load /etc/environment
try:
    with open('/etc/environment') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k, v)
except Exception:
    pass

from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.configuration import Configuration
from plaid.api_client import ApiClient

PLAID_CLIENT_ID = os.environ.get('PLAID_CLIENT_ID', '')
PLAID_SECRET = os.environ.get('PLAID_SECRET', '')
PLAID_ENV = os.environ.get('PLAID_ENV', 'production')

TOKENS_PATH = Path('/root/.openclaw/scripts/plaid/plaid_tokens.json')

app = Flask(__name__)

configuration = Configuration(
    host='https://production.plaid.com',
    api_key={
        'clientId': PLAID_CLIENT_ID,
        'secret': PLAID_SECRET,
    }
)
api_client = ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)

INDEX_HTML = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Plaid Link</title>
    <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
  </head>
  <body style="font-family: Arial, sans-serif; padding: 24px;">
    <h2>Plaid Link</h2>
    <button id="link-button">Connect Bank</button>
    <pre id="status"></pre>
    <script>
      async function getLinkToken() {
        const res = await fetch('/create_link_token');
        const data = await res.json();
        return data.link_token;
      }
      (async () => {
        const linkToken = await getLinkToken();
        const handler = Plaid.create({
          token: linkToken,
          onSuccess: async (public_token, metadata) => {
            document.getElementById('status').textContent = 'Exchanging token...';
            const res = await fetch('/exchange_token', {
              method: 'POST',
              headers: {'Content-Type':'application/json'},
              body: JSON.stringify({ public_token, metadata })
            });
            const out = await res.json();
            document.getElementById('status').textContent = JSON.stringify(out, null, 2);
          },
          onExit: (err, metadata) => {
            document.getElementById('status').textContent = err ? JSON.stringify(err, null, 2) : 'Exited';
          }
        });
        document.getElementById('link-button').onclick = () => handler.open();
      })();
    </script>
  </body>
</html>
"""

@app.get('/')
def index():
    return render_template_string(INDEX_HTML)

@app.get('/create_link_token')
def create_link_token():
    req = LinkTokenCreateRequest(
        products=[Products('transactions'), Products('auth')],
        client_name='OpenClaw Plaid Link',
        country_codes=[CountryCode('US')],
        language='en',
        user=LinkTokenCreateRequestUser(client_user_id='openclaw-user')
    )
    resp = client.link_token_create(req)
    return jsonify(resp.to_dict())

@app.post('/exchange_token')
def exchange_token():
    data = request.get_json(force=True) or {}
    public_token = data.get('public_token')
    if not public_token:
        return jsonify({'ok': False, 'error': 'missing public_token'}), 400
    exchange = client.item_public_token_exchange(ItemPublicTokenExchangeRequest(public_token=public_token))
    access_token = exchange['access_token']
    tokens = []
    if TOKENS_PATH.exists():
        try:
            tokens = json.loads(TOKENS_PATH.read_text())
        except Exception:
            tokens = []
    tokens.append({
        'access_token': access_token,
        'item_id': exchange.get('item_id'),
    })
    TOKENS_PATH.write_text(json.dumps(tokens, indent=2))
    return jsonify({'ok': True, 'item_id': exchange.get('item_id')})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8901, debug=False)
