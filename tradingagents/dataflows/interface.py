import inspect
import logging
from typing import Annotated

logger = logging.getLogger(__name__)

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage_common import AlphaVantageRateLimitError
from .a_stock import (
    resolve_ticker,
    get_stock_data as get_astock_stock_data,
    get_indicators as get_astock_indicators,
    get_fundamentals as get_astock_fundamentals,
    get_balance_sheet as get_astock_balance_sheet,
    get_cashflow as get_astock_cashflow,
    get_income_statement as get_astock_income_statement,
    get_news as get_astock_news,
    get_global_news as get_astock_global_news,
    get_insider_transactions as get_astock_insider_transactions,
    get_profit_forecast as get_astock_profit_forecast,
    get_hot_stocks as get_astock_hot_stocks,
    get_northbound_flow as get_astock_northbound_flow,
    get_concept_blocks as get_astock_concept_blocks,
    get_fund_flow as get_astock_fund_flow,
    get_dragon_tiger_board as get_astock_dragon_tiger_board,
    get_lockup_expiry as get_astock_lockup_expiry,
    get_industry_comparison as get_astock_industry_comparison,
    get_margin_trading as get_astock_margin_trading,
    get_block_trade as get_astock_block_trade,
    get_shareholder_count as get_astock_shareholder_count,
    get_research_reports as get_astock_research_reports,
    get_dividend_history as get_astock_dividend_history,
    get_daily_dragon_tiger as get_astock_daily_dragon_tiger,
    get_northbound_stock_holdings as get_astock_northbound_stock_holdings,
    get_cninfo_announcements as get_astock_cninfo_announcements,
    get_consecutive_limit_stats as get_astock_consecutive_limit_stats,
    get_theme_heat as get_astock_theme_heat,
    get_first_board_screen as get_astock_first_board_screen,
    get_high_board_status as get_astock_high_board_status,
    get_leader_identification as get_astock_leader_identification,
    get_auction_strength as get_astock_auction_strength,
)

# Configuration and routing logic
from .config import get_config

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    },
    "signal_data": {
        "description": "A-stock signal layer (topic attribution, capital flow, consensus forecast)",
        "tools": [
            "get_profit_forecast",
            "get_hot_stocks",
            "get_northbound_flow",
            "get_concept_blocks",
            "get_fund_flow",
            "get_dragon_tiger_board",
            "get_lockup_expiry",
            "get_industry_comparison",
        ]
    },
    "capital_flow": {
        "description": "Capital flow & chip layer (margin, block trade, shareholder, dividends)",
        "tools": [
            "get_margin_trading",
            "get_block_trade",
            "get_shareholder_count",
            "get_research_reports",
            "get_dividend_history",
            "get_daily_dragon_tiger",
            "get_northbound_stock_holdings",
            "get_cninfo_announcements",
        ]
    },
    "short_term_data": {
        "description": "Short-term trading signals (limit-up boards, theme heat, leader identification)",
        "tools": [
            "get_consecutive_limit_stats",
            "get_theme_heat",
            "get_first_board_screen",
            "get_high_board_status",
            "get_leader_identification",
            "get_auction_strength",
        ]
    }
}

