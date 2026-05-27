"""
forge_reviewer.py — Self-review and iteration engine for Forge.

Sends generated HTML back to Claude for quality evaluation.
Iterates up to 3 times if score < 7. Marks as APPROVED or NEEDS_REVIEW.
"""

import sys
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent))
from forge_config import (
    REVIEW_MODEL, MAX_TOKENS_REVIEW,
    get_logger, save_api_cost, extract_json, send_telegram,
)

log = get_logger('reviewer')

MAX_ITERATIONS  = 3
APPROVAL_SCORE  = 7
MAX_HTML_REVIEW = 80_000   # chars — keeps input tokens sane

SYSTEM_PROMPT_REVIEW = """\
You are a senior quality engineer reviewing AI-generated digital products.
Your job is to evaluate HTML dashboards against their specifications and
identify specific, actionable issues.

Be direct and specific — do not be vague. If a feature is missing, name it.
If a style is wrong, say exactly what colour or font is wrong and what it should be.
If code is broken, identify the exact function or line.

OUTPUT FORMAT (valid JSON only, no markdown):
{
  "score": 8,
  "passes_spec": true,
  "theme_correct": true,
  "is_responsive": true,
  "missing_features": ["feature name that is absent"],
  "visual_bugs": ["specific visual issue"],
  "code_errors": ["specific JS/CSS error"],
  "issues": ["combined list of all issues worth fixing"],
  "fix_instructions": "Specific step-by-step instructions to fix all issues above. Be precise.",
  "verdict": "APPROVED"
}

verdict must be one of: APPROVED, NEEDS_FIXES, NEEDS_REVIEW
APPROVED   = score >= 7, ready to ship
NEEDS_FIXES = score < 7, fixable by Claude
NEEDS_REVIEW = score < 5, requires human judgment"""


def _build_review_prompt(html_content: str, product_spec: dict, theme_name: str) -> str:
    # Truncate if too large
    if len(html_content) > MAX_HTML_REVIEW:
        log.warning(
            'HTML %d chars — truncating to %d for review',
            len(html_content), MAX_HTML_REVIEW,
        )
        html_content = html_content[:MAX_HTML_REVIEW] + '\n\n[... TRUNCATED FOR REVIEW ...]'

    features = '\n'.join(f'  - {f}' for f in product_spec.get('features', []))
    size_kb = round(len(html_content.encode()) / 1024, 1)

    return f"""Review this generated HTML product for quality and specification compliance.

PRODUCT: {product_spec.get('display_name', product_spec.get('name', '?'))}
DESCRIPTION: {product_spec.get('description', '')}
THEME: {theme_name}

REQUIRED FEATURES:
{features}

HTML FILE ({size_kb} KB):
```html
{html_content}
```

Evaluate every required feature — mark missing ones explicitly.
Check theme colors match the spec.
Check responsiveness (media queries present, flexible layout).
Check for JS errors (undefined variables, broken event listeners).
Rate 1-10 and output ONLY the JSON verdict."""


def _build_fix_prompt(html_content: str, review: dict, product_spec: dict, theme_name: str) -> str:
    issues       = '\n'.join(f'  - {i}' for i in review.get('issues', []))
    fix_instruct = review.get('fix_instructions', 'Fix all issues above.')
    features     = '\n'.join(f'  - {f}' for f in product_spec.get('features', []))

    if len(html_content) > MAX_HTML_REVIEW:
        html_content = html_content[:MAX_HTML_REVIEW] + '\n\n[... TRUNCATED ...]'

    return f"""Apply the following fixes to this HTML product and return the corrected complete file.

PRODUCT: {product_spec.get('display_name', '')}
THEME: {theme_name}

REQUIRED FEATURES (ensure all are present):
{features}

ISSUES TO FIX (score was {review.get('score', '?')}/10):
{issues}

FIX INSTRUCTIONS:
{fix_instruct}

CURRENT HTML:
```html
{html_content}
```

Return ONLY the complete corrected HTML file in a ```html code block. No prose, no explanation."""


def _call_claude(prompt: str, system: str, max_tokens: int) -> tuple[str, int, int]:
    """Returns (response_text, input_tokens, output_tokens)."""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=REVIEW_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{'role': 'user', 'content': prompt}],
    )
    text = next(
        (b.text for b in response.content if getattr(b, 'type', '') == 'text'),
        '',
    )
    return text, response.usage.input_tokens, response.usage.output_tokens


