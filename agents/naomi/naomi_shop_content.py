"""
naomi_shop_content.py — Custom task: write Etsy shop-level content for JCF7Studio.

Not a product listing — writes shop announcement, buyer messages,
shop description, order receipt banner spec, and shop policies.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import requests

sys.path.insert(0, str(Path(__file__).parent))
from naomi_brain import _save_cost, _send_telegram

# ── Config ─────────────────────────────────────────────────────────────────────

MODEL      = 'claude-sonnet-4-6'
MAX_TOKENS = 4096
OUTPUT_DIR = Path('/root/.openclaw/agents/forge/builds')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / 'etsy_shop_content.txt'

SYSTEM_PROMPT = """\
You are Naomi, an elite Etsy copywriter for JCF HQ.

Your task is to write complete shop-level content for an Etsy shop called \
"JCF7Studio" — NOT individual product listings.

The shop sells premium digital dashboards, templates, and tools for traders, \
entrepreneurs, and tech professionals. Products include:
- AI operations dashboards
- Sports betting bankroll managers
- DCA portfolio trackers
- Freelancer tools
- Content creator dashboards
- Trading journals

TONE: Professional but warm. Not corporate or salesy. Think: "a skilled \
developer who actually cares about helping you succeed." Clean, direct, \
confident — never pushy.

IMPORTANT: Search Etsy to understand how top digital download shops write \
their shop announcements, buyer messages, and descriptions. Look at what \
converts well and what language successful shops use. Apply those insights \
to JCF7Studio's copy.

OUTPUT FORMAT — plain text, clearly labelled sections, ready to copy-paste \
into Etsy settings. No JSON, no markdown headers with #. Use ALL CAPS \
section labels like: SHOP ANNOUNCEMENT, MESSAGE TO BUYERS, etc."""


TASK_PROMPT = """\
Write the following Etsy shop content for JCF7Studio.

SHOP: JCF7Studio
ETSY NICHE: Premium digital dashboards, templates, and tools
BUYERS: Traders, entrepreneurs, content creators, tech professionals
PRODUCTS: AI operations dashboards, sports betting bankroll managers, \
DCA portfolio trackers, freelancer tools, content creator dashboards, \
trading journals
WHAT MAKES THEM SPECIAL: Premium design with multiple themes (dark/light/minimal), \
fully customizable, built by someone who actually uses these tools daily, \
instant digital download, lifetime access

---

Please search Etsy first to see how top-performing digital download shops \
write their shop content, what language converts, and what buyers in this \
space respond to. Then write:

1. SHOP ANNOUNCEMENT (displays on shop homepage)
   - Brief, welcoming, professional but not corporate
   - Mention premium design, multiple themes, customizable
   - What type of buyer will love this shop
   - 2-3 sentences max

2. MESSAGE TO BUYERS (sent on receipt page and email after purchase)
   - Thank them for their purchase
   - Quick instruction: check their Etsy purchases page or email for the download link
   - Mention they can reach out with any questions
   - Warm and personal tone
   - 3-4 sentences max

3. MESSAGE TO BUYERS FOR DIGITAL ITEMS (shown on the downloads page)
   - Specific instructions for opening digital files
   - Mention: unzip if needed, open in browser for HTML dashboards
   - If they bought a bundle, they'll find multiple theme folders
   - Encourage them to leave a review — it genuinely helps a small shop
   - 3-4 sentences max