VENDOR_LIST = [
    "a_stock",
    "yfinance",
    "alpha_vantage",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "a_stock": get_astock_stock_data,
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
    },
    # technical_indicators
    "get_indicators": {
        "a_stock": get_astock_indicators,
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
    },
    # fundamental_data
    "get_fundamentals": {
        "a_stock": get_astock_fundamentals,
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "a_stock": get_astock_balance_sheet,
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "a_stock": get_astock_cashflow,
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "a_stock": get_astock_income_statement,
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    # news_data
    "get_news": {
        "a_stock": get_astock_news,
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
    },
    "get_global_news": {
        "a_stock": get_astock_global_news,
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_transactions": {
        "a_stock": get_astock_insider_transactions,
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
    # signal_data (A-stock only)
    "get_profit_forecast": {
        "a_stock": get_astock_profit_forecast,
    },
    "get_hot_stocks": {
        "a_stock": get_astock_hot_stocks,
    },
    "get_northbound_flow": {
        "a_stock": get_astock_northbound_flow,
    },
    "get_concept_blocks": {
        "a_stock": get_astock_concept_blocks,
    },
    "get_fund_flow": {
        "a_stock": get_astock_fund_flow,
    },
    "get_dragon_tiger_board": {
        "a_stock": get_astock_dragon_tiger_board,
    },
    "get_lockup_expiry": {
        "a_stock": get_astock_lockup_expiry,
    },
    "get_industry_comparison": {
        "a_stock": get_astock_industry_comparison,
    },
    # capital_flow (A-stock only)
    "get_margin_trading": {
        "a_stock": get_astock_margin_trading,
    },
    "get_block_trade": {
        "a_stock": get_astock_block_trade,
    },
    "get_shareholder_count": {
        "a_stock": get_astock_shareholder_count,
    },
    "get_research_reports": {
        "a_stock": get_astock_research_reports,
    },
    "get_dividend_history": {
        "a_stock": get_astock_dividend_history,
    },
    "get_daily_dragon_tiger": {
        "a_stock": get_astock_daily_dragon_tiger,
    },
    "get_northbound_stock_holdings": {
        "a_stock": get_astock_northbound_stock_holdings,
    },
    "get_cninfo_announcements": {
        "a_stock": get_astock_cninfo_announcements,
    },
    # short_term_data (A-stock only)
    "get_consecutive_limit_stats": {
        "a_stock": get_astock_consecutive_limit_stats,
    },
    "get_theme_heat": {
        "a_stock": get_astock_theme_heat,
    },
    "get_first_board_screen": {
        "a_stock": get_astock_first_board_screen,
    },
    "get_high_board_status": {
        "a_stock": get_astock_high_board_status,
    },
    "get_leader_identification": {
        "a_stock": get_astock_leader_identification,
    },
    "get_auction_strength": {
        "a_stock": get_astock_auction_strength,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

# ---------------------------------------------------------------------------
# Per-run vendor cache — populated by prefetch_vendor_data() and individual
# tool calls, cleared at the start of each analysis run via clear_vendor_cache().
# Key: (method, args_tuple, frozenset_of_kwargs) → cached return value
# ---------------------------------------------------------------------------
_vendor_cache: dict[tuple, object] = {}


def clear_vendor_cache() -> None:
    """Clear the per-run vendor cache.

    Called at the start of each analysis run (TradingAgentsGraph.propagate)
    so that stale data from a previous run is never served.
    """
    global _vendor_cache
    _vendor_cache = {}


def _resolve_impl_func(method: str, vendor: str):
    """Resolve the actual callable for a given method+vendor."""
    vendor_impl = VENDOR_METHODS[method][vendor]
    return vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl


def _normalize_cache_key(method: str, args: tuple, kwargs: dict) -> tuple:
    """Build a canonical cache key from positional + keyword args.

    Prefetch calls use keyword args (``route_to_vendor("get_fundamentals",
    (), {"ticker": t, "curr_date": d})``) while @tool wrappers use positional
    args (``route_to_vendor("get_fundamentals", t, d)``).  Without
    normalization the two produce different cache keys and the prefetch result
    is wasted.

    The function inspects the primary vendor implementation's signature to
    bind positional args to parameter names, then builds a single canonical
    key of ``(method, frozenset_of_bound_arguments)``.
    """
    if method not in VENDOR_METHODS:
        return (method, args, tuple(sorted(kwargs.items())))

    # Get the primary vendor's implementation to inspect its signature
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendor = vendor_config.split(',')[0].strip()
    if primary_vendor not in VENDOR_METHODS.get(method, {}):
        return (method, args, tuple(sorted(kwargs.items())))

    impl_func = _resolve_impl_func(method, primary_vendor)

    # Unwrap if wrapped (e.g. by @tool or other decorators)
    raw = getattr(impl_func, '__wrapped__', impl_func)

    try:
        sig = inspect.signature(raw)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        # Use frozenset for order-independent comparison
        return (method, frozenset(bound.arguments.items()))
    except (TypeError, ValueError):
        # Fallback: if we can't inspect the signature, use the original key
        return (method, args, tuple(sorted(kwargs.items())))


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with caching and fallback support.

    Results are cached per normalized (method, bound-args) tuple so that
    duplicate calls — whether via prefetch (keyword args) or @tool wrappers
    (positional args) — hit the same cache entry.  The cache is cleared at
    the start of each propagate() call.
    """
    cache_key = _normalize_cache_key(method, args, kwargs)
    if cache_key in _vendor_cache:
        return _vendor_cache[cache_key]

    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            result = impl_func(*args, **kwargs)
            _vendor_cache[cache_key] = result
            return result
        except AlphaVantageRateLimitError:
            continue  # Rate limits trigger fallback to next vendor
        except Exception:
            # Non-rate-limit errors (network, proxy, timeout) — try next vendor
            # rather than crashing the entire analysis pipeline.
            logger.debug("Vendor %s failed for %s, trying next", vendor, method)
            continue

    # All vendors failed — return a graceful empty result instead of raising,
    # so the analysis pipeline continues with missing data rather than blocking.
    logger.warning("All vendors failed for %s, returning empty result", method)
    return ""