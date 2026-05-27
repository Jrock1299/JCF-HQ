"""
forge_brain.py — Main build engine for Forge.

Builds premium HTML dashboards and Excel spreadsheets using Claude API.
No web search needed — Claude generates the product code directly.

Usage:
    python3 forge_brain.py --build ai_ops_dashboard
    python3 forge_brain.py --build-all
    python3 forge_brain.py --list

    from forge_brain import build_single_theme
    result = build_single_theme('ai_ops_dashboard', 'dark_techy')
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent))
from forge_config import (
    BUILD_MODEL, MAX_TOKENS_BUILD,
    THEME_SPECS, CUSTOM_PALETTES,
    BUILDS_DIR, SPECS_PATH, BUILD_LOG_PATH,
    get_logger, send_telegram, save_api_cost,
    load_json, save_json,
)

log = get_logger('brain')

# ── System prompt ──────────────────────────────────────────────────────────────

BUILD_SYSTEM_PROMPT = """\
You are Forge, a master digital product builder. You create premium, \
production-grade digital products — HTML dashboards, web apps, and \
spreadsheet templates — that look like they were built by a professional \
design studio.

QUALITY STANDARDS:
- Responsive design — works perfectly on desktop (1440px), tablet (768px), \
  and mobile (375px)
- Smooth CSS animations and transitions (no janky layout shifts)
- Proper typography hierarchy — headings, subheadings, labels, values all distinct
- Consistent 8px grid spacing system
- Interactive elements — all buttons, cards, and inputs have hover states and \
  click feedback
- No generic AI aesthetic — each product should feel unique and purposeful
- Include a "Your Brand Here" logo placeholder (top-left, 40×40px with rounded \
  corners) and an editable title field in the header
- Data persists via localStorage — user's numbers survive a page refresh
- Loading state on initial render (brief skeleton or fade-in)

THEME APPLICATION:
Apply theme colors and fonts exactly as specified. Use CSS custom properties \
at :root for every color and font so the theme is easily reskinnable. \
Do NOT override theme colors with your own defaults.

CODE QUALITY:
- Single HTML file with all CSS and JS embedded inline
- Google Fonts CDN only for fonts — no other external dependencies
- Vanilla HTML/CSS/JS only — no React, Vue, jQuery, or any JS framework
- No external CSS frameworks — no Tailwind, Bootstrap, etc.
- Clean code with section comments (/* ── Section ─── */)
- LocalStorage key prefixed with product name to avoid collisions
- All charts built with pure Canvas API or SVG — no Chart.js or similar

OUTPUT: Return the complete HTML file as a single ```html code block. \
Nothing before the opening ``` and nothing after the closing ```."""


# ── HTML extraction ────────────────────────────────────────────────────────────

def _extract_html(text: str) -> str | None:
    """Extract HTML from Claude's response, handling multiple wrapping styles."""
    if not text:
        return None

    # Strategy 1: ```html\n...\n```
    idx = text.lower().find('```html')
    if idx >= 0:
        start = text.find('\n', idx)
        if start >= 0:
            start += 1
            end = text.find('\n```', start)
            if end >= 0:
                return text[start:end].strip()
            # No closing fence — take everything after opening
            return text[start:].strip()

    # Strategy 2: generic ``` block containing HTML
    idx = text.find('```')
    if idx >= 0:
        start = text.find('\n', idx)
        if start >= 0:
            start += 1
            snippet = text[start:start + 50].lstrip()
            if snippet.lower().startswith('<!doctype') or snippet.lower().startswith('<html'):
                end = text.find('\n```', start)
                if end >= 0:
                    return text[start:end].strip()
                return text[start:].strip()

    # Strategy 3: bare <!DOCTYPE html> in response
    lower = text.lower()
    doctype_idx = lower.find('<!doctype html')
    if doctype_idx >= 0:
        chunk = text[doctype_idx:]
        # Try to find closing </html>
        end_idx = lower.rfind('</html>')
        if end_idx >= doctype_idx:
            return text[doctype_idx:end_idx + 7].strip()
        return chunk.strip()

    # Strategy 4: bare <html>
    html_idx = lower.find('<html')
    if html_idx >= 0:
        end_idx = lower.rfind('</html>')
        if end_idx >= html_idx:
            return text[html_idx:end_idx + 7].strip()
        return text[html_idx:].strip()

    return None


