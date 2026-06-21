"""Tests for hard-logic prompt helpers and quality gate consistency checks."""

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.quality_gate import create_quality_gate
from tradingagents.agents.utils.hard_logic_prompt import (
    build_aggressive_gate_instruction,
    build_bear_veto_instruction,
    check_hard_signal_report_consistency,
    check_short_term_report_coverage,
)
from tradingagents.logic.trading_hard_logic import HardSignal, hard_signal_to_json


def _sample_signal(**overrides) -> HardSignal:
    base = {
        "ticker": "000001",
        "trade_date": "2026-06-16",
        "emotion_phase": "修复",
        "emotion_score": 58,
        "breadth_signal": "正常",
        "yesterday_limitup_avg_return": 1.2,
        "can_trade": True,
        "market_gate_passed": True,
        "in_limitup_pool": True,
        "consecutive_days": 1,
        "role": "首板候选",
        "theme": "AI",
        "theme_rank": 2,
        "second_board_score": 72,
        "leader_score": -1,
        "divergence_score": -1,
        "break_risk": "不适用",
        "seal_ratio": 4.5,
        "is_yizi_unbuyable": False,
        "unlock_pressure_pct": 0.0,
        "has_regulatory_alert": False,
        "st_flag": False,
        "action": "打板",
        "position_cap": 0.15,
        "strategy": "首板打板",
        "veto_reasons": [],
        "gates_passed": ["G3-首板打板"],
        "confidence": "medium",
        "data_sources": {},
    }
    base.update(overrides)
    return HardSignal(**base)


@pytest.mark.unit
class TestHardLogicPromptHelpers:
    def test_bear_veto_instruction_when_three_vetoes(self):
        signal = _sample_signal(
            can_trade=False,
            veto_reasons=["冰点确认", "一字不可买", "解禁重压"],
        )
        text = build_bear_veto_instruction(hard_signal_to_json(signal))
        assert "3 active veto" in text
        assert "Hold or Sell" in text

    def test_aggressive_blocked_when_cannot_trade(self):
        signal = _sample_signal(
            can_trade=False,
            action="回避",
            position_cap=0.0,
            veto_reasons=["冰点确认"],
        )
        text = build_aggressive_gate_instruction(hard_signal_to_json(signal))
        assert "can_trade=False" in text
        assert "MUST NOT" in text

    def test_short_term_coverage_detects_missing_strategy(self):
        report = "市场情绪处于修复阶段，梯队健康。"
        issues = check_short_term_report_coverage(report)
        assert any("策略" in item for item in issues)

    def test_consistency_flags_score_drift(self):
        signal = _sample_signal(emotion_score=58, second_board_score=72)
        report = (
            "情绪阶段：修复。情绪分：80。二板预期分：40。策略建议：首板打板。"
        )
        issues = check_hard_signal_report_consistency(
            report, hard_signal_to_json(signal),
        )
        assert any("情绪分偏差" in item for item in issues)
        assert any("二板预期分偏差" in item for item in issues)


@pytest.mark.unit
class TestQualityGateHardLogic:
    def test_quality_gate_downgrades_short_term_on_consistency_issues(self):
        signal = _sample_signal(emotion_score=58, second_board_score=72)
        short_report = (
            "| 指标 | 值 |\n| --- | --- |\n"
            "情绪升温，情绪分90，二板预期分30，建议观望。"
            + ("x" * 200)
        )
        state = {
            "trade_date": "2026-06-16",
            "company_of_interest": "000001",
            "market_report": "x" * 250,
            "sentiment_report": "x" * 250,
            "news_report": "x" * 250,
            "fundamentals_report": "x" * 250,
            "policy_report": "x" * 250,
            "hot_money_report": "x" * 250,
            "lockup_report": "x" * 250,
            "short_term_report": short_report,
            "hard_signal": hard_signal_to_json(signal),
        }
        gate = create_quality_gate(llm=MagicMock())
        result = gate(state)
        summary = result["data_quality_summary"]
        assert "硬逻辑一致性检查" in summary
        assert "短线博弈分析师: [C]" in summary