4. ORDER RECEIPT BANNER (760x100px image — describe it, we'll design separately)
   - Describe the visual design in detail: colors, layout, text, style
   - JCF7Studio branding
   - Clean, tech-forward aesthetic
   - Should look premium and professional
   - Describe it as you would brief a designer

5. SHOP DESCRIPTION / ABOUT SECTION
   - Who is JCF7Studio (a developer/creator who builds tools they actually use)
   - What we make and why
   - Why our products are different from generic templates
   - Professional but human and approachable
   - 4-5 sentences

6. SHOP POLICIES (brief, clear, friendly)
   - Refund policy: digital items are non-refundable BUT we will help fix any issue
   - Delivery: instant digital download, available immediately after purchase
   - Support: reply within 24-48 hours, happy to help

Format each section clearly. Write everything ready to copy directly into Etsy.
Do not add any extra commentary — just the content itself."""


def run_shop_content_task() -> str:
    """
    Call Claude with web search to write JCF7Studio Etsy shop content.
    Returns the formatted text content.
    """
    client   = anthropic.Anthropic()
    messages = [{'role': 'user', 'content': TASK_PROMPT}]

    print(f'[naomi] Calling {MODEL} with web search for shop content...')

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
        messages=messages,
    )

    web_searches = sum(
        1 for b in response.content
        if getattr(b, 'type', '') in ('tool_use', 'server_tool_use')
        and 'web_search' in getattr(b, 'name', '')
    ) or sum(
        1 for b in response.content
        if 'web_search' in getattr(b, 'type', '')
    )

    total_in  = response.usage.input_tokens
    total_out = response.usage.output_tokens

    print(f'[naomi] Turn 1: {total_in}in + {total_out}out | {web_searches} searches')

    result_text = next(
        (b.text for b in response.content
         if getattr(b, 'type', '') == 'text' and b.text),
        '',
    )

    # If response looks incomplete or too short, request a follow-up
    if result_text and len(result_text) < 300:
        print('[naomi] Response seems short — requesting follow-up...')
        response2 = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
            messages=messages + [
                {'role': 'assistant', 'content': response.content},
                {'role': 'user', 'content':
                 'Please now write all 6 sections of shop content in full. '
                 'Start directly with the content — no preamble.'},
            ],
        )
        total_in  += response2.usage.input_tokens
        total_out += response2.usage.output_tokens
        result_text = next(
            (b.text for b in response2.content
             if getattr(b, 'type', '') == 'text' and b.text),
            result_text,
        )

    cost = _save_cost('naomi_shop', total_in, total_out, web_searches)
    print(f'[naomi] Total: {total_in}in + {total_out}out | {web_searches} searches | ${cost:.4f}')

    # ── Build output file ──────────────────────────────────────────────────────
    timestamp  = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    header = (
        f"JCF7STUDIO — ETSY SHOP CONTENT\n"
        f"Generated by Naomi | {timestamp}\n"
        f"API cost: ${cost:.4f} | Model: {MODEL}\n"
        f"{'='*60}\n\n"
    )
    full_output = header + result_text.strip() + "\n"

    OUTPUT_FILE.write_text(full_output, encoding='utf-8')
    print(f'[naomi] Saved → {OUTPUT_FILE}')

    # ── Extract preview sections for Telegram ─────────────────────────────────
    lines    = result_text.strip().splitlines()
    announcement_lines = []
    buyer_msg_lines    = []
    section = None

    for line in lines:
        stripped = line.strip()
        upper    = stripped.upper()
        if 'SHOP ANNOUNCEMENT' in upper:
            section = 'announcement'
            continue
        elif 'MESSAGE TO BUYERS FOR DIGITAL' in upper:
            section = None   # skip this one in preview
        elif 'MESSAGE TO BUYERS' in upper and 'DIGITAL' not in upper:
            section = 'buyer'
            continue
        elif stripped.startswith('---') or (
            stripped.isupper() and len(stripped) > 6 and section is not None
            and stripped not in ('', '---')
        ):
            if section in ('announcement', 'buyer'):
                section = None

        if section == 'announcement' and stripped:
            announcement_lines.append(stripped)
        elif section == 'buyer' and stripped:
            buyer_msg_lines.append(stripped)

    announcement_preview = ' '.join(announcement_lines[:3])[:300] or '(see file)'
    buyer_preview        = ' '.join(buyer_msg_lines[:4])[:300] or '(see file)'

    # ── Telegram notification ──────────────────────────────────────────────────
    tg_msg = (
        f"NAOMI — ETSY SHOP CONTENT READY\n"
        f"Shop: JCF7Studio\n"
        f"Saved to: forge/builds/etsy_shop_content.txt\n\n"
        f"SHOP ANNOUNCEMENT:\n{announcement_preview}\n\n"
        f"MESSAGE TO BUYERS:\n{buyer_preview}\n\n"
        f"Cost: ${cost:.4f} | {web_searches} searches"
    )
    _send_telegram(tg_msg)
    print('[naomi] Telegram sent')

    return full_output


if __name__ == '__main__':
    output = run_shop_content_task()
    print('\n' + '='*60)
    print(output)