def _extract_python(text: str) -> str | None:
    """Extract Python code from Claude's response."""
    # ```python block
    m = re.search(r'```python\s*([\s\S]+?)\s*```', text)
    if m:
        return m.group(1)
    # Generic ``` block that looks like Python
    m = re.search(r'```\w*\s*(import\s[\s\S]+?)\s*```', text)
    if m:
        return m.group(1)
    # Bare import statement
    m = re.search(r'(import\s+\w+[\s\S]+)', text)
    if m:
        return m.group(1)
    return None


# ── Prompt builders ────────────────────────────────────────────────────────────

def _build_html_prompt(product_spec: dict, theme_name: str) -> str:
    theme    = THEME_SPECS[theme_name]
    features = '\n'.join(f'  {i+1}. {f}' for i, f in enumerate(product_spec.get('features', [])))

    return f"""Build this digital product now.

PRODUCT:
  Name:        {product_spec.get('display_name', product_spec.get('name', ''))}
  Description: {product_spec.get('description', '')}

FEATURES TO IMPLEMENT (all required):
{features}

THEME: {theme['name']}
  --color-bg:           {theme['bg']}
  --color-card-bg:      {theme['card_bg']}
  --color-accent:       {theme['accent']}
  --color-accent-alt:   {theme['accent_alt']}
  --color-text:         {theme['text']}
  --color-text-muted:   {theme['text_muted']}
  --color-border:       {theme['border']}
  --font-heading:       {theme['font_heading']}
  --font-body:          {theme['font_body']}
  Style notes:          {theme['style_notes']}

DELIVERABLE:
Single-file HTML dashboard. All features fully functional with localStorage \
persistence. Production-ready. Return ONLY the ```html code block."""


def _build_custom_builder_prompt(product_spec: dict) -> str:
    base_theme = THEME_SPECS['dark_techy']
    features   = '\n'.join(f'  {i+1}. {f}' for i, f in enumerate(product_spec.get('features', [])))

    palette_lines = '\n'.join(
        f"  '{k}': bg={v['bg']}, accent={v['accent']}"
        for k, v in CUSTOM_PALETTES.items()
    )

    return f"""Build this digital product with a built-in theme customizer.

PRODUCT:
  Name:        {product_spec.get('display_name', product_spec.get('name', ''))} — Custom Builder Edition
  Description: {product_spec.get('description', '')}

FEATURES TO IMPLEMENT (all required):
{features}

BASE THEME (Dark/Techy):
  --color-bg:           {base_theme['bg']}
  --color-card-bg:      {base_theme['card_bg']}
  --color-accent:       {base_theme['accent']}
  --color-accent-alt:   {base_theme['accent_alt']}
  --color-text:         {base_theme['text']}
  --color-text-muted:   {base_theme['text_muted']}
  --color-border:       {base_theme['border']}
  --font-heading:       {base_theme['font_heading']}
  --font-body:          {base_theme['font_body']}

THEME CUSTOMIZER (required — this is the key differentiator):
Add a floating "Themes" button fixed to the bottom-right corner.
Clicking it opens a slide-up panel with:
  1. A grid of 12 palette swatches (2 circles each: bg + accent color):
{palette_lines}
  2. A "Custom" row with two <input type="color"> pickers for bg and accent
  3. An "Apply" button and a "Reset to Default" button
Clicking a palette swatch INSTANTLY applies those colors by updating CSS \
custom properties on :root via JavaScript — no page reload.
The selected palette name persists in localStorage.

DELIVERABLE:
Single-file HTML. All features functional. Theme customizer fully working. \
Return ONLY the ```html code block."""


