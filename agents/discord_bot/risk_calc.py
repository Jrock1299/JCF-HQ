"""
risk_calc.py — Norman's risk calculator for the #risk-calculator channel.

Parses natural phrasing like:
    "I'm risking $500 on NVDA, trying to gain $1500"
    "risk 1% ($250) on SPX, stop 12 pts, target 2R, account $25k"
    "yolo $2k on SOL to make $20k quick"

...computes the REAL risk math (R-multiple, risk-of-account %, checks against
Norman's rails), and replies IN NORMAN'S VOICE — cold, honest, no coddling.

Design point from Jase: the response varies by stated intent/discipline.
  • Quick-money / high-risk framing  -> flagged clearly, not judgmentally.
  • Disciplined position-sizing framing -> answered in kind with a proper R:R.

Norman's rails (CLAUDE.md 6.8 / 4d position-sizer methodology):
  <=1% risk per single trade, <=2% per cluster, min 1.5:1 R:R,
  6-8% total portfolio heat ceiling, Half-Kelly not full.

Math is deterministic (numbers must be right). An optional Codex pass
(norman_reply(text, use_llm=True)) rephrases the same computed facts in
Norman's voice for extra naturalness; the deterministic text is the reliable
baseline and what the bot ships by default.
"""
import re

# Norman's hard rails
MAX_RISK_PCT_TRADE = 1.0     # % of account per single trade
MAX_RISK_PCT_CLUSTER = 2.0   # % per cluster
MIN_RR = 1.5                 # minimum reward:risk

# Language that signals quick-money / undisciplined energy
_HOT_WORDS = [
    'yolo', 'all in', 'all-in', 'send it', 'sendit', 'ape', 'aping', 'degen',
    'moon', 'lambo', 'quick', 'fast money', 'easy money', 'easy', 'lottery',
    'gonna', 'double', 'triple', '10x', '100x', 'get rich', 'life changing',
    'life-changing', 'bag', 'pump', 'fomo', 'rocket', 'to the moon',
]
# Language that signals a disciplined process
_COOL_WORDS = [
    'stop', 'sl ', 'stop-loss', 'stop loss', 'position size', 'position-size',
    'r:r', 'rr', 'risk reward', 'risk-reward', 'planned', 'plan', 'setup',
    'entry', 'invalidation', 'structure', 'atr', 'sizing', '1%', '2%',
    'per trade', 'account risk', 'heat',
]


def _to_num(s: str):
    """'$1,500' -> 1500.0 ; '2k' -> 2000 ; '1.5m' -> 1_500_000."""
    if s is None:
        return None
    s = s.strip().lower().replace(',', '').replace('$', '')
    mult = 1.0
    if s.endswith('k'):
        mult, s = 1_000.0, s[:-1]
    elif s.endswith('m'):
        mult, s = 1_000_000.0, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


_NUM = r'\$?\s*([\d][\d,]*\.?\d*\s*[kmKM]?)'


