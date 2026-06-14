"""Pre-fetch deterministic tool data in parallel before the graph runs.

Populates the vendor cache so that analyst tool calls are instant cache hits.
Only tools whose parameters are fully known (no LLM-chosen arguments) are
pre-fetched.  Tools like ``get_news`` (LLM picks date range) or
``get_indicators`` (LLM picks indicator name) are left for the first analyst
that needs them; subsequent analysts benefit from the vendor cache automatically.

The pre-fetch uses a small ThreadPoolExecutor (default 6 workers) so the 14
HTTP requests complete in the time of the single slowest one (~5-10 s) rather
than the sum of all (~80 s).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger(__name__)

# Each entry: (vendor_method, positional_args, keyword_args)
# Placeholders {ticker} and {date} are resolved at runtime.
_PREFETCH_TASKS: list[tuple[str, tuple, dict[str, str]]] = [
    # --- News / sentiment (used by social, news, policy, hot_money, lockup) ---
    ("get_global_news",      (), {"curr_date": "{date}"}),
    ("get_insider_transactions", (), {"ticker": "{ticker}"}),
    # --- Fundamentals (used by fundamentals, lockup) ---
    ("get_fundamentals",     (), {"ticker": "{ticker}", "curr_date": "{date}"}),
    ("get_balance_sheet",    (), {"ticker": "{ticker}"}),
    ("get_cashflow",         (), {"ticker": "{ticker}"}),
    ("get_income_statement", (), {"ticker": "{ticker}"}),
    # --- Signal data (used by hot_money, fundamentals) ---
    ("get_profit_forecast",  (), {"ticker": "{ticker}"}),
    ("get_hot_stocks",       (), {"curr_date": "{date}"}),
    ("get_northbound_flow",  (), {"curr_date": "{date}"}),
    ("get_concept_blocks",   (), {"ticker": "{ticker}"}),
    ("get_fund_flow",        (), {"ticker": "{ticker}", "curr_date": "{date}"}),
    ("get_dragon_tiger_board", (), {"ticker": "{ticker}", "curr_date": "{date}"}),
    ("get_lockup_expiry",    (), {"ticker": "{ticker}", "curr_date": "{date}"}),
    ("get_industry_comparison", (), {"ticker": "{ticker}", "curr_date": "{date}"}),
]


def _resolve_templates(
    tasks: list[tuple[str, tuple, dict[str, str]]],
    ticker: str,
    trade_date: str,
) -> list[tuple[str, tuple, dict[str, str]]]:
    """Replace ``{ticker}`` and ``{date}`` placeholders with actual values."""
    resolved: list[tuple[str, tuple, dict[str, str]]] = []
    for method, args, kwargs in tasks:
        resolved_args = tuple(
            a.replace("{ticker}", ticker).replace("{date}", trade_date)
            if isinstance(a, str) else a
            for a in args
        )
        resolved_kwargs = {
            k: v.replace("{ticker}", ticker).replace("{date}", trade_date)
            if isinstance(v, str) else v
            for k, v in kwargs.items()
        }
        resolved.append((method, resolved_args, resolved_kwargs))
    return resolved


def prefetch_vendor_data(
    ticker: str,
    trade_date: str,
    max_workers: int = 6,
) -> int:
    """Pre-fetch deterministic tool data in parallel into the vendor cache.

    This function is called once at the start of each analysis run, before
    the LangGraph pipeline begins.  It populates the same cache that
    ``route_to_vendor()`` reads from, so analyst tool calls that hit the
    same (method, args, kwargs) tuple return instantly.

    Args:
        ticker: Resolved 6-digit A-stock code (e.g. ``300750``).
        trade_date: Trading date in ``YYYY-MM-DD`` format.
        max_workers: Thread pool size.  6 is a good default for I/O-bound
            HTTP requests — enough parallelism without overwhelming the
            upstream data providers.

    Returns:
        Number of successful pre-fetches (out of 14).
    """
    # Lazy import so that importing this module at collection time does not
    # pull in the full vendor stack.
    from .interface import route_to_vendor

    tasks = _resolve_templates(_PREFETCH_TASKS, ticker, trade_date)
    success_count = 0

    def _fetch_one(
        method: str, args: tuple, kwargs: dict[str, str]
    ) -> tuple[str, bool, str]:
        """Call route_to_vendor; return (method, success, error_msg)."""
        try:
            route_to_vendor(method, *args, **kwargs)
            return (method, True, "")
        except Exception as exc:
            # Non-fatal: the analyst's own tool call will retry normally.
            return (method, False, f"{type(exc).__name__}: {exc}")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_fetch_one, m, a, kw): m
            for m, a, kw in tasks
        }
        for future in as_completed(futures):
            method, ok, err = future.result()
            if ok:
                success_count += 1
                logger.debug("Pre-fetched: %s", method)
            else:
                # Log at warning level but do NOT raise — graceful degradation.
                logger.warning("Pre-fetch skipped %s: %s", method, err)

    logger.info(
        "Pre-fetch complete: %d/%d succeeded for %s on %s",
        success_count, len(tasks), ticker, trade_date,
    )
    return success_count