def _build_excel_prompt(product_spec: dict) -> str:
    features = '\n'.join(f'  {i+1}. {f}' for i, f in enumerate(product_spec.get('features', [])))

    return f"""Generate Python code using openpyxl to create a professional Excel spreadsheet.

PRODUCT:
  Name:        {product_spec.get('display_name', product_spec.get('name', ''))}
  Description: {product_spec.get('description', '')}

FEATURES TO IMPLEMENT:
{features}

REQUIREMENTS:
- Use openpyxl library
- Professional formatting: colors, bold headers, column widths
- Header row: dark fill (#1e293b), white bold text
- Alternating row colors (light/white)
- Pre-populated sample data rows (5-10 rows) so the buyer sees it in action
- Formulas where appropriate (SUM, AVERAGE, IF, etc.)
- Multiple sheets if the product warrants it
- Freeze the header row
- The output file must be saved as: output_path (variable already defined)

IMPORTANT: The variable `output_path` is already defined as the output file path.
Your code must use it: `wb.save(output_path)`

Generate ONLY the Python code in a ```python code block. No prose."""


# ── Claude API call ────────────────────────────────────────────────────────────

def _call_claude_build(prompt: str, label: str) -> tuple[str, float]:
    """
    Call Claude with the build prompt. Returns (raw_response_text, cost_usd).
    Handles max_tokens truncation with a continuation turn.
    """
    client      = anthropic.Anthropic()
    total_in    = 0
    total_out   = 0
    messages    = [{'role': 'user', 'content': prompt}]

    log.info('[%s] Calling %s (max_tokens=%d)...', label, BUILD_MODEL, MAX_TOKENS_BUILD)

    response = client.messages.create(
        model=BUILD_MODEL,
        max_tokens=MAX_TOKENS_BUILD,
        system=BUILD_SYSTEM_PROMPT,
        messages=messages,
    )

    total_in  += response.usage.input_tokens
    total_out += response.usage.output_tokens

    text = next(
        (b.text for b in response.content if getattr(b, 'type', '') == 'text'),
        '',
    )

    log.info(
        '[%s] Turn 1: %din + %dout | stop=%s',
        label, response.usage.input_tokens, response.usage.output_tokens,
        response.stop_reason,
    )

    # ── Continuation if output was truncated ──────────────────────────────────
    if response.stop_reason == 'max_tokens':
        log.info('[%s] Output truncated — requesting continuation...', label)
        messages = messages + [
            {'role': 'assistant', 'content': text},
            {'role': 'user',      'content':
             'The file was truncated. Continue EXACTLY from where you left off. '
             'Do not restart or repeat — just continue the code from the cut-off point. '
             'End with the closing </html> tag when complete.'},
        ]
        response2 = client.messages.create(
            model=BUILD_MODEL,
            max_tokens=MAX_TOKENS_BUILD,
            system=BUILD_SYSTEM_PROMPT,
            messages=messages,
        )
        total_in  += response2.usage.input_tokens
        total_out += response2.usage.output_tokens
        cont = next(
            (b.text for b in response2.content if getattr(b, 'type', '') == 'text'),
            '',
        )
        # Strip any opening fence from continuation (Claude sometimes re-opens)
        cont_stripped = re.sub(r'^```html?\s*', '', cont.lstrip())
        text = text + cont_stripped
        log.info(
            '[%s] Turn 2 (cont): %din + %dout | stop=%s',
            label, response2.usage.input_tokens, response2.usage.output_tokens,
            response2.stop_reason,
        )

    cost = save_api_cost(f'build/{label}', total_in, total_out)
    log.info('[%s] Total: %din + %dout | $%.4f', label, total_in, total_out, cost)

    return text, cost


# ── Build helpers ──────────────────────────────────────────────────────────────

def _save_build_log(entry: dict) -> None:
    history = load_json(BUILD_LOG_PATH, [])
    if not isinstance(history, list):
        history = []
    history.append(entry)
    save_json(BUILD_LOG_PATH, history)


