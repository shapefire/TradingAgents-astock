"""Integration tests for hard logic wiring (no network)."""

import inspect
from unittest.mock import patch


class TestLeaderIdentificationToolParams:
    def test_leader_identification_has_ticker_param(self):
        from tradingagents.agents.utils.signal_data_tools import get_leader_identification

        fields = get_leader_identification.args_schema.model_fields
        assert "ticker" in fields
        assert "trade_date" in fields

    @patch("tradingagents.agents.utils.signal_data_tools.route_to_vendor")
    def test_leader_identification_routes_ticker_first(self, mock_route):
        from tradingagents.agents.utils.signal_data_tools import get_leader_identification

        mock_route.return_value = "ok"
        get_leader_identification.invoke({
            "ticker": "000001",
            "trade_date": "2026-06-16",
            "theme": "",
        })
        mock_route.assert_called_once_with(
            "get_leader_identification", "000001", "2026-06-16", ""
        )


class TestDecisionChainIncludesShortTerm:
    def test_bull_researcher_includes_short_term(self):
        from tradingagents.agents.researchers import bull_researcher

        source = inspect.getsource(bull_researcher.create_bull_researcher)
        assert "short_term_report" in source
        assert "hard_signal_summary" in source

    def test_bear_researcher_includes_veto_instruction(self):
        from tradingagents.agents.researchers import bear_researcher

        source = inspect.getsource(bear_researcher.create_bear_researcher)
        assert "build_bear_veto_instruction" in source
        assert "short_term_report" in source

    def test_aggressive_debator_includes_hard_signal(self):
        from tradingagents.agents.risk_mgmt import aggressive_debator

        source = inspect.getsource(aggressive_debator.create_aggressive_debator)
        assert "hard_signal_summary" in source
        assert "build_aggressive_gate_instruction" in source

    def test_research_plan_has_time_horizon(self):
        from tradingagents.agents.schemas import ResearchPlan

        fields = ResearchPlan.model_fields
        assert "time_horizon" in fields

    def test_trader_includes_short_term(self):
        from tradingagents.agents.trader import trader

        source = inspect.getsource(trader.create_trader)
        assert "short_term_report" in source
        assert "hard_signal_summary" in source

    def test_portfolio_manager_includes_hard_signal(self):
        from tradingagents.agents.managers import portfolio_manager

        source = inspect.getsource(portfolio_manager.create_portfolio_manager)
        assert "hard_signal_summary" in source

    def test_quality_gate_includes_short_term(self):
        from tradingagents.agents import quality_gate

        assert "short_term" in quality_gate.REPORT_FIELDS
        assert "short_term" in quality_gate.ANALYST_NAMES

    def test_agent_state_has_hard_signal_fields(self):
        from typing import get_type_hints

        from tradingagents.agents.utils.agent_states import AgentState

        hints = get_type_hints(AgentState)
        assert "hard_signal" in hints
        assert "hard_signal_summary" in hints

    def test_trading_graph_injects_hard_signal(self):
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        source = inspect.getsource(TradingAgentsGraph._run_graph)
        assert "evaluate_hard_signal" in source or "hard_signal" in source
        assert "hard_signal_summary" in source

    def test_log_state_includes_hard_signal(self):
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        source = inspect.getsource(TradingAgentsGraph._log_state)
        assert "hard_signal" in source

    def test_prefetch_leader_passes_ticker(self):
        from tradingagents.dataflows import prefetch

        leader_task = next(
            t for t in prefetch._PREFETCH_TASKS if t[0] == "get_leader_identification"
        )
        _, _, kwargs = leader_task
        assert kwargs.get("ticker") == "{ticker}"
