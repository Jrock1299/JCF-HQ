"""
agent_llm.py — shared LLM call helper for the JCF HQ Discord bot.

Routes a persona + task prompt through the openclaw gateway agent (Codex),
mirroring the `_run_codex` pattern used by Norman/Victoria/Lucy. The gateway
agent has no separate `system` slot, so the persona is prepended into the
message. Payload goes via --message-file to dodge the CLI arg-size limit.

Returns response text, or None on any failure (callers degrade gracefully).
"""
import json
import os
import subprocess
import tempfile

# Same working tier the migrated reasoning agents use (see CLAUDE.md 4d).
# Plain tier id — the `-codex` suffixed ids are rejected as --model overrides.
DEFAULT_MODEL = os.getenv('DISCORD_BOT_MODEL', 'openai/gpt-5.6-terra')


def run_agent(persona: str, task: str, timeout: int = 180,
              model: str = None) -> str | None:
    """Call the gateway agent with a persona + task. Returns text or None."""
    model = model or DEFAULT_MODEL
    combined = f"{persona}\n\n=== TASK ===\n\n{task}"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            'w', suffix='.txt', prefix='discord_llm_',
            dir='/tmp', delete=False, encoding='utf-8',
        ) as fh:
            fh.write(combined)
            tmp_path = fh.name
        cmd = [
            'openclaw', 'agent',
            '--agent', 'main',
            '--model', model,
            '--message-file', tmp_path,
            '--json',
            '--timeout', str(timeout),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout + 60)
        if proc.returncode != 0:
            print(f'[discord-llm] agent call failed: {proc.stderr[:300]}')
            return None
        data = json.loads(proc.stdout)
        payloads = data.get('result', {}).get('payloads', [])
        text = payloads[0].get('text', '') if payloads else ''
        return text.strip() or None
    except subprocess.TimeoutExpired:
        print('[discord-llm] agent call timed out')
        return None
    except Exception as e:
        print(f'[discord-llm] agent call error: {e}')
        return None
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
