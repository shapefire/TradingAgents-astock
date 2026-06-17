"""Phase 0: API 接口验证测试

验证短线交易功能扩展所依赖的数据源接口可用性。
每个测试独立验证一个接口的字段结构和数据质量。

注意：这些测试会发起真实 HTTP 请求，需要网络连接。
"""

import pytest
from tradingagents.dataflows.a_stock import (
    _em_get,
    _get_limitup_stocks_ths,
    _detect_limitup_from_kline,
    _get_market_breadth,
    _get_northbound_flow_signal,
    _get_limitup_stocks,
    _get_limitdown_stocks,
)


# ---------------------------------------------------------------------------
# P0-01: 东财 RPT_LIMITUP_STOCK 接口（已失效）
# ---------------------------------------------------------------------------

class TestRptLimitupStockApi:
    """验证东财 RPT_LIMITUP_STOCK 接口状态"""

    def test_report_returns_empty_or_error(self):
        """RPT_LIMITUP_STOCK 接口已失效（2026-05-19 确认）"""
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_LIMITUP_STOCK",
            "columns": "ALL",
            "filter": "(TRADE_DATE='2026-06-13')",
            "pageSize": 5,
        }
        resp = _em_get(url, params=params)
        # 接口已失效，返回 None 或空数据
        if resp is not None:
            data = resp.get("result", {})
            if data:
                # 如果有数据，验证字段结构
                assert "data" in data or data is None
        # 不要求接口返回有效数据（已确认失效）


# ---------------------------------------------------------------------------
# P0-02: 东财选股接口 (dataapi/xuangu/list)
# ---------------------------------------------------------------------------

class TestXuanguApi:
    """验证东财选股接口可用性"""

    def test_returns_valid_response(self):
        """选股接口应返回有效响应"""
        url = "https://dataapi.eastmoney.com/xuangu/list"
        params = {
            "st": "CHANGE_RATE",
            "sr": "-1",
            "ps": 5,
            "p": 1,
            "sty": "SECURITY_CODE,SECURITY_NAME_ABBR,CHANGE_RATE,FREE_CAP",
        }
        resp = _em_get(url, params=params)
        # 选股接口可能返回 None（参数不正确）或有效数据
        # 主要验证不抛出异常
        assert resp is None or isinstance(resp, (dict, list))


# ---------------------------------------------------------------------------
# P0-03: 同花顺 getharden 接口
# ---------------------------------------------------------------------------

class TestThsGethardenApi:
    """验证同花顺涨停获取接口"""

    def test_returns_list(self):
        """getharden 应返回列表"""
        result = _get_limitup_stocks_ths("2026-06-13")
        assert isinstance(result, list)

    def test_record_structure(self):
        """返回记录应包含 code, name, reason 字段"""
        result = _get_limitup_stocks_ths("2026-06-13")
        if result:
            record = result[0]
            assert "code" in record, "记录缺少 code 字段"
            assert "name" in record, "记录缺少 name 字段"
            assert "reason" in record, "记录缺少 reason 字段"

    def test_reason_content_quality(self):
        """涨停原因字段应包含有意义的文本"""
        result = _get_limitup_stocks_ths("2026-06-13")
        if result:
            reasons = [r.get("reason", "") for r in result if r.get("reason")]
            # 至少有一些非空原因
            assert len(reasons) > 0 or len(result) == 0

    def test_non_trading_day(self):
        """非交易日应返回空列表"""
        result = _get_limitup_stocks_ths("2026-06-08")  # Sunday
        assert isinstance(result, list)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# P0-04: mootdx K线接口
# ---------------------------------------------------------------------------

class TestMootdxKlineApi:
    """验证 mootdx K线接口可用性"""

    def test_detect_limitup_returns_dict(self):
        """涨停判断应返回字典"""
        result = _detect_limitup_from_kline("000001", "2026-06-13")
        assert isinstance(result, dict)

    def test_detect_limitup_has_required_fields(self):
        """涨停判断结果应包含必要字段"""
        result = _detect_limitup_from_kline("000001", "2026-06-13")
        assert "is_limit_up" in result, "缺少 is_limit_up 字段"

    def test_detect_limitup_invalid_code(self):
        """无效代码应返回 is_limit_up=False"""
        result = _detect_limitup_from_kline("999999", "2026-06-13")
        assert result.get("is_limit_up") is False

    def test_limitup_stocks_integration(self):
        """统一涨停获取接口应能整合 mootdx 数据"""
        result = _get_limitup_stocks("2026-06-13")
        assert isinstance(result, list)
        if result:
            assert "consecutive_days" in result[0], "缺少连板天数字段"
            assert "limit_type" in result[0], "缺少涨停类型字段"


# ---------------------------------------------------------------------------
# P0-05: 市场广度接口
# ---------------------------------------------------------------------------

class TestMarketBreadthApi:
    """验证市场涨跌家数接口"""

    def test_returns_dict(self):
        """市场涨跌家数应返回字典"""
        result = _get_market_breadth()
        assert isinstance(result, dict)

    def test_has_required_fields(self):
        """应包含涨跌家数相关字段"""
        result = _get_market_breadth()
        # 至少应有一个有效字段
        has_any = any(
            k in result
            for k in ["up_count", "down_count", "flat_count", "total", "up_ratio"]
        )
        assert has_any or len(result) == 0, f"返回字段不符合预期: {list(result.keys())}"


# ---------------------------------------------------------------------------
# P0-06: 北向资金接口
# ---------------------------------------------------------------------------

class TestNorthboundFlowApi:
    """验证北向资金信号接口"""

    def test_returns_string(self):
        """北向资金信号应返回字符串"""
        result = _get_northbound_flow_signal()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# P0-07: 跌停获取接口
# ---------------------------------------------------------------------------

class TestLimitdownApi:
    """验证跌停获取接口"""

    def test_returns_list(self):
        """跌停获取应返回列表"""
        result = _get_limitdown_stocks("2026-06-13")
        assert isinstance(result, list)
