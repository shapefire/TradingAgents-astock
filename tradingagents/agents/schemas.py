"""Pydantic schemas used by agents that produce structured output.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared rating types
# ---------------------------------------------------------------------------


class PortfolioRating(str, Enum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    """3-tier transaction direction used by the Trader.

    The Trader's job is to translate the Research Manager's investment plan
    into a concrete transaction proposal: should the desk execute a Buy, a
    Sell, or sit on Hold this round.  Position sizing and the nuanced
    Overweight / Underweight calls happen later at the Portfolio Manager.
    """

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


class ShortTermAction(str, Enum):
    """A-share short-term tactic aligned with TradingHardLogic Gate 3 actions."""

    DABAN = "打板"
    RELAY = "接力"
    DIP_BUY = "低吸"
    WATCH = "观望"
    AVOID = "回避"


# ---------------------------------------------------------------------------
# Research Manager
# ---------------------------------------------------------------------------


class ResearchPlan(BaseModel):
    """Structured investment plan produced by the Research Manager.

    Hand-off to the Trader: the recommendation pins the directional view,
    the rationale captures which side of the bull/bear debate carried the
    argument, and the strategic actions translate that into concrete
    instructions the trader can execute against.
    """

    recommendation: PortfolioRating = Field(
        description=(
            "The investment recommendation. Exactly one of Buy / Overweight / "
            "Hold / Underweight / Sell. Reserve Hold for situations where the "
            "evidence on both sides is genuinely balanced; otherwise commit to "
            "the side with the stronger arguments."
        ),
    )
    rationale: str = Field(
        description=(
            "Conversational summary of the key points from both sides of the "
            "debate, ending with which arguments led to the recommendation. "
            "Speak naturally, as if to a teammate."
        ),
    )
    strategic_actions: str = Field(
        description=(
            "Concrete steps for the trader to implement the recommendation, "
            "including position sizing guidance consistent with the rating."
        ),
    )
    time_horizon: Optional[str] = Field(
        default=None,
        description=(
            "Recommended holding period, e.g. '3-6 months' for swing/medium term "
            "or 'T+1~3日' for short-term tactical plans."
        ),
    )


def render_research_plan(plan: ResearchPlan) -> str:
    """Render a ResearchPlan to markdown for storage and the trader's prompt context."""
    parts = [
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ]
    if plan.time_horizon:
        parts.extend(["", f"**Time Horizon**: {plan.time_horizon}"])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------


class TraderProposal(BaseModel):
    """Structured transaction proposal produced by the Trader.

    The trader reads the Research Manager's investment plan and the analyst
    reports, then turns them into a concrete transaction: what action to
    take, the reasoning that justifies it, and the practical levels for
    entry, stop-loss, and sizing.
    """

    action: TraderAction = Field(
        description="The transaction direction. Exactly one of Buy / Hold / Sell.",
    )
    reasoning: str = Field(
        description=(
            "The case for this action, anchored in the analysts' reports and "
            "the research plan. Two to four sentences."
        ),
    )
    entry_price: Optional[float] = Field(
        default=None,
        description="Optional entry price target in the instrument's quote currency.",
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description="Optional stop-loss price in the instrument's quote currency.",
    )
    position_sizing: Optional[str] = Field(
        default=None,
        description=(
            "Optional sizing guidance, e.g. '5% of portfolio'. When short-term hard logic "
            "context is present, implied allocation must be ≤ HardSignal.position_cap."
        ),
    )


