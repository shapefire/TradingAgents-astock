"""短线交易功能 - 集成测试 (P8-31, P8-32)

测试 Agent 工具注册、路由、图配置等组件间的集成关系。
这些测试不发起真实 API 请求，只验证组件装配正确性。
"""

import pytest
from typing import get_type_hints
from unittest.mock import MagicMock, patch

from langchain_core.runnables import RunnableLambda
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.dataflows.interface import (
    VENDOR_METHODS,
    TOOLS_CATEGORIES,
    route_to_vendor,
)


def _make_mock_llm(response_content="", tool_calls=None):
    """Create a mock LLM whose bind_tools returns a RunnableLambda wrapper."""
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.tool_calls = tool_calls or []
    mock_response.content = response_content
    # Wrap in RunnableLambda so prompt | bind_tools(...) produces a valid RunnableSequence
    mock_llm.bind_tools.return_value = RunnableLambda(lambda x: mock_response)
    return mock_llm


# ---------------------------------------------------------------------------
# P8-32a: 工具注册验证
# ---------------------------------------------------------------------------

class TestToolRegistration:
    """验证 5 个短线工具在 VENDOR_METHODS 和 TOOLS_CATEGORIES 中正确注册"""

    EXPECTED_TOOLS = [
        "get_consecutive_limit_stats",
        "get_theme_heat",
        "get_first_board_screen",
        "get_high_board_status",
        "get_leader_identification",
    ]

    def test_all_tools_in_vendor_methods(self):
        """所有短线工具应注册到 VENDOR_METHODS"""
        for tool_name in self.EXPECTED_TOOLS:
            assert tool_name in VENDOR_METHODS, f"{tool_name} 未注册到 VENDOR_METHODS"

    def test_all_vendor_methods_are_a_stock_only(self):
        """短线工具应仅支持 a_stock vendor"""
        for tool_name in self.EXPECTED_TOOLS:
            vendors = list(VENDOR_METHODS[tool_name].keys())
            assert vendors == ["a_stock"], (
                f"{tool_name} 的 vendor 列表应为 ['a_stock']，实际为 {vendors}"
            )

    def test_all_tools_in_short_term_category(self):
        """所有短线工具应归入 short_term_data 分类"""
        category_tools = TOOLS_CATEGORIES["short_term_data"]["tools"]
        for tool_name in self.EXPECTED_TOOLS:
            assert tool_name in category_tools, f"{tool_name} 未在 short_term_data 分类中"

    def test_short_term_category_description(self):
        """short_term_data 分类应有描述"""
        desc = TOOLS_CATEGORIES["short_term_data"]["description"]
        assert isinstance(desc, str)
        assert len(desc) > 0


# ---------------------------------------------------------------------------
# P8-32b: AgentState 字段验证
# ---------------------------------------------------------------------------

class TestAgentStateField:
    """验证 AgentState 包含 short_term_report 字段"""

    def test_short_term_report_in_type_hints(self):
        """AgentState 应有 short_term_report 类型注解"""
        hints = get_type_hints(AgentState)
        assert "short_term_report" in hints, "AgentState 缺少 short_term_report 字段"

    def test_short_term_report_is_str(self):
        """short_term_report 应为 str 类型"""
        hints = get_type_hints(AgentState)
        assert hints["short_term_report"] is str, (
            f"short_term_report 类型应为 str，实际为 {hints['short_term_report']}"
        )


# ---------------------------------------------------------------------------
# P8-32c: Agent 工厂函数验证
# ---------------------------------------------------------------------------

class TestShortTermAnalystFactory:
    """验证 short_term_analyst 工厂函数的装配逻辑"""

    def test_factory_importable(self):
        """create_short_term_analyst 应可从 agents 包导入"""
        from tradingagents.agents import create_short_term_analyst
        assert callable(create_short_term_analyst)

    def test_factory_returns_callable(self):
        """工厂函数应返回可调用的 node 函数"""
        from tradingagents.agents import create_short_term_analyst
        mock_llm = MagicMock()
        node = create_short_term_analyst(mock_llm)
        assert callable(node)

    def test_node_binds_correct_tools(self):
        """node 函数应使用 7 个工具（2 共享 + 5 短线）"""
        from tradingagents.agents import create_short_term_analyst
        mock_llm = _make_mock_llm()
        node = create_short_term_analyst(mock_llm)
        state = {
            "trade_date": "2026-06-13",
            "company_of_interest": "000001.SZ",
            "messages": [],
        }
        node(state)
        # 验证 bind_tools 被调用，且传入 7 个工具
        mock_llm.bind_tools.assert_called_once()
        tools_arg = mock_llm.bind_tools.call_args[0][0]
        assert len(tools_arg) == 7, f"应绑定 7 个工具，实际 {len(tools_arg)}"

    def test_node_returns_short_term_report(self):
        """node 函数返回值应包含 short_term_report 键"""
        from tradingagents.agents.analysts.short_term_analyst import create_short_term_analyst
        mock_llm = _make_mock_llm(response_content="测试报告")

        node = create_short_term_analyst(mock_llm)
        state = {
            "trade_date": "2026-06-13",
            "company_of_interest": "000001.SZ",
            "messages": [],
        }
        result = node(state)
        assert "short_term_report" in result
        assert result["short_term_report"] == "测试报告"

    def test_node_returns_messages(self):
        """node 函数返回值应包含 messages 键"""
        from tradingagents.agents.analysts.short_term_analyst import create_short_term_analyst
        mock_llm = _make_mock_llm(response_content="测试")

        node = create_short_term_analyst(mock_llm)
        state = {
            "trade_date": "2026-06-13",
            "company_of_interest": "000001.SZ",
            "messages": [],
        }
        result = node(state)
        assert "messages" in result
        assert len(result["messages"]) == 1


