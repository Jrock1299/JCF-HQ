import subprocess
import json
import re

PRIMARY_MODEL  = 'openai/gpt-5.3-codex'
FALLBACK_MODEL = 'openai/gpt-5.5'


def _run_agent(prompt, model=PRIMARY_MODEL, timeout=90):
    """Run a prompt through the openclaw gateway agent. Returns response text or None."""
    cmd = [
        'openclaw', 'agent',
        '--agent', 'oracle',
        '--model', model,
        '--message', prompt,
        '--json',
        '--timeout', str(timeout),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15)
        if proc.returncode != 0:
            return None
        result = json.loads(proc.stdout)
        payloads = result.get('result', {}).get('payloads', [])
        return payloads[0].get('text', '') if payloads else None
    except Exception:
        return None


def research_game(home_team, away_team, sport, game_date):
    """Use Codex with web search to research a game and predict the winner."""

    prompt = (
        f"You are a sharp sports analyst. Research this upcoming {sport} game "
        f"and give me a prediction.\n\n"
        f"Game: {away_team} at {home_team}\n"
        f"Date: {game_date}\n\n"
        f"Use web_search to find:\n"
        f"1. Recent form for both teams (last 5-10 games)\n"
        f"2. Key injuries or player availability\n"
        f"3. Head-to-head record\n"
        f"4. Home/away performance\n"
        f"5. Current Vegas/sportsbook odds if available\n\n"
        f"Then give me:\n"
        f"- Your predicted winner\n"
        f"- Confidence level (50-95%)\n"
        f"- Key reasons (2-3 bullet points max)\n"
        f"- Any edges or angles worth noting\n\n"
        f'Respond ONLY in this JSON format:\n'
        f'{{\n'
        f'  "predicted_winner": "team name",\n'
        f'  "confidence": 65,\n'
        f'  "reasoning": ["reason 1", "reason 2", "reason 3"],\n'
        f'  "edge_note": "brief edge observation",\n'
        f'  "data_found": true\n'
        f'}}'
    )

    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        text = _run_agent(prompt, model=model)
        if text is None:
            continue
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            print(f"Research parse error ({model}): {e}")

    return None

if __name__ == '__main__':
    # Test
    result = research_game('Sacramento Kings', 'Phoenix Suns', 'NBA', '2026-03-04')
    print(json.dumps(result, indent=2))