def render_trader_proposal(proposal: TraderProposal) -> str:
    """Render a TraderProposal to markdown.

    The trailing ``FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`` line is
    preserved for backward compatibility with the analyst stop-signal text
    and any external code that greps for it.
    """
    parts = [
        f"**Action**: {proposal.action.value}",
        "",
        f"**Reasoning**: {proposal.reasoning}",
    ]
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    if proposal.position_sizing:
        parts.extend(["", f"**Position Sizing**: {proposal.position_sizing}"])
    parts.extend([
        "",
        f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value.upper()}**",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Short-Term Trader
# ---------------------------------------------------------------------------


class ShortTermProposal(BaseModel):
    """Structured short-term trade proposal produced by the Short-Term Trader.

    Mirrors TradingHardLogic Gate 3 strategy labels while letting the LLM
    specify executable entry/stop levels.  ``position`` must respect the
    programmatic ``HardSignal.position_cap`` injected in the prompt context.
    """

    action: ShortTermAction = Field(
        description=(
            "Short-term tactic. Exactly one of 打板 / 接力 / 低吸 / 观望 / 回避. "
            "Must align with HardSignal.action when can_trade=True; use 观望 or "
            "回避 when HardSignal.can_trade=False."
        ),
    )
    strategy: str = Field(
        description=(
            "Gate 3 strategy label, e.g. 首板打板 / 二板接力 / 高标接力 / "
            "龙头低吸 / 空仓观望 / 硬否决. Copy or refine HardSignal.strategy."
        ),
    )
    reasoning: str = Field(
        description=(
            "Two to four sentences anchoring the tactic in short_term_report "
            "and hard_signal_summary. Cite emotion phase, role, and key scores."
        ),
    )
    entry_price: Optional[float] = Field(
        default=None,
        description=(
            "Optional limit-up queue or breakout entry price in quote currency. "
            "Omit for 观望 / 回避."
        ),
    )
    entry_condition: Optional[str] = Field(
        default=None,
        description=(
            "Optional non-price entry trigger, e.g. limit-up queue or intraday pullback. "
            "Use when price level is ambiguous."
        ),
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description=(
            "Hard stop price. Short-term horizon mandates a stop for 打板/接力/低吸."
        ),
    )
    position: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Portfolio fraction to allocate (0.0–1.0). Must be ≤ HardSignal.position_cap "
            "from the programmatic gate output; use 0 when action is 观望 or 回避."
        ),
    )
    time_horizon: str = Field(
        default="T+1~3日",
        description="Holding window. Short-term mode caps at T+1~3 trading days.",
    )


def render_short_term_proposal(proposal: ShortTermProposal) -> str:
    """Render a ShortTermProposal to markdown for downstream agents and reports."""
    parts = [
        f"**Action**: {proposal.action.value}",
        "",
        f"**Strategy**: {proposal.strategy}",
        "",
        f"**Reasoning**: {proposal.reasoning}",
    ]
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.entry_condition:
        parts.extend(["", f"**Entry Condition**: {proposal.entry_condition}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    parts.extend([
        "",
        f"**Position**: {proposal.position:.0%}",
        "",
        f"**Time Horizon**: {proposal.time_horizon}",
        "",
        f"FINAL SHORT-TERM PROPOSAL: **{proposal.action.value}**",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------


class PortfolioDecision(BaseModel):
    """Structured output produced by the Portfolio Manager.

    The model fills every field as part of its primary LLM call; no separate
    extraction pass is required. Field descriptions double as the model's
    output instructions, so the prompt body only needs to convey context and
    the rating-scale guidance.
    """

    rating: PortfolioRating = Field(
        description=(
            "The final position rating. Exactly one of Buy / Overweight / Hold / "
            "Underweight / Sell, picked based on the analysts' debate."
        ),
    )
    executive_summary: str = Field(
        description=(
            "A concise action plan covering entry strategy, position sizing, "
            "key risk levels, and time horizon. Two to four sentences."
        ),
    )
    investment_thesis: str = Field(
        description=(
            "Detailed reasoning anchored in specific evidence from the analysts' "
            "debate. If prior lessons are referenced in the prompt context, "
            "incorporate them; otherwise rely solely on the current analysis."
        ),
    )
    price_target: Optional[float] = Field(
        default=None,
        description="Optional target price in the instrument's quote currency.",
    )
    time_horizon: Optional[str] = Field(
        default=None,
        description="Optional recommended holding period, e.g. '3-6 months'.",
    )


def render_pm_decision(decision: PortfolioDecision) -> str:
    """Render a PortfolioDecision back to the markdown shape the rest of the system expects.

    Memory log, CLI display, and saved report files all read this markdown,
    so the rendered output preserves the exact section headers (``**Rating**``,
    ``**Executive Summary**``, ``**Investment Thesis**``) that downstream
    parsers and the report writers already handle.
    """
    parts = [
        f"**Rating**: {decision.rating.value}",
        "",
        f"**Executive Summary**: {decision.executive_summary}",
        "",
        f"**Investment Thesis**: {decision.investment_thesis}",
    ]
    if decision.price_target is not None:
        parts.extend(["", f"**Price Target**: {decision.price_target}"])
    if decision.time_horizon:
        parts.extend(["", f"**Time Horizon**: {decision.time_horizon}"])
    return "\n".join(parts)
