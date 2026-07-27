"""agent_report.py — shared two-tier report layer for every JCF agent.

ONE generation, TWO renderings:

  Tier 1 (Telegram / Discord) — the glance. Decision first, 3-5 one-line
      headlines, every number carrying a plain-language tag, a pointer to the
      dashboard, and a hard length cap. Jase reads these on a phone.

  Tier 2 (dashboard JSON) — the depth. The same content, sectioned and
      collapsible: Decision -> Holdings -> New Ideas -> Risk Notes -> Reasoning.
      Full transcripts, all numbers, per-agent debate.

Built as ONE shared module rather than per-agent copies, for the same reason
`scripts/risk_validation.py` holds the sample-size gate once: a formatting rule
copied into five agents drifts, and the next person to fix one has no way to
know the other four exist.

DESIGN NOTE — structure is deterministic, narrative is optional.
    Tier 1 and Tier 2 are built from data, not from an LLM. A model may supply
    prose for `reasoning` / `notes`, but if it fails or is unavailable the
    report still renders with its decision, numbers and provenance intact.
    This is the same principle as Critical Rule #10 (a deterministic gate
    outranks an LLM's narrative) applied to the reporting layer. It is not
    hypothetical: the Codex subscription hit its usage limit mid-build on
    2026-07-27 and Victoria's synthesis returned nothing.

Usage:
    from agent_report import Report, Metric, Section, GLOSSARY

    r = Report(agent='victoria', kind='daily', date='2026-07-27')
    r.decide('Nothing to action today. Blade and Edge have no gradeable data.')
    r.headline('Jerry: first real verdict — FAIL on 116 trades')
    r.metric('profit_factor', 0.972, subject='Jerry')
    r.section('Holdings', rows=[...])
    print(r.tier1())            # -> str for Telegram
    r.write_tier2('/root/.openclaw/dashboard/victoria_report_v2.json')
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
# PART 3 — the plain-language layer
# ══════════════════════════════════════════════════════════════════════════════
#
# Every agent uses THIS table. Jargon never ships to Jase without a plain tag.
# Two kinds of entry:
#   'plain'  — what the term means, always appended
#   'bands'  — value-dependent reading, e.g. Sharpe 0.012 -> "no edge"
# Bands are (predicate, phrase) and the first match wins. A band phrase
# REPLACES the generic 'plain' text, because "Sharpe 0.012 (no edge once you
# account for risk)" is more useful than restating the definition.

GLOSSARY: dict[str, dict] = {
    'sharpe': {
        'label': 'Sharpe',
        'plain': 'risk-adjusted edge (higher = better; under ~1 = weak)',
        'bands': [
            (lambda v: v < 0,    'losing money after you account for risk'),
            (lambda v: v < 0.5,  'no real edge once you account for risk'),
            (lambda v: v < 1.0,  'weak edge for the risk taken'),
            (lambda v: v < 2.0,  'solid risk-adjusted edge'),
            (lambda v: True,     'very strong risk-adjusted edge'),
        ],
    },
    'profit_factor': {
        'label': 'Profit factor',
        'plain': '$ won per $ lost (under 1 = losing)',
        'bands': [
            (lambda v: v < 1.0,  'losing — under $1 won per $1 lost'),
            (lambda v: v < 1.2,  'barely break-even'),
            (lambda v: v < 1.5,  'marginal but positive'),
            (lambda v: True,     'strong — comfortably profitable'),
        ],
    },
    'expectancy': {
        'label': 'Expectancy',
        'plain': 'average $ per trade',
        'bands': [
            (lambda v: v < 0, 'loses money on the average trade'),
            (lambda v: True,  'average $ per trade'),
        ],
    },
    'max_drawdown_pct': {
        'label': 'Max drawdown',
        'plain': 'worst peak-to-trough drop',
        'bands': [
            (lambda v: v > 100, 'IMPOSSIBLE as a drawdown — accounting error, not a trading result'),
            (lambda v: v > 50,  'worst peak-to-trough drop — severe'),
            (lambda v: v > 25,  'worst peak-to-trough drop — heavy'),
            (lambda v: True,    'worst peak-to-trough drop'),
        ],
    },
    'win_rate': {
        'label': 'Win rate',
        'plain': 'share of trades that made money',
    },
    'ruin_probability': {
        'label': 'Risk of ruin',
        'plain': 'chance of blowing up the account',
        'bands': [
            (lambda v: v <= 0,   'no modelled chance of blowing up the account'),
            (lambda v: v < 0.05, 'small chance of blowing up the account'),
            (lambda v: True,     'meaningful chance of blowing up the account'),
        ],
    },
    'beta': {
        'label': 'Beta',
        'plain': 'how hard it swings vs the market — 2.0 = twice as jumpy',
    },
    'r_multiple': {
        'label': 'R-multiple',
        'plain': 'profit in units of the risk taken — 2R = twice what you risked',
    },
    'devig': {
        'label': 'Devig',
        'plain': "the true odds with the bookmaker's margin stripped out",
    },
    'sortino': {
        'label': 'Sortino',
        'plain': 'like Sharpe but only counts downside swings',
    },
    'max_consec_losses': {
        'label': 'Worst losing streak',
        'plain': 'most losses in a row',
    },
    'total_pnl': {'label': 'Net P&L', 'plain': 'money made or lost overall'},
    'n':         {'label': 'Sample',  'plain': 'number of closed trades behind these numbers'},
}

# Verdicts also get a plain reading — these are the words Jase actually sees.
VERDICT_PLAIN = {
    'PASS':              'cleared',
    'FAIL':              'not deployable as-is',
    'MARGINAL':          'borderline — not ready',
    'REFINE':            'needs work before it can be judged',
    'ABANDON':           'stop — no edge here',
    'NO_DATA':           'nothing to judge — no trades recorded',
    'INSUFFICIENT_DATA': 'too few trades to judge yet',
    'STALE_DATA':        'feed is out of date — cannot judge',
    'NO_BALANCE':        'no account balance — cannot judge',
    'UNKNOWN':           'not yet assessed',
}

TIER1_CHAR_CAP = 750          # roughly one phone screen without much scrolling
DECISION_LINE_CAP = 130       # a decision is a line, not a paragraph
MAX_DECISION_LINES = 3        # "One to three lines, top of message"
HEADLINE_CAP = 85             # each headline is ONE line
HEADLINE_RESERVE = 260        # chars held back so headlines always survive
DASHBOARD_URL = 'Full breakdown on the dashboard →'


def explain(term: str, value=None) -> str:
    """Plain-language tag for a metric. Returns '' for unknown terms."""
    entry = GLOSSARY.get(term)
    if not entry:
        return ''
    if value is not None and 'bands' in entry:
        try:
            v = float(value)
            for predicate, phrase in entry['bands']:
                if predicate(v):
                    return phrase
        except (TypeError, ValueError):
            pass
    return entry.get('plain', '')


def label_for(term: str) -> str:
    entry = GLOSSARY.get(term)
    return entry['label'] if entry else term.replace('_', ' ')


def plain_verdict(verdict: str) -> str:
    return VERDICT_PLAIN.get((verdict or '').upper(), '')


# ══════════════════════════════════════════════════════════════════════════════
# Data model — one generation feeds both tiers
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Metric:
    """A number that always travels with its plain-language reading."""
    term: str
    value: object
    subject: str = ''          # e.g. 'Jerry' — whose number is this
    unit: str = ''             # '%', '$', ''
    note: str = ''             # optional override for the plain tag

    def formatted_value(self) -> str:
        v = self.value
        if v is None:
            return 'n/a'
        if isinstance(v, float):
            av = abs(v)
            if av >= 1000:
                text = f'{v:,.0f}'
            elif av < 1:
                # Keep small ratios legible: Sharpe 0.012, not 0.01.
                text = f'{v:.3f}'.rstrip('0')
                if text.endswith('.'):
                    text += '0'
            else:
                text = f'{v:,.2f}'.rstrip('0')
                if text.endswith('.'):
                    text += '0'
        else:
            text = str(v)
        if self.unit == '$':
            return f'${text}'
        if self.unit == '%':
            return f'{text}%'
        return text

    def render(self) -> str:
        """'Sharpe 0.012 (no edge once you account for risk)'"""
        tag = self.note or explain(self.term, self.value)
        head = f'{label_for(self.term)} {self.formatted_value()}'
        if self.subject:
            head = f'{self.subject} {head[0].lower()}{head[1:]}'
        return f'{head} ({tag})' if tag else head


@dataclass
class Section:
    """A Tier-2 section. Collapsed by default unless it holds the decision."""
    title: str
    body: str = ''
    rows: list = field(default_factory=list)
    collapsed: bool = True

    def to_dict(self) -> dict:
        return {
            'title': self.title,
            'body': self.body,
            'rows': self.rows,
            'collapsed': self.collapsed,
        }


@dataclass
class Report:
    agent: str
    kind: str                                   # daily | weekly | thesis | council
    date: str
    decision_lines: list = field(default_factory=list)
    headlines: list = field(default_factory=list)
    metrics: list = field(default_factory=list)
    sections: list = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    degraded: list = field(default_factory=list)   # what was missing/stale

    # ── builders ────────────────────────────────────────────────────────────
    def decide(self, *lines: str) -> 'Report':
        """THE decision. 1-3 lines, top of the message. Say it plainly."""
        self.decision_lines.extend(l for l in lines if l)
        return self

    def headline(self, *lines: str) -> 'Report':
        self.headlines.extend(l for l in lines if l)
        return self

    def metric(self, term: str, value, subject: str = '', unit: str = '',
               note: str = '') -> 'Report':
        self.metrics.append(Metric(term, value, subject, unit, note))
        return self

    def section(self, title: str, body: str = '', rows: list | None = None,
                collapsed: bool = True) -> 'Report':
        self.sections.append(Section(title, body, rows or [], collapsed))
        return self

    def source(self, name: str, freshness) -> 'Report':
        """Record where a number came from and whether it is current."""
        if freshness is None:
            self.provenance[name] = {'ok': False, 'reason': 'absent', 'marker': '⚠️ NO DATA'}
            self.degraded.append(name)
            return self
        if hasattr(freshness, 'ok'):
            entry = {
                'ok': bool(getattr(freshness, 'ok', False)),
                'reason': getattr(freshness, 'reason', ''),
                'marker': freshness.marker() if hasattr(freshness, 'marker') else '',
                'as_of': str(getattr(freshness, 'as_of', '') or ''),
            }
        else:
            entry = dict(freshness)
        self.provenance[name] = entry
        if not entry.get('ok'):
            self.degraded.append(name)
        return self

    # ── TIER 1 — the glance ─────────────────────────────────────────────────
    @staticmethod
    def _compress(line: str, limit: int = DECISION_LINE_CAP) -> str:
        """Squeeze a decision to its first sentence, then to a hard limit.

        Models return paragraphs. The brief asks for one to three LINES at the
        top of the message — and if a decision eats the whole budget, the
        headlines get trimmed away and Jase loses the scan layer entirely.
        The full prose is never lost; it is in Tier 2's Reasoning section.
        """
        text = ' '.join(str(line).split())
        if len(text) <= limit:
            return text
        # Prefer a clean sentence break inside the budget.
        cut = -1
        for end in ('. ', '! ', '? '):
            cut = max(cut, text.rfind(end, 0, limit + 1))
        if cut > limit * 0.5:
            return text[:cut + 1].strip()
        return text[:limit].rsplit(' ', 1)[0].rstrip(',;:') + '…'

    def tier1(self, cap: int = TIER1_CHAR_CAP) -> str:
        """Telegram/Discord text. Decision first, then headlines, under a cap.

        Budget-aware assembly rather than "build everything, then trim from the
        bottom". The naive version let three long decision lines consume the
        whole allowance, so every headline was trimmed away and the scan layer
        disappeared exactly when there was most to scan.

        Priority: header, the FIRST decision line and the dashboard pointer are
        guaranteed. Headlines get a reserved slice. Extra decision lines take
        whatever is left over.
        """
        from telegram_personalities import AGENT_EMOJIS, AGENT_DISPLAY  # local import
        emoji = AGENT_EMOJIS.get(self.agent, '📋') if AGENT_EMOJIS else '📋'
        name = (AGENT_DISPLAY.get(self.agent, self.agent) if AGENT_DISPLAY
                else self.agent).upper()
        kind = self.kind.upper()
        head = (f'{emoji} {name} — {self.date}' if kind == name
                else f'{emoji} {name} — {kind} {self.date}')

        decision = [self._compress(d) for d in
                    (self.decision_lines or ['No decision recorded.'])[:MAX_DECISION_LINES]]
        heads = [self._compress(h, HEADLINE_CAP) for h in self.headlines[:5]]

        warn = ''
        if self.degraded:
            warn = (f'⚠️ Not current: {", ".join(sorted(set(self.degraded)))}'
                    f' — no verdict issued on these.')

        reserve = min(sum(len(h) + 3 for h in heads), HEADLINE_RESERVE) if heads else 0
        used = len(head) + 2 + len(decision[0]) + 2 + len(DASHBOARD_URL)
        used += (len(warn) + 2) if warn else 0
        budget = cap - used - reserve

        kept = [decision[0]]
        for d in decision[1:]:
            if len(d) + 1 <= budget:
                kept.append(d)
                budget -= len(d) + 1

        parts = [head, '', *kept]
        if heads:
            parts.append('')
            room = (cap - len('\n'.join(parts)) - len(DASHBOARD_URL) - 2
                    - ((len(warn) + 2) if warn else 0))
            for h in heads:
                if len(h) + 3 > room:
                    break
                parts.append(f'• {h}')
                room -= len(h) + 3
        if warn:
            parts += ['', warn]
        parts += ['', DASHBOARD_URL]
        return '\n'.join(parts)

    # ── TIER 2 — the depth ──────────────────────────────────────────────────
    def tier2(self) -> dict:
        """Structured dashboard JSON. The frontend renders this; no styling here."""
        ordered = ['Decision', 'Holdings', 'New Ideas', 'Risk Notes', 'Reasoning']
        by_title = {s.title: s for s in self.sections}
        sections = [by_title.pop(t).to_dict() for t in ordered if t in by_title]
        sections += [s.to_dict() for s in self.sections if s.title in by_title]

        return {
            'schema': 'jcf.agent_report/v1',
            'agent': self.agent,
            'kind': self.kind,
            'date': self.date,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'tier1_text': self.tier1(),
            'decision': self.decision_lines,
            'headlines': self.headlines,
            'metrics': [
                {
                    'term': m.term,
                    'label': label_for(m.term),
                    'value': m.value,
                    'subject': m.subject,
                    'display': m.formatted_value(),
                    'plain': m.note or explain(m.term, m.value),
                    'rendered': m.render(),
                }
                for m in self.metrics
            ],
            'sections': sections,
            'provenance': self.provenance,
            'degraded_sources': sorted(set(self.degraded)),
            'glossary_used': sorted({m.term for m in self.metrics if m.term in GLOSSARY}),
        }

    def write_tier2(self, path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.tier2(), indent=2, default=str))
        return p


# ══════════════════════════════════════════════════════════════════════════════
# Convenience: build a Report straight from a validator payload
# ══════════════════════════════════════════════════════════════════════════════

def from_validation(agent: str, kind: str, validation: dict,
                    display_names: dict | None = None) -> Report:
    """Turn a lens_validation.json / victoria_validation.json payload into a Report.

    Keeps the two validators from each inventing their own report shape.
    """
    display_names = display_names or {}
    date = validation.get('date') or datetime.now(timezone.utc).date().isoformat()
    r = Report(agent=agent, kind=kind, date=date)

    reports = validation.get('agent_reports') or {}
    gradeable, blocked = [], []

    for internal, ar in reports.items():
        shown = display_names.get(internal, internal.capitalize())
        verdict = (ar.get('verdict') or 'UNKNOWN').upper()
        n = ar.get('total_trades', ar.get('n', 0)) or 0
        plain = plain_verdict(verdict)

        if verdict in ('NO_DATA', 'STALE_DATA', 'INSUFFICIENT_DATA', 'NO_BALANCE', 'UNKNOWN'):
            blocked.append(f'{shown}: {verdict} — {plain}')
            r.headline(f'{shown}: {verdict.replace("_", " ").lower()} — {plain}')
        else:
            gradeable.append(f'{shown}: {verdict} — {plain}')
            r.headline(f'{shown}: {verdict} on {n} trades — {plain}')
            for term in ('profit_factor', 'sharpe', 'win_rate', 'expectancy'):
                if ar.get(term) is not None:
                    unit = '%' if term == 'win_rate' else ('$' if term == 'expectancy' else '')
                    r.metric(term, ar[term], subject=shown, unit=unit)

        rows = [{'metric': label_for(k), 'value': ar.get(k), 'plain': explain(k, ar.get(k))}
                for k in ('total_trades', 'win_rate', 'profit_factor', 'sharpe',
                          'expectancy', 'max_drawdown_pct')
                if ar.get(k) is not None]
        if rows or ar.get('recommendation'):
            r.section(f'{shown} — detail', body=ar.get('recommendation', ''), rows=rows)

    if gradeable:
        r.decide(*gradeable)
    if blocked and not gradeable:
        r.decide('No verdicts today — every feed is absent or out of date.')

    for name, f in (validation.get('_freshness', {}).get('detail') or {}).items():
        r.source(display_names.get(name, name), f)

    return r