def _build_html_theme(
    product_spec: dict,
    theme_name: str,
    output_dir: Path,
) -> dict:
    """Build one HTML theme variant. Returns result dict."""
    label    = f"{product_spec['name']}/{theme_name}"
    prompt   = _build_html_prompt(product_spec, theme_name)
    raw, cost = _call_claude_build(prompt, label)

    html = _extract_html(raw)
    if not html:
        log.error('[%s] No HTML extracted from response', label)
        log.debug('Response snippet: %s', raw[:300])
        return {
            'status':    'BUILD_FAILED',
            'theme':     theme_name,
            'error':     'No HTML in response',
            'cost':      cost,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / 'index.html'
    out_file.write_text(html, encoding='utf-8')
    size_kb = round(len(html.encode()) / 1024, 1)
    log.info('[%s] Saved %.1f KB → %s', label, size_kb, out_file)

    return {
        'theme':     theme_name,
        'file_path': str(out_file),
        'size_kb':   size_kb,
        'build_cost': cost,
    }


def _build_custom_builder(product_spec: dict, output_dir: Path) -> dict:
    """Build the custom color builder variant."""
    label    = f"{product_spec['name']}/custom_builder"
    prompt   = _build_custom_builder_prompt(product_spec)
    raw, cost = _call_claude_build(prompt, label)

    html = _extract_html(raw)
    if not html:
        log.error('[%s] No HTML extracted', label)
        return {'status': 'BUILD_FAILED', 'theme': 'custom_builder', 'cost': cost}

    out_dir = output_dir / 'custom_builder'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / 'index.html'
    out_file.write_text(html, encoding='utf-8')
    size_kb = round(len(html.encode()) / 1024, 1)
    log.info('[%s] Saved %.1f KB → %s', label, size_kb, out_file)

    return {
        'theme':      'custom_builder',
        'file_path':  str(out_file),
        'size_kb':    size_kb,
        'build_cost': cost,
    }


def _build_excel_file(product_spec: dict, output_dir: Path) -> dict:
    """Build Excel file by generating and executing openpyxl code."""
    label    = f"{product_spec['name']}/excel"
    prompt   = _build_excel_prompt(product_spec)
    raw, cost = _call_claude_build(prompt, label)

    py_code = _extract_python(raw)
    if not py_code:
        log.error('[%s] No Python code extracted', label)
        return {'status': 'BUILD_FAILED', 'type': 'excel', 'cost': cost}

    out_dir = output_dir / 'excel'
    out_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = out_dir / f"{product_spec['name']}.xlsx"

    # Write code to temp file and execute
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', delete=False, encoding='utf-8',
    ) as tmp:
        tmp.write(f"output_path = {repr(str(xlsx_path))}\n\n")
        tmp.write(py_code)
        tmp_path = tmp.name

    log.info('[%s] Executing openpyxl code...', label)
    result = subprocess.run(
        [sys.executable, tmp_path],
        capture_output=True, text=True, timeout=60,
    )
    Path(tmp_path).unlink(missing_ok=True)

    if result.returncode != 0:
        log.error('[%s] Excel build failed:\n%s', label, result.stderr[:500])
        return {
            'status': 'BUILD_FAILED', 'type': 'excel',
            'error': result.stderr[:200], 'cost': cost,
        }

    if not xlsx_path.exists():
        log.error('[%s] Excel file not created at %s', label, xlsx_path)
        return {'status': 'BUILD_FAILED', 'type': 'excel', 'cost': cost}

    size_kb = round(xlsx_path.stat().st_size / 1024, 1)
    log.info('[%s] Excel saved %.1f KB → %s', label, size_kb, xlsx_path)

    return {
        'type':       'excel',
        'file_path':  str(xlsx_path),
        'size_kb':    size_kb,
        'build_cost': cost,
        'status':     'BUILT',
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def build_single_theme(product_name: str, theme_name: str) -> dict:
    """
    Build one theme variant of a product and review it.

    Args:
        product_name: key in product_specs.json (e.g. 'ai_ops_dashboard')
        theme_name:   key in THEME_SPECS (e.g. 'dark_techy')

    Returns:
        Result dict with file_path, size_kb, build_cost, review_score, status.
    """
    # Load spec
    specs = load_json(SPECS_PATH, [])
    if not isinstance(specs, list):
        specs = []
    product_spec = next((s for s in specs if s.get('name') == product_name), None)
    if product_spec is None:
        raise ValueError(f"Product '{product_name}' not found in {SPECS_PATH}")

    if theme_name not in THEME_SPECS:
        raise ValueError(f"Theme '{theme_name}' not in THEME_SPECS. "
                         f"Valid: {list(THEME_SPECS)}")

    log.info('Building %s / %s', product_name, theme_name)

    # ── Build ──────────────────────────────────────────────────────────────────
    output_dir = BUILDS_DIR / product_name / theme_name
    build_result = _build_html_theme(product_spec, theme_name, output_dir)

    if build_result.get('status') == 'BUILD_FAILED':
        log.error('Build failed for %s/%s', product_name, theme_name)
        return build_result

    # ── Review ─────────────────────────────────────────────────────────────────
    from forge_reviewer import review_product  # noqa: F401
    review = review_product(build_result['file_path'], product_spec, theme_name)

    # ── Merge result ───────────────────────────────────────────────────────────
    result = {
        'build_id':     str(uuid.uuid4())[:8],
        'timestamp':    datetime.now(timezone.utc).isoformat(),
        'product_name': product_name,
        'theme':        theme_name,
        'file_path':    build_result['file_path'],
        'size_kb':      build_result['size_kb'],
        'build_cost':   build_result['build_cost'],
        'review_score': review['score'],
        'review_status': review['status'],
        'iterations':   review['iterations'],
        'issues':       review.get('issues', []),
        'total_cost':   round(build_result['build_cost'] + review['total_review_cost'], 4),
    }

    _save_build_log(result)

    log.info(
        'Build complete: %s/%s | %.1f KB | score=%.1f/10 | status=%s | cost=$%.4f',
        product_name, theme_name,
        result['size_kb'], result['review_score'],
        result['review_status'], result['total_cost'],
    )

    return result


def build_product(product_spec: dict) -> list[dict]:
    """
    Build all theme variants + custom builder for a product.

    Args:
        product_spec: Full product spec dict (or product name string to load from file).

    Returns:
        List of result dicts, one per theme + custom builder (+ excel if type=both/xlsx).
    """
    if isinstance(product_spec, str):
        specs = load_json(SPECS_PATH, [])
        if not isinstance(specs, list):
            specs = []
        product_spec = next((s for s in specs if s.get('name') == product_spec), None)
        if product_spec is None:
            raise ValueError(f"Product spec not found")

    name         = product_spec.get('name', 'unknown')
    display_name = product_spec.get('display_name', name)
    themes       = product_spec.get('themes', list(THEME_SPECS.keys()))
    prod_type    = product_spec.get('type', 'html')
    include_cb   = product_spec.get('include_custom_builder', False)

    log.info('=== FORGE BUILD: %s ===', display_name)
    send_telegram(
        f"FORGE — BUILD STARTED\n"
        f"Product: {display_name}\n"
        f"Themes: {', '.join(themes)}"
        + (' + Custom Builder' if include_cb else '') +
        f"\nType: {prod_type.upper()}"
    )

    results      = []
    output_base  = BUILDS_DIR / name

    # ── HTML themes ────────────────────────────────────────────────────────────
    if prod_type in ('html', 'both'):
        for theme_name in themes:
            if theme_name not in THEME_SPECS:
                log.warning('Unknown theme %s — skipping', theme_name)
                continue
            out_dir = output_base / theme_name
            build_r = _build_html_theme(product_spec, theme_name, out_dir)
            if build_r.get('status') != 'BUILD_FAILED':
                from forge_reviewer import review_product
                review  = review_product(build_r['file_path'], product_spec, theme_name)
                build_r.update({
                    'review_score':  review['score'],
                    'review_status': review['status'],
                    'iterations':    review['iterations'],
                    'total_cost':    round(
                        build_r['build_cost'] + review['total_review_cost'], 4,
                    ),
                })
            results.append(build_r)

        # Custom builder
        if include_cb:
            cb_r = _build_custom_builder(product_spec, output_base)
            if cb_r.get('status') != 'BUILD_FAILED':
                from forge_reviewer import review_product
                # Use dark_techy spec for custom builder review
                dark_spec = dict(product_spec)
                review = review_product(cb_r['file_path'], dark_spec, 'custom_builder')
                cb_r.update({
                    'review_score':  review['score'],
                    'review_status': review['status'],
                    'iterations':    review['iterations'],
                    'total_cost':    round(
                        cb_r['build_cost'] + review['total_review_cost'], 4,
                    ),
                })
            results.append(cb_r)

    # ── Excel ──────────────────────────────────────────────────────────────────
    if prod_type in ('xlsx', 'both'):
        xl_r = _build_excel_file(product_spec, output_base)
        results.append(xl_r)

    # ── Summary notification ───────────────────────────────────────────────────
    approved = [r for r in results if r.get('review_status') == 'APPROVED']
    needs_rv = [r for r in results if r.get('review_status') == 'NEEDS_REVIEW']
    scores   = [r['review_score'] for r in results if r.get('review_score')]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    total_cost = round(sum(r.get('total_cost', r.get('build_cost', 0)) for r in results), 2)

    if needs_rv:
        for r in needs_rv:
            send_telegram(
                f"FORGE — NEEDS REVIEW\n"
                f"Product: {display_name} — {r.get('theme', '?')} theme\n"
                f"Quality: {r.get('review_score', '?')}/10 after {r.get('iterations', '?')} iterations\n"
                f"Issues: {', '.join(r.get('issues', [])[:3])}\n"
                f"Manual review needed"
            )

    send_telegram(
        f"FORGE — BUILD COMPLETE\n"
        f"Product: {display_name}\n"
        f"Files: {len(results)} variants\n"
        f"Approved: {len(approved)}/{len(results)}\n"
        f"Quality: {avg_score}/10 avg\n"
        f"Cost: ${total_cost}\n"
        f"Location: builds/{name}/"
    )

    log.info(
        '=== BUILD COMPLETE: %s | %d files | avg_score=%.1f | cost=$%.2f ===',
        display_name, len(results), avg_score, total_cost,
    )
    return results


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description='Forge — Digital Product Builder')
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--build',     metavar='PRODUCT', help='Build a specific product')
    group.add_argument('--build-all', action='store_true', help='Build all products')
    group.add_argument('--list',      action='store_true', help='List available product specs')
    args = parser.parse_args()

    specs = load_json(SPECS_PATH, [])
    if not isinstance(specs, list):
        specs = []

    if args.list:
        if not specs:
            print('No product specs found.')
            return
        print(f'\nAvailable products ({len(specs)}):')
        for s in specs:
            print(f"  {s['name']:30s}  {s.get('display_name','')}  "
                  f"[{s.get('type','html')}]  themes={s.get('themes', [])}")
        return

    if args.build:
        product_spec = next((s for s in specs if s.get('name') == args.build), None)
        if product_spec is None:
            print(f"Error: product '{args.build}' not found.")
            print(f"Available: {[s['name'] for s in specs]}")
            sys.exit(1)
        results = build_product(product_spec)
        print(f'\nBuild complete: {len(results)} variants')
        for r in results:
            score  = r.get('review_score', 'N/A')
            status = r.get('review_status', r.get('status', '?'))
            print(f"  {r.get('theme','?'):20s}  {r.get('size_kb','?'):6} KB  "
                  f"score={score}/10  {status}")
        return

    if args.build_all:
        if not specs:
            print('No products to build.')
            return
        for spec in specs:
            print(f'\n--- Building: {spec["display_name"]} ---')
            results = build_product(spec)
            print(f'  Done: {len(results)} variants')


if __name__ == '__main__':
    main()