def parse(text: str) -> dict:
    """Extract risk, target, asset, account, stop distance from free text."""
    t = ' ' + text.strip() + ' '
    low = t.lower()

    def grab(patterns):
        for p in patterns:
            m = re.search(p, low)
            if m:
                return _to_num(m.group(1))
        return None

    # percent-of-account risk stated explicitly ("risk 1%", "1% of the account")
    risk_pct_stated = None
    m = re.search(r'risk(?:ing)?\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*%', low) \
        or re.search(r'(\d+(?:\.\d+)?)\s*%\s+(?:risk|of (?:the )?account|account)', low)
    if m:
        try:
            risk_pct_stated = float(m.group(1))
        except ValueError:
            pass

    # dollar risk — anchored patterns reject a number that's actually a percent
    risk = grab([
        _NUM + r'\s+(?:risk|at risk|on the line)',          # "$250 risk"
        r'risk(?:ing)?\s+(?:of\s+)?' + _NUM + r'(?!\s*%)',   # "risking $500"
        r'lose\s+' + _NUM + r'(?!\s*%)',
        # framing bets: "yolo $2k on SOL", "put $800 into", "betting $2k"
        r'(?:yolo|put(?:ting)?|throw(?:ing)?|bet(?:ting)?|drop(?:ping)?|'
        r'send(?:ing)?|risk(?:ing)?)\s+' + _NUM + r'(?!\s*%)',
        _NUM + r'\s+on\s+[A-Za-z]',                          # "$2k on SOL" (fallback)
    ])
    # target dollars — exclude R-multiples ("2R") and percents
    _NOT_R = r'(?!\s*[rR%])'
    target = grab([
        r'(?:gain(?:ing)?|mak(?:e|ing)|target(?:ing)?|profit|win|for|'
        r'to get|get|net)\s+' + _NUM + _NOT_R,
        r'trying to (?:gain|make|hit)\s+' + _NUM + _NOT_R,
        _NUM + _NOT_R + r'\s+(?:target|profit|gain|upside)',
    ])
    account = grab([
        r'account\s+(?:of\s+|is\s+|size\s+)?' + _NUM,
        r'(?:balance|portfolio|capital)\s+(?:of\s+|is\s+)?' + _NUM,
        _NUM + r'\s+(?:account|balance|portfolio)',
    ])
    # asset: token after "on" / "in", or an all-caps/ticker-ish symbol
    asset = None
    m = re.search(r'\b(?:on|in|into|trading|buy|short|long)\s+'
                  r'([A-Za-z][A-Za-z0-9]*(?:[/\-][A-Za-z0-9]+)?)', text)
    if m:
        cand = m.group(1)
        if cand.lower() not in ('the', 'a', 'my', 'this', 'that', 'it'):
            asset = cand.upper()
    if not asset:
        m = re.search(r'\b([A-Z]{2,6}(?:[/\-][A-Z]{2,6})?)\b', text)
        if m:
            asset = m.group(1)

    # explicit stop distance in pts/pips (optional)
    stop_pts = None
    m = re.search(r'stop\s+(?:at\s+|of\s+|is\s+)?' + _NUM + r'\s*(?:pt|pts|point|pip)', low)
    if m:
        stop_pts = _to_num(m.group(1))

    # explicit stated R multiple ("2R", "target 3R")
    stated_r = None
    m = re.search(r'(\d+(?:\.\d+)?)\s*r\b', low)
    if m:
        try:
            stated_r = float(m.group(1))
        except ValueError:
            pass

    # If only a % risk was given and we know the account, derive the dollar risk
    if risk is None and risk_pct_stated is not None and account:
        risk = account * risk_pct_stated / 100.0

    return {
        'risk': risk, 'target': target, 'account': account, 'asset': asset,
        'stop_pts': stop_pts, 'stated_r': stated_r,
        'risk_pct_stated': risk_pct_stated,
    }


def _discipline(text: str, rr, risk_pct) -> str:
    """Classify framing: 'hot' (quick-money), 'cool' (disciplined), 'neutral'."""
    low = ' ' + text.lower() + ' '
    hot = sum(1 for w in _HOT_WORDS if w in low)
    cool = sum(1 for w in _COOL_WORDS if w in low)
    # Numeric tells override soft language
    if risk_pct is not None and risk_pct > MAX_RISK_PCT_CLUSTER:
        hot += 2
    if rr is not None and rr >= 5 and cool == 0:
        hot += 1
    if risk_pct is not None and risk_pct <= MAX_RISK_PCT_TRADE and cool:
        cool += 1
    if hot > cool:
        return 'hot'
    if cool > hot:
        return 'cool'
    return 'neutral'


def assess(text: str) -> dict:
    """Full assessment. Returns parsed fields + verdict + Norman-voiced message."""
    p = parse(text)
    risk, target, account = p['risk'], p['target'], p['account']

    # Need at least risk + (target or stated R) to compute R:R
    rr = None
    if p['stated_r'] is not None:
        rr = p['stated_r']
        if target is None and risk is not None:
            target = risk * rr
    elif risk and target:
        rr = target / risk if risk else None

    risk_pct = (risk / account * 100.0) if (risk and account) else p.get('risk_pct_stated')
    framing = _discipline(text, rr, risk_pct)

    # ---- build verdict facts ----
    flags = []
    if rr is not None and rr < 1:
        flags.append(f"reward:risk is {rr:.2f}:1 — you're risking more than you stand to make")
    elif rr is not None and rr < MIN_RR:
        flags.append(f"reward:risk is {rr:.2f}:1 — under my {MIN_RR:.1f}:1 floor")
    if risk_pct is not None and risk_pct > MAX_RISK_PCT_CLUSTER:
        flags.append(f"that's {risk_pct:.1f}% of the account on one idea — my ceiling is "
                     f"{MAX_RISK_PCT_TRADE:.0f}% per trade, {MAX_RISK_PCT_CLUSTER:.0f}% per cluster")
    elif risk_pct is not None and risk_pct > MAX_RISK_PCT_TRADE:
        flags.append(f"that's {risk_pct:.1f}% of the account — over my {MAX_RISK_PCT_TRADE:.0f}% "
                     f"per-trade rail")

    verdict = 'PASS'
    if rr is not None and rr < 1:
        verdict = 'REJECT'
    elif flags:
        verdict = 'MARGINAL'
    if risk is None:
        verdict = 'INSUFFICIENT_DATA'

    msg = _norman_voice(text, p, risk, target, account, rr, risk_pct,
                        framing, flags, verdict)
    return {
        **p, 'target': target, 'rr': rr, 'risk_pct': risk_pct,
        'framing': framing, 'verdict': verdict, 'flags': flags, 'message': msg,
    }


