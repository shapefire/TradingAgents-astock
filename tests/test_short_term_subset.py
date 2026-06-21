"""Tests for short-term analyst subset mode (R5)."""

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.quality_gate import create_quality_gate
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import (
    ALL_ANALYST_KEYS,
    resolve_analyst_selection,
)
from tradingagents.logic.trading_hard_logic import HardSignal, hard_signal_to_json


class TestResolveAnalystSelection:
    def test_subset_when_short_term_mode(self):
        config = {
            "short_term_mode": True,
            "short_term_analyst_subset": ["short_term", "market", "policy", "hot_money"],
        }
        result = resolve_analyst_selection(ALL_ANALYST_KEYS, config)
        assert result == ["short_term", "market", "policy", "hot_money"]

    def test_full_list_when_mode_off(self):
        config = {"short_term_mode": False}
        result = resolve_analyst_selection(ALL_ANALYST_KEYS[:4], config)
        assert result == ALL_ANALYST_KEYS[:4]

    def test_empty_subset_falls_back_to_selected(self):
        config = {"short_term_mode": True, "short_term_analyst_subset": []}
        result = resolve_analyst_selection(["market", "news"], config)
        assert result == ["market", "news"]


class TestGraphAnalystSubset:
    def test_setup_graph_subset_node_count(self):
        from langgraph.prebuilt import ToolNode

        from tradingagents.graph.conditional_logic import ConditionalLogic
        from tradingagents.graph.setup import GraphSetup

        cl = ConditionalLogic(short_term_mode=True)
        tool_nodes = {
            key: ToolNode([])
            for key in ("short_term", "hot_money", "policy", "market")
        }
        setup = GraphSetup(
            MagicMock(),
            MagicMock(),
            tool_nodes,
            cl,
            skip_quality_gate_llm=True,
        )
        subset = ["short_term", "hot_money", "policy", "market"]
        workflow = setup.setup_graph(subset)
        analyst_nodes = [
            name for name in workflow.nodes
            if name in {f"{key.capitalize()} Analyst" for key in subset}
        ]
        assert len(analyst_nodes) == 4
        assert "Short_term Analyst" in workflow.nodes
        assert "Fundamentals Analyst" not in workflow.nodes


class TestQualityGateSkipLlm:
    def test_skip_llm_review_in_short_term_mode(self):
        signal = HardSignal(
            ticker="000001",
            trade_date="2026-06-16",
            emotion_phase="修复",
            can_trade=True,
            role="首板候选",
            theme_rank=2,
        )
        short_report = (
            "| 指标 | 值 |\n| --- | --- |\n"
            "情绪修复，策略首板打板，情绪分58，二板预期72。"
            + ("x" * 200)
        )
        state = {
            "trade_date": "2026-06-16",
            "company_of_interest": "000001",
            "short_term_report": short_report,
            "hard_signal": hard_signal_to_json(signal),
        }
        llm = MagicMock()
        gate = create_quality_gate(
            llm,
            skip_llm_review=True,
            active_analysts=["short_term"],
        )
        result = gate(state)
        summary = result["data_quality_summary"]
        assert "跳过 LLM 复审" in summary
        llm.invoke.assert_not_called()
        assert "短线博弈分析师" in summary
        assert "技术分析师" not in summary
