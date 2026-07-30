#!/usr/bin/env python3
"""oanda_retry.py — bounded retry for transient OANDA v20 request failures.

Written 2026-07-30. Lens's 12:00 regime briefing reported "Data unavailable;
standing down" on SPX500, DE30 and XAU. The token was not the problem — the
same credential, replayed against the same endpoints minutes later, returned
200 with full candles on all three. The 401s were transient:

    12:00:02 performing request .../SPX500_USD/candles      -> ok
    12:00:05 performing request .../SPX500_USD/candles      -> ok
    12:00:10 request .../SPX500_USD/candles failed [401, "Insufficient
             authorization to perform request."]

At 12:00 three jobs fire on the same cron minute (the regime briefing plus
Blade's and Edge's turtle ticks) and hammer the practice API with one shared
token. OANDA answers some of that burst with 401 rather than 429, which reads
like an auth failure and isn't one.

A single-shot fetch turns that blip into a whole instrument going dark for the
session. One retry with backoff recovers it.

WHAT THIS IS NOT: a way to manufacture data. If every attempt fails the caller
still gets the exception (or an empty list) and must report the gap honestly —
Critical Rule #9 is untouched. Retrying a flaky read is not the same as
substituting a stale value for a failed one.
"""
from __future__ import annotations

import logging
import time

__all__ = ['request_with_retry', 'TRANSIENT_MARKERS']

# Substrings that mark a failure as worth retrying. OANDA returns 401 for
# burst-throttled requests as well as for genuine auth failures, so 401 is
# included — a real auth failure simply burns the retries and then surfaces,
# costing ~3s once per run rather than silently losing an instrument every run.
TRANSIENT_MARKERS = (
    'insufficient authorization',
    'too many requests',
    'service unavailable',
    'gateway timeout',
    'internal server error',
    'connection reset',
    'timed out',
    'temporarily unavailable',
)

_DEFAULT_ATTEMPTS = 3
_DEFAULT_BACKOFF = 1.5   # seconds; doubles each attempt


def _is_transient(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(m in text for m in TRANSIENT_MARKERS)


def request_with_retry(client, request, attempts: int = _DEFAULT_ATTEMPTS,
                       backoff: float = _DEFAULT_BACKOFF, label: str = ''):
    """Run `client.request(request)`, retrying transient failures.

    Returns the request object's `.response`. Re-raises the last exception if
    every attempt fails, or immediately if the failure is not transient (a bad
    instrument name should fail fast, not three times).
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            client.request(request)
            if attempt > 1:
                logging.info(f'oanda_retry: {label or request} recovered on '
                             f'attempt {attempt}/{attempts}')
            return request.response
        except Exception as exc:                     # oandapyV20 raises V20Error
            last = exc
            if not _is_transient(exc) or attempt == attempts:
                raise
            delay = backoff * (2 ** (attempt - 1))
            logging.warning(
                f'oanda_retry: {label or request} attempt {attempt}/{attempts} '
                f'failed transiently ({str(exc)[:120]}) — retrying in {delay:.1f}s'
            )
            time.sleep(delay)
    raise last                                       # pragma: no cover