def _fmt(n):
    if n is None:
        return '?'
    if n == int(n):
        return f'${int(n):,}'
    return f'${n:,.2f}'


def _norman_voice(text, p, risk, target, account, rr, risk_pct,
                  framing, flags, verdict) -> str:
    asset = p['asset'] or 'this'
    L = []

    if risk is None:
        return ("Give me a number. How much are you risking, and what's the target? "
                "I don't grade vibes. — Norman")

    # Opening line varies by framing
    if framing == 'hot':
        L.append(f"Let's be honest about what this is. {_fmt(risk)} on {asset} "
                 f"chasing {_fmt(target) if target else 'an undefined number'} — "
                 f"that's quick-money energy, not a plan.")
    elif framing == 'cool':
        L.append(f"Clean setup to grade. {_fmt(risk)} risk on {asset}, "
                 f"targeting {_fmt(target) if target else '(no target stated)'}.")
    else:
        L.append(f"Risking {_fmt(risk)} on {asset} for {_fmt(target) if target else 'an unstated target'}.")

    # The math
    line = "The math:"
    if rr is not None:
        line += f" reward:risk {rr:.2f}:1."
    if risk_pct is not None:
        line += f" {risk_pct:.1f}% of a {_fmt(account)} account."
    elif account is None:
        line += " (No account size given — I can't size the % risk. Tell me the balance.)"
    L.append(line)

    # Verdict / flags
    if verdict == 'REJECT':
        L.append("This one I kill. " + flags[0].capitalize() + ". "
                 "Flip the reward and risk or don't take it.")
    elif flags:
        L.append("What I don't like: " + '; '.join(flags) + '.')
        if rr is not None and rr >= MIN_RR:
            L.append(f"The {rr:.2f}:1 is fine — it's the sizing that's loud.")
    elif framing == 'hot':
        # High R with quick-money framing = the target is a wish, not a plan
        if rr is not None and rr >= 4:
            L.append(f"And {rr:.2f}:1 isn't generosity — it's a target you pulled from the air. "
                     f"That number is only real if there's a stop that makes it real.")
    else:
        if rr is not None and rr >= 2:
            L.append(f"At {rr:.2f}:1 you can be wrong more than half the time and still come out ahead. "
                     f"That's a trade I can defend.")
        elif rr is not None:
            L.append(f"{rr:.2f}:1 clears my {MIN_RR:.1f}:1 floor. Acceptable — not generous.")

    # Closing, tone by framing
    if framing == 'hot':
        L.append("If you take it anyway, size it so the loss doesn't matter. "
                 "The market doesn't pay out on conviction. — Norman")
    elif framing == 'cool':
        if account:
            safe = account * MAX_RISK_PCT_TRADE / 100.0
            L.append(f"Keep single-trade risk at or under {_fmt(safe)} ({MAX_RISK_PCT_TRADE:.0f}%) "
                     f"and you're inside the rails. — Norman")
        else:
            L.append("Stay inside 1% per trade and let the R:R do the work. — Norman")
    else:
        L.append("Numbers first, feelings never. — Norman")

    return '\n'.join(L)


def norman_reply(text: str, use_llm: bool = False) -> str:
    """Public entry: Norman's reply for a risk-calculator message.

    Deterministic by default. With use_llm=True, the computed facts are handed
    to Codex to rephrase in Norman's voice (falls back to deterministic text on
    any failure).
    """
    result = assess(text)
    if not use_llm:
        return result['message']
    try:
        from agent_llm import run_agent
    except ImportError:
        return result['message']
    persona = (
        "You are Norman, JCF HQ's risk validator. Cold, calculated, brutally "
        "honest — never cruel, never coddling. You speak in short, declarative "
        "lines and sign off '— Norman'. You do NOT invent numbers; you only "
        "phrase the facts you're given."
    )
    facts = (
        f"A trader wrote in #risk-calculator: \"{text}\"\n\n"
        f"Computed facts (authoritative — do not change them):\n"
        f"- Risk: {_fmt(result['risk'])}\n- Target: {_fmt(result['target'])}\n"
        f"- Reward:risk: {result['rr']}\n- % of account: {result['risk_pct']}\n"
        f"- Framing detected: {result['framing']} "
        f"(hot=quick-money, cool=disciplined)\n"
        f"- Rail flags: {result['flags'] or 'none'}\n- Verdict: {result['verdict']}\n\n"
        f"Write Norman's reply (<=120 words). If framing is 'hot', flag the "
        f"quick-money energy honestly but not preachy. If 'cool', answer in kind "
        f"with the proper R:R read. End with '— Norman'."
    )
    out = run_agent(persona, facts, timeout=90)
    return out or result['message']


if __name__ == '__main__':
    import sys
    q = ' '.join(sys.argv[1:]) or "I'm risking $500 on NVDA, trying to gain $1500"
    print(norman_reply(q))