def review_product(
    file_path: str | Path,
    product_spec: dict,
    theme_name: str,
) -> dict:
    """
    Review a generated HTML product. Iterate up to MAX_ITERATIONS if score < APPROVAL_SCORE.

    Returns:
        {
            'score': 8.5,
            'status': 'APPROVED',
            'iterations': 1,
            'issues': [...],
            'total_review_cost': 0.09,
            'file_path': '...',
        }
    """
    file_path = Path(file_path)
    if not file_path.exists():
        log.error('review_product: file not found: %s', file_path)
        return {'status': 'ERROR', 'score': 0, 'issues': ['File not found']}

    html_content  = file_path.read_text(encoding='utf-8')
    total_in      = 0
    total_out     = 0
    final_review  = None
    iterations    = 0

    for attempt in range(1, MAX_ITERATIONS + 1):
        iterations = attempt
        log.info(
            'Review iteration %d/%d for %s/%s',
            attempt, MAX_ITERATIONS, product_spec.get('name'), theme_name,
        )

        # ── Review pass ────────────────────────────────────────────────────────
        review_prompt = _build_review_prompt(html_content, product_spec, theme_name)
        review_text, in_tok, out_tok = _call_claude(
            review_prompt, SYSTEM_PROMPT_REVIEW, MAX_TOKENS_REVIEW,
        )
        total_in  += in_tok
        total_out += out_tok

        review = extract_json(review_text)
        if review is None:
            log.warning('Review iteration %d returned no JSON', attempt)
            review = {'score': 5, 'verdict': 'NEEDS_FIXES',
                      'issues': ['Review returned no JSON']}

        score   = review.get('score', 0)
        verdict = review.get('verdict', 'NEEDS_FIXES')
        log.info(
            'Review %d/%d: score=%s/10 verdict=%s issues=%d',
            attempt, MAX_ITERATIONS, score, verdict,
            len(review.get('issues', [])),
        )

        final_review = review

        # ── Accept if good enough ──────────────────────────────────────────────
        if score >= APPROVAL_SCORE:
            final_review['verdict'] = 'APPROVED'
            log.info('Quality approved at %.1f/10', score)
            break

        # ── Last attempt — give up ─────────────────────────────────────────────
        if attempt == MAX_ITERATIONS:
            log.warning(
                'Still %.1f/10 after %d iterations — marking NEEDS_REVIEW',
                score, MAX_ITERATIONS,
            )
            final_review['verdict'] = 'NEEDS_REVIEW'
            break

        # ── Apply fixes ────────────────────────────────────────────────────────
        log.info('Applying fixes (score %.1f < %d)...', score, APPROVAL_SCORE)

        from forge_brain import _extract_html, BUILD_SYSTEM_PROMPT  # noqa: F401
        fix_prompt = _build_fix_prompt(html_content, review, product_spec, theme_name)
        fix_text, in2, out2 = _call_claude(
            fix_prompt, BUILD_SYSTEM_PROMPT, 16384,
        )
        total_in  += in2
        total_out += out2

        fixed_html = _extract_html(fix_text)
        if fixed_html:
            html_content = fixed_html
            file_path.write_text(html_content, encoding='utf-8')
            log.info(
                'Fix applied — new size %.1f KB',
                len(html_content.encode()) / 1024,
            )
        else:
            log.warning('Fix attempt %d returned no valid HTML', attempt)

    # ── Save cost ──────────────────────────────────────────────────────────────
    cost = save_api_cost(
        f'review/{product_spec.get("name","?")}/{theme_name}',
        total_in, total_out,
    )
    log.info(
        'Review complete: %d/%d score=%s status=%s cost=$%.4f',
        iterations, MAX_ITERATIONS,
        final_review.get('score', '?'),
        final_review.get('verdict', '?'),
        cost,
    )

    return {
        'score':              final_review.get('score', 0),
        'status':             final_review.get('verdict', 'NEEDS_REVIEW'),
        'iterations':         iterations,
        'issues':             final_review.get('issues', []),
        'missing_features':   final_review.get('missing_features', []),
        'visual_bugs':        final_review.get('visual_bugs', []),
        'code_errors':        final_review.get('code_errors', []),
        'total_review_cost':  cost,
        'file_path':          str(file_path),
    }
