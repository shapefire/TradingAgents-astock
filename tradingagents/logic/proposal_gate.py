"""Post-LLM clamp for trader proposals — programmatic enforcement of HardSignal gates."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from tradingagents.logic.trading_hard_logic import HardSignal

if TYPE_CHECKING:
    from tradingagents.agents.schemas import ShortTermProposal, TraderProposal

_PASSIVE_SIGNAL_ACTIONS = frozenset({"观望", "回避"})


def _short_term_types() -> tuple[Any, Any, Any]:
    from tradingagents.agents.schemas import ShortTermAction, ShortTermProposal

    aggressive = frozenset({
        ShortTermAction.DABAN,
        ShortTermAction.RELAY,
        ShortTermAction.DIP_BUY,
    })
    passive = frozenset({
        ShortTermAction.WATCH,
        ShortTermAction.AVOID,
    })
    return ShortTermAction, ShortTermProposal, aggressive, passive


def format_hard_logic_override(
    adjustments: list[str],
    signal: HardSignal,
) -> str:
    """Append override block when programmatic clamp changed the proposal."""
    if not adjustments:
        return ""
    lines = [
        "",
        "---",
        "[HardLogic Override]",
    ]
    for note in adjustments:
        lines.append(f"- {note}")
    lines.append(f"- 程序化仓位上限: {signal.position_cap:.0%}")
    lines.append(
        f"- 总开关: {'可交易' if signal.can_trade else '不可交易'}"
    )
    return "\n".join(lines)


def append_hard_logic_footer(
    markdown: str,
    signal: HardSignal | None,
    extra_notes: list[str] | None = None,
) -> str:
    """Free-text fallback footer when structured clamp is unavailable."""
    if signal is None:
        return markdown
    notes = list(extra_notes or [])
    if not signal.can_trade:
        notes.append("HardSignal.can_trade=False：战术以观望/回避为准，仓位 0")
    if signal.position_cap < 1.0:
        notes.append(f"仓位不得超过 HardSignal.position_cap={signal.position_cap:.0%}")
    footer = format_hard_logic_override(notes, signal)
    if footer and footer not in markdown:
        return markdown + footer
    return markdown


def _resolve_passive_action(signal: HardSignal) -> Any:
    ShortTermAction, _, _, _ = _short_term_types()
    if signal.action in _PASSIVE_SIGNAL_ACTIONS:
        return (
            ShortTermAction.WATCH
            if signal.action == "观望"
            else ShortTermAction.AVOID
        )
    return ShortTermAction.AVOID


def clamp_short_term_proposal(
    proposal: ShortTermProposal,
    signal: HardSignal,
) -> tuple[ShortTermProposal, list[str]]:
    """Clamp ShortTermProposal to HardSignal bounds (R1-G-01 ~ R1-G-05)."""
    _, _, aggressive, passive = _short_term_types()

    adjustments: list[str] = []
    updates: dict = {}

    position = float(proposal.position)
    action = proposal.action

    if not signal.can_trade:
        passive_action = _resolve_passive_action(signal)
        if action in aggressive or action not in passive:
            updates["action"] = passive_action
            adjustments.append(
                f"can_trade=False：action {action.value} → {passive_action.value}"
            )
            action = passive_action
        if position > 0:
            updates["position"] = 0.0
            adjustments.append(f"can_trade=False：position {position:.0%} → 0")
            position = 0.0
        if proposal.entry_price is not None:
            updates["entry_price"] = None
        if proposal.stop_loss is not None:
            updates["stop_loss"] = None
        if proposal.entry_condition:
            updates["entry_condition"] = None

    if signal.position_cap <= 0 and position > 0:
        updates["position"] = 0.0
        updates["action"] = _resolve_passive_action(signal)
        adjustments.append("position_cap=0：强制观望/回避")
        position = 0.0
        action = updates["action"]

    if position > signal.position_cap:
        updates["position"] = signal.position_cap
        adjustments.append(
            f"仓位 clamp：{position:.0%} → {signal.position_cap:.0%}"
        )
        position = signal.position_cap

    if (
        action in aggressive
        and signal.action in _PASSIVE_SIGNAL_ACTIONS
    ):
        passive_action = _resolve_passive_action(signal)
        updates["action"] = passive_action
        updates["position"] = min(position, signal.position_cap)
        adjustments.append(
            f"signal.action={signal.action}：战术 {action.value} → {passive_action.value}"
        )
        action = passive_action
        position = updates["position"]

    if action in aggressive and proposal.stop_loss is None:
        adjustments.append("warning：打板/接力/低吸未设 stop_loss")

    if not updates:
        return proposal, adjustments
    return proposal.model_copy(update=updates), adjustments


def clamp_trader_proposal(
    proposal: TraderProposal,
    signal: HardSignal,
) -> tuple[TraderProposal, list[str]]:
    """Clamp TraderProposal (Buy/Hold/Sell) to HardSignal when short-term context exists."""
    from tradingagents.agents.schemas import TraderAction, TraderProposal

    adjustments: list[str] = []
    updates: dict = {}

    if not signal.can_trade or signal.position_cap <= 0:
        if proposal.action == TraderAction.BUY:
            updates["action"] = TraderAction.HOLD
            adjustments.append("can_trade=False 或 cap=0：Buy → Hold")
        if proposal.entry_price is not None:
            updates["entry_price"] = None
        if proposal.stop_loss is not None:
            updates["stop_loss"] = None

    cap_pct = f"{signal.position_cap:.0%}"
    sizing = proposal.position_sizing or ""
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", sizing)
    if pct_match and signal.position_cap < 1.0:
        implied = float(pct_match.group(1)) / 100.0
        if implied > signal.position_cap:
            new_sizing = re.sub(
                r"\d+(?:\.\d+)?\s*%",
                cap_pct,
                sizing,
                count=1,
            )
            updates["position_sizing"] = new_sizing
            adjustments.append(f"仓位 sizing clamp：{implied:.0%} → {cap_pct}")

    if not signal.can_trade and not updates.get("position_sizing"):
        updates["position_sizing"] = "0%（HardGate 不可交易）"
        adjustments.append("仓位 sizing 设为 0%")

    if not updates:
        return proposal, adjustments
    return proposal.model_copy(update=updates), adjustments