# ---------------------------------------------------------------------------
# P8-32d: 条件路由验证
# ---------------------------------------------------------------------------

class TestConditionalLogic:
    """验证 ConditionalLogic 的短线路由方法"""

    def test_should_continue_short_term_exists(self):
        """ConditionalLogic 应有 should_continue_short_term 方法"""
        from tradingagents.graph.conditional_logic import ConditionalLogic
        cl = ConditionalLogic()
        assert hasattr(cl, "should_continue_short_term")
        assert callable(cl.should_continue_short_term)

    def test_routes_to_tools_on_tool_calls(self):
        """有 tool_calls 时应路由到 tools_short_term"""
        from tradingagents.graph.conditional_logic import ConditionalLogic
        cl = ConditionalLogic()
        mock_msg = MagicMock()
        mock_msg.tool_calls = [{"name": "get_theme_heat"}]
        state = {"messages": [mock_msg]}
        result = cl.should_continue_short_term(state)
        assert result == "tools_short_term"

    def test_routes_to_cleanup_on_no_tool_calls(self):
        """无 tool_calls 时应路由到 Msg Clear Short_term"""
        from tradingagents.graph.conditional_logic import ConditionalLogic
        cl = ConditionalLogic()
        mock_msg = MagicMock()
        mock_msg.tool_calls = []
        state = {"messages": [mock_msg]}
        result = cl.should_continue_short_term(state)
        assert result == "Msg Clear Short_term"


# ---------------------------------------------------------------------------
# P8-32e: 图配置验证
# ---------------------------------------------------------------------------

class TestGraphSetup:
    """验证 GraphSetup 包含 short_term analyst 配置"""

    def test_short_term_in_default_analysts(self):
        """默认分析师列表应包含 short_term"""
        from tradingagents.graph.setup import GraphSetup
        # 读取源码中的默认值
        import inspect
        source = inspect.getsource(GraphSetup.setup_graph)
        assert "short_term" in source, "setup_graph 源码中未找到 short_term"

    def test_tool_node_names(self):
        """应为短线工具创建 tools_short_term 节点"""
        from tradingagents.graph.conditional_logic import ConditionalLogic
        cl = ConditionalLogic()
        # 验证路由目标名称
        mock_msg = MagicMock()
        mock_msg.tool_calls = [{"name": "test"}]
        result = cl.should_continue_short_term({"messages": [mock_msg]})
        assert result == "tools_short_term"


# ---------------------------------------------------------------------------
# P8-32f: signal_data_tools 函数签名验证
# ---------------------------------------------------------------------------

class TestSignalDataToolsSignatures:
    """验证 signal_data_tools 中短线工具的 StructuredTool 参数"""

    def test_consecutive_limit_stats_has_trade_date(self):
        """get_consecutive_limit_stats 应接受 trade_date 参数"""
        from tradingagents.agents.utils.signal_data_tools import get_consecutive_limit_stats
        fields = get_consecutive_limit_stats.args_schema.model_fields
        assert "trade_date" in fields

    def test_theme_heat_has_trade_date(self):
        """get_theme_heat 应接受 trade_date 参数"""
        from tradingagents.agents.utils.signal_data_tools import get_theme_heat
        fields = get_theme_heat.args_schema.model_fields
        assert "trade_date" in fields

    def test_theme_heat_has_top_n_param(self):
        """get_theme_heat 应接受 top_n 参数"""
        from tradingagents.agents.utils.signal_data_tools import get_theme_heat
        fields = get_theme_heat.args_schema.model_fields
        assert "top_n" in fields

    def test_first_board_screen_has_min_score_param(self):
        """get_first_board_screen 应接受 trade_date 与 min_score 参数"""
        from tradingagents.agents.utils.signal_data_tools import get_first_board_screen
        fields = get_first_board_screen.args_schema.model_fields
        assert "trade_date" in fields
        assert "min_score" in fields

    def test_high_board_status_has_trade_date(self):
        """get_high_board_status 应接受 trade_date 参数"""
        from tradingagents.agents.utils.signal_data_tools import get_high_board_status
        fields = get_high_board_status.args_schema.model_fields
        assert "trade_date" in fields

    def test_leader_identification_has_both_params(self):
        """get_leader_identification 应接受 ticker, trade_date 和 theme 参数"""
        from tradingagents.agents.utils.signal_data_tools import get_leader_identification
        fields = get_leader_identification.args_schema.model_fields
        assert "ticker" in fields
        assert "trade_date" in fields
        assert "theme" in fields


# ---------------------------------------------------------------------------
# P8-32g: _log_state 验证
# ---------------------------------------------------------------------------

class TestLogStateIncludesShortTermReport:
    """验证 _log_state 包含 short_term_report"""

    def test_log_state_source_includes_short_term_report(self):
        """_log_state 源码应包含 short_term_report"""
        import inspect
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        source = inspect.getsource(TradingAgentsGraph._log_state)
        assert "short_term_report" in source, (
            "_log_state 未记录 short_term_report 字段"
        )
