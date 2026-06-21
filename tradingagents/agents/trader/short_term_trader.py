"""Short-Term Trader: turns research plan + hard logic into a tactical proposal."""

from __future__ import annotations

import functools

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import ShortTermProposal, render_short_term_proposal
from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.logic.proposal_gate import (
    append_hard_logic_footer,
    clamp_short_term_proposal,
    format_hard_logic_override,
)
from tradingagents.logic.trading_hard_logic import hard_signal_from_json


def create_short_term_trader(llm):
    structured_llm = bind_structured(llm, ShortTermProposal, "ShortTermTrader")

    def short_term_trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        investment_plan = state["investment_plan"]
        short_term_report = state.get("short_term_report", "")
        hard_signal_summary = state.get("hard_signal_summary", "")
        signal = hard_signal_from_json(state.get("hard_signal", ""))

        context_parts = []
        if short_term_report:
            context_parts.append(f"Short-Term Trading Report:\n{short_term_report}")
        if hard_signal_summary:
            context_parts.append(
                "Trading Hard Logic (programmatic gates — must respect can_trade and position_cap):\n"
                f"{hard_signal_summary}"
            )
        short_term_context = "\n\n".join(context_parts)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an A-share short-term trading desk officer. Translate the Research "
                    "Manager's plan into a tactical proposal bounded by TradingHardLogic gates. "
                    "Rules:\n"
                    "- Horizon: T+1~3 trading days; every 打板/接力/低吸 proposal needs a stop\n"
                    "- T+1 settlement: shares bought today cannot be sold until next trading day\n"
                    "- Daily limits: main board ±10%, STAR/ChiNext ±20%, ST ±5%\n"
                    "- If HardSignal.can_trade=False, action must be 观望 or 回避 with position=0\n"
                    "- position must be ≤ HardSignal.position_cap; never override programmatic vetoes\n"
                    "- Align action/strategy with HardSignal when gates pass\n"
                    "（以上参数仅供技术研究参考，不构成投资建议）"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Craft a short-term tactical proposal for {company_name}.\n\n"
                    f"{instrument_context}\n\n"
                    f"Research Manager Plan:\n{investment_plan}\n\n"
                    + (f"Short-Term Context:\n{short_term_context}\n\n" if short_term_context else "")
                    + "Output a precise tactic with entry, stop, and position within gate limits."
                    + get_language_instruction()
                ),
            },
        ]

        decision_obj = None
        if structured_llm is not None:
            try:
                decision_obj = structured_llm.invoke(messages)
            except Exception:
                decision_obj = None

        if decision_obj is not None:
            proposal = decision_obj
            adjustments: list[str] = []
            if signal:
                proposal, adjustments = clamp_short_term_proposal(proposal, signal)
            trader_plan = render_short_term_proposal(proposal)
            if signal and adjustments:
                trader_plan += format_hard_logic_override(adjustments, signal)
        else:
            trader_plan = invoke_structured_or_freetext(
                structured_llm,
                llm,
                messages,
                render_short_term_proposal,
                "ShortTermTrader",
            )
            trader_plan = append_hard_logic_footer(trader_plan, signal)

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(short_term_trader_node, name="Short Term Trader")
