"""Prompt snippets derived from programmatic HardSignal JSON."""

from __future__ import annotations

import re

from tradingagents.logic.trading_hard_logic import hard_signal_from_json

EMOTION_PHASE_TOKENS = ("冰点", "退潮", "修复", "升温", "高潮", "低迷")
STRATEGY_TOKENS = ("打板", "接力", "低吸", "观望", "回避")


def build_bear_veto_instruction(hard_signal_raw: str) -> str:
    """When many vetoes fire, Bear must argue Hold/Sell."""
    signal = hard_signal_from_json(hard_signal_raw)
    if signal is None:
        return ""

    veto_count = len(signal.veto_reasons)
    if veto_count >= 3:
        veto_text = "、".join(signal.veto_reasons)
        return (
            f"\n⚠️ HARD GATE ALERT: {veto_count} active veto reasons ({veto_text}). "
            "You MUST conclude with a clear recommendation to Hold or Sell — "
            "do not argue for Buy or Overweight.\n"
        )
    if not signal.can_trade:
        return (
            "\n⚠️ HARD GATE: can_trade=False. Your bear case should favor Hold or Sell.\n"
        )
    return ""


def build_bull_gate_reminder(hard_signal_raw: str) -> str:
    """Remind Bull that programmatic gates cannot be overridden."""
    signal = hard_signal_from_json(hard_signal_raw)
    if signal is None:
        return ""

    if signal.veto_reasons:
        return (
            f"\n⚠️ Hard logic vetoes ({len(signal.veto_reasons)}): "
            f"{', '.join(signal.veto_reasons)}. "
            "Acknowledge these limits; do not claim gates can be ignored.\n"
        )
    if signal.position_cap < 0.15 and signal.can_trade:
        return (
            f"\n⚠️ Hard logic caps position at {signal.position_cap:.0%}; "
            "bull thesis must respect this ceiling.\n"
        )
    return ""


def build_aggressive_gate_instruction(hard_signal_raw: str) -> str:
    """Aggressive analyst cannot advocate full risk when gates block trading."""
    signal = hard_signal_from_json(hard_signal_raw)
    if signal is None:
        return ""

    if not signal.can_trade:
        veto_text = "、".join(signal.veto_reasons) if signal.veto_reasons else "硬逻辑禁止"
        return (
            f"\n⚠️ HARD GATE: can_trade=False ({veto_text}). "
            "You may debate position sizing within limits but MUST NOT argue for "
            "aggressive Buy or full-size entry. Respect action="
            f"{signal.action} and position_cap={signal.position_cap:.0%}.\n"
        )
    if signal.position_cap <= 0.10:
        return (
            f"\n⚠️ Hard logic limits position_cap to {signal.position_cap:.0%}. "
            "Aggressive upside arguments must stay within this cap.\n"
        )
    return ""


def build_risk_hard_signal_block(
    hard_signal_summary: str,
    hard_signal_raw: str,
) -> str:
    """Context block for risk debate agents."""
    if not hard_signal_summary and not hard_signal_raw:
        return ""
    parts = ["Trading hard logic gates (deterministic, cannot be overridden):"]
    if hard_signal_summary:
        parts.append(hard_signal_summary)
    signal = hard_signal_from_json(hard_signal_raw)
    if signal and signal.veto_reasons:
        parts.append(f"Veto reasons: {', '.join(signal.veto_reasons)}")
    return "\n".join(parts)


def check_short_term_report_coverage(report: str) -> list[str]:
    """T2-14: short_term report must mention emotion phase and strategy."""
    issues: list[str] = []
    if not any(token in report for token in EMOTION_PHASE_TOKENS):
        issues.append("缺少情绪阶段描述（冰点/退潮/修复/升温/高潮/低迷）")
    if not any(token in report for token in STRATEGY_TOKENS):
        issues.append("缺少短线策略建议（打板/接力/低吸/观望/回避）")
    return issues


def check_hard_signal_report_consistency(
    report: str,
    hard_signal_raw: str,
) -> list[str]:
    """T2-15: flag score drift between analyst report and HardSignal JSON."""
    signal = hard_signal_from_json(hard_signal_raw)
    if signal is None or not report:
        return []

    issues: list[str] = []
    phase_base = signal.emotion_phase.split("(")[0].strip()
    if phase_base and phase_base not in report:
        issues.append(f"报告未体现情绪阶段「{signal.emotion_phase}」")

    emotion_scores = re.findall(r"情绪(?:分|评分)?[：:\s]*(\d+)", report)
    if emotion_scores and signal.emotion_score >= 0:
        reported = int(emotion_scores[0])
        if abs(reported - signal.emotion_score) > 10:
            issues.append(
                f"情绪分偏差: 报告{reported} vs 硬逻辑{signal.emotion_score}"
            )

    if signal.second_board_score >= 0:
        match = re.search(r"二板预期(?:分)?[：:\s]*(\d+)", report)
        if match:
            reported = int(match.group(1))
            if abs(reported - signal.second_board_score) > 15:
                issues.append(
                    f"二板预期分偏差: 报告{reported} vs 硬逻辑{signal.second_board_score}"
                )

    if signal.leader_score >= 0:
        match = re.search(r"龙头(?:评分|分)?[：:\s]*(\d+)", report)
        if match:
            reported = int(match.group(1))
            if abs(reported - signal.leader_score) > 15:
                issues.append(
                    f"龙头评分偏差: 报告{reported} vs 硬逻辑{signal.leader_score}"
                )

    strategy_hint = signal.strategy or signal.action
    if strategy_hint and strategy_hint not in report:
        issues.append(f"报告未体现硬逻辑策略「{strategy_hint}」")

    return issues
