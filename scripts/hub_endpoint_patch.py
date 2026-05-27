import re
import os

SERVER_PATH = "/root/.openclaw/scripts/hq_storage_server.py"

with open(SERVER_PATH, "r") as f:
    content = f.read()

# --- Step 1: Inject imports ---
if "from hq_storage_server import load_data, save_data" not in content:
    content = re.sub(
        r"(import json\nimport os\nfrom flask import Flask, request, jsonify\nfrom flask_cors import CORS)",
        r"\1\nfrom hq_post import add_hub_message, load_hub_data, save_hub_data",
        content, 1
    )
    print("[OK] Injected hub_post imports")
else:
    print("[SKIP] hub_post imports already exist")


# --- Step 2: Inject /hq/hub endpoint ---
hub_endpoint_code = '''
@app.route('/hq/hub', methods=['POST'])
def add_hub_entry():
    data = request.get_json()
    agent = data.get('agent', 'unknown')
    msg_type = data.get('type', 'log')
    message = data.get('message', '')
    tags = data.get('tags', [])
    if message:
        add_hub_message(agent, msg_type, message, tags)
    return jsonify({'ok': True})

@app.route('/hq/hub', methods=['GET'])
def get_hub_entries():
    data = load_hub_data()
    return jsonify(data.get('messages', []))
'''

# Find the last @app.route for existing endpoints and insert before that, or at the end.
# We'll insert it just before the existing @app.route('/hq/bankroll', methods=['POST']) for consistency
if "@app.route('/hq/hub')" not in content:
    content = content.replace(
        "@app.route('/hq/bankroll', methods=['POST'])",
        hub_endpoint_code + "\n\n@app.route('/hq/bankroll', methods=['POST'])"
    )
    print("[OK] Injected /hq/hub endpoints")
else:
    print("[SKIP] /hq/hub endpoints already exist")


with open(SERVER_PATH, "w") as f:
    f.write(content)

print(f"[OK] Patched {SERVER_PATH} ({len(content)} chars)")

# Verify syntax
import py_compile
try:
    py_compile.compile(SERVER_PATH, doraise=True)
    print("[OK] Syntax check PASSED")
except Exception as e:
    print(f"[ERROR] Syntax check FAILED: {e}")
