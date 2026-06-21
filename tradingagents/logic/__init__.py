"""Trading hard logic — deterministic short-term gates."""

from tradingagents.logic.trading_hard_logic import (
    HardSignal,
    MarketContext,
    apply_gates,
    build_market_context,
    evaluate,
    evaluate_with_context,
    gate_check_portfolio_rating,
    hard_signal_to_json,
    hard_signal_to_markdown,
)

__all__ = [
    "HardSignal",
    "MarketContext",
    "apply_gates",
    "build_market_context",
    "evaluate",
    "evaluate_with_context",
    "gate_check_portfolio_rating",
    "hard_signal_to_json",
    "hard_signal_to_markdown",
]
