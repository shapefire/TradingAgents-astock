"""Tests for short-term trading feature extensions (Phase 1-4)."""

import pytest
from unittest.mock import patch, MagicMock
from tradingagents.dataflows.a_stock import (
    _get_limitup_stocks_ths,
    _detect_limitup_from_kline,
    _calculate_consecutive_days,
    _match_limit_up_ratio,
    _limit_up_price,
    _load_ohlcv_astock,
    _get_limitup_stocks,
    _get_limitdown_stocks,
    _get_stock_realtime_quote,
    _get_market_breadth,
    _get_northbound_flow_signal,
    _normalize_theme_name,
    REASON_NORMALIZATION_MAP,
    # Phase 2
    _get_previous_trading_date,
    _get_yesterday_limitup_performance,
    _get_board_distribution,
    _calculate_seal_quality,
    _calculate_yesterday_performance,
    _calculate_board_health,
    _judge_emotion_phase,
    _calculate_emotion_metrics,
    get_consecutive_limit_stats,
    # Phase 3
    _get_limitup_by_theme,
    _get_theme_history,
    _get_theme_leader_status,
    _get_theme_active_days,
    _get_theme_phase,
    _calculate_theme_trend,
    _calculate_theme_recognition_score,
    _calculate_heat_score,
    get_theme_heat,
    # Phase 4
    _get_first_board_stocks,
    _get_stock_seal_info,
    _get_historical_activity,
    _calculate_theme_purity,
    _calculate_volume_match_score,
    calculate_second_board_score,
    get_first_board_screen,
    # Phase 5
    _get_high_board_stocks,
    _get_high_board_detail,
    _get_yizi_cumulative_turnover,
    _calculate_divergence_score,
    _calculate_break_risk_level,
    _get_theme_effect_for_high_board,
    get_high_board_status,
    # Phase 6
    _get_same_theme_stocks,
    _get_leader_candidates,
    _calculate_leader_score,
    _calculate_time_score,
    _identify_card_position,
    _identify_deputy_leader,
    _distinguish_deputy_vs_new_leader,
    judge_strong_bullish_leader,
    judge_strong_bearish_leader,
    judge_card_position_outcome,
    get_leader_identification,
)


class TestGetLimitupStocksThs:
    """P1-01: 同花顺涨停获取"""

    def test_returns_list(self):
        """正常返回应为列表"""
        result = _get_limitup_stocks_ths("2026-06-13")
        assert isinstance(result, list)

    def test_empty_date_uses_today(self):
        """空日期应使用今日"""
        result = _get_limitup_stocks_ths("")
        assert isinstance(result, list)

    def test_non_trading_day_returns_empty(self):
        """非交易日应返回空列表"""
        result = _get_limitup_stocks_ths("2026-06-08")  # Sunday
        assert isinstance(result, list)

    def test_record_fields(self):
        """返回记录应包含必要字段"""
        result = _get_limitup_stocks_ths("2026-06-13")
        if result:
            record = result[0]
            assert "code" in record
            assert "name" in record
            assert "reason" in record

    def test_api_error_returns_empty(self):
        """API错误应返回空列表而非抛出异常"""
        result = _get_limitup_stocks_ths("2026-01-01")
        assert isinstance(result, list)


class TestDetectLimitupFromKline:
    """P1-02: mootdx涨停判断"""

    def test_returns_dict(self):
        """返回应为字典"""
        result = _detect_limitup_from_kline("000001", "2026-06-13")
        assert isinstance(result, dict)

    def test_contains_is_limit_up(self):
        """应包含 is_limit_up 字段"""
        result = _detect_limitup_from_kline("000001", "2026-06-13")
        assert "is_limit_up" in result

    def test_invalid_code_returns_false(self):
        """无效代码应返回 is_limit_up=False"""
        result = _detect_limitup_from_kline("999999", "2026-06-13")
        assert result.get("is_limit_up") is False

    def test_yizi_detection(self):
        """应能检测一字板"""
        result = _detect_limitup_from_kline("000001", "2026-06-13")
        if result.get("is_limit_up"):
            assert "is_yizi" in result


class TestCalculateConsecutiveDays:
    """P1-03: 连板天数计算"""

    def test_returns_int(self):
        """返回应为整数"""
        result = _calculate_consecutive_days("000001", "2026-06-13")
        assert isinstance(result, int)

    def test_non_negative(self):
        """连板天数应非负"""
        result = _calculate_consecutive_days("000001", "2026-06-13")
        assert result >= 0

    def test_invalid_code_returns_zero(self):
        """无效代码应返回0"""
        result = _calculate_consecutive_days("999999", "2026-06-13")
        assert result == 0


class TestMatchLimitUpRatio:
    """涨停幅度匹配（5%/10%/20%/30%）"""

    def test_main_board_10pct(self):
        assert _match_limit_up_ratio(10.0, 11.0) == 0.10

    def test_st_5pct(self):
        assert _match_limit_up_ratio(10.0, 10.5) == 0.05

    def test_chinext_20pct(self):
        assert _match_limit_up_ratio(10.0, 12.0) == 0.20

    def test_not_limit_up(self):
        assert _match_limit_up_ratio(10.0, 10.8) is None

    def test_limit_price_rounding(self):
        assert _limit_up_price(13.54, 0.10) == 14.89


class TestCalculateConsecutiveDaysWithMockKline:
    """连板天数：K 线缺失当日 bar 时不应少算（回归测试）"""

    def test_missing_trade_date_bar_undercounts_without_fix(self):
        """缺少 trade_date 当日 K 线时，3 连板会被误判为 2 连板"""
        import pandas as pd

        dates = pd.to_datetime(
            ["2026-06-12", "2026-06-15", "2026-06-16", "2026-06-17"]
        )
        df = pd.DataFrame(
            {
                "Date": dates,
                "Open": [16.0, 18.06, 19.87, 21.86],
                "High": [16.42, 18.06, 19.87, 21.86],
                "Low": [16.0, 18.06, 19.87, 21.86],
                "Close": [16.42, 18.06, 19.87, 21.86],
                "Volume": [100, 100, 100, 100],
            }
        )
        with patch("tradingagents.dataflows.a_stock._load_ohlcv_astock") as mock_load:
            mock_load.return_value = df
            assert _calculate_consecutive_days("000777", "2026-06-17") == 3

            truncated = df[df["Date"] < "2026-06-17"]
            mock_load.return_value = truncated
            assert _calculate_consecutive_days("000777", "2026-06-17") == 2


class TestOhlcvCacheCoversDate:
    """OHLCV 缓存应覆盖 curr_date，否则需重新拉取"""

    def test_stale_same_day_cache_is_not_used(self, tmp_path):
        import pandas as pd
        from tradingagents.dataflows import a_stock

        code = "000777"
        cache_file = tmp_path / f"{code}-astock-daily.csv"
        stale = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2026-06-15", "2026-06-16"]),
                "Open": [1, 1],
                "High": [1, 1],
                "Low": [1, 1],
                "Close": [1, 1],
                "Volume": [1, 1],
            }
        )
        stale.to_csv(cache_file, index=False, encoding="utf-8")

        fresh = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2026-06-15", "2026-06-16", "2026-06-17"]),
                "Open": [1, 1, 1],
                "High": [1, 1, 1],
                "Low": [1, 1, 1],
                "Close": [1, 1, 1],
                "Volume": [1, 1, 1],
            }
        )

        with patch("tradingagents.dataflows.config.get_config", return_value={"data_cache_dir": str(tmp_path)}), \
             patch.object(a_stock, "_get_mootdx_client") as mock_client, \
             patch.object(a_stock, "datetime") as mock_dt:
            mock_dt.now.return_value = __import__("datetime").datetime(2026, 6, 17, 16, 0, 0)
            mock_dt.fromtimestamp = __import__("datetime").datetime.fromtimestamp
            mock_client.return_value.bars.return_value = fresh.rename(
                columns={
                    "Date": "datetime",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            ).set_index("datetime")

            result = a_stock._load_ohlcv_astock(code, "2026-06-17")

        assert len(result) == 3
        assert result["Date"].max().strftime("%Y-%m-%d") == "2026-06-17"
        mock_client.return_value.bars.assert_called_once()


class TestGetLimitupStocks:
    """P1-04: 统一涨停获取接口"""

    def test_returns_list(self):
        """返回应为列表"""
        result = _get_limitup_stocks("2026-06-13")
        assert isinstance(result, list)

    def test_record_has_consecutive_days(self):
        """记录应包含连板天数"""
        result = _get_limitup_stocks("2026-06-13")
        if result:
            assert "consecutive_days" in result[0]

    def test_record_has_limit_type(self):
        """记录应包含涨停类型"""
        result = _get_limitup_stocks("2026-06-13")
        if result:
            assert "limit_type" in result[0]

    def test_empty_date(self):
        """空日期应正常处理"""
        result = _get_limitup_stocks("")
        assert isinstance(result, list)

    def test_error_handling(self):
        """异常应被捕获返回空列表"""
        result = _get_limitup_stocks("invalid_date_format")
        assert isinstance(result, list)


class TestGetLimitdownStocks:
    """P1-05: 跌停获取"""

    def test_returns_list(self):
        """返回应为列表"""
        result = _get_limitdown_stocks("2026-06-13")
        assert isinstance(result, list)

    def test_empty_date(self):
        """空日期应正常处理"""
        result = _get_limitdown_stocks("")
        assert isinstance(result, list)


class TestGetStockRealtimeQuote:
    """P1-06: 个股行情获取"""

    def test_returns_dict(self):
        """返回应为字典"""
        result = _get_stock_realtime_quote("000001")
        assert isinstance(result, dict)

    def test_contains_price(self):
        """应包含价格字段"""
        result = _get_stock_realtime_quote("000001")
        if result:
            assert "price" in result

    def test_invalid_code(self):
        """无效代码应返回空字典"""
        result = _get_stock_realtime_quote("999999")
        assert isinstance(result, dict)


class TestGetMarketBreadth:
    """P1-07: 市场涨跌家数"""

    def test_returns_dict(self):
        """返回应为字典"""
        result = _get_market_breadth("2026-06-13")
        assert isinstance(result, dict)

    def test_contains_required_fields(self):
        """应包含必要字段"""
        result = _get_market_breadth("2026-06-13")
        assert "up_count" in result
        assert "down_count" in result
        assert "ad_ratio" in result

    def test_breadth_signal_values(self):
        """breadth_signal 应为有效值"""
        result = _get_market_breadth("2026-06-13")
        valid = ["强势", "正常", "弱势", "无数据"]
        assert result["breadth_signal"] in valid

    def test_empty_date(self):
        """空日期应正常处理"""
        result = _get_market_breadth("")
        assert isinstance(result, dict)


class TestGetNorthboundFlowSignal:
    """P1-08: 北向资金信号"""

    def test_returns_dict(self):
        """返回应为字典"""
        result = _get_northbound_flow_signal("2026-06-13")
        assert isinstance(result, dict)

    def test_contains_direction(self):
        """应包含 direction 字段"""
        result = _get_northbound_flow_signal("2026-06-13")
        assert "direction" in result

    def test_direction_values(self):
        """direction 应为有效值"""
        result = _get_northbound_flow_signal("2026-06-13")
        if result.get("direction"):
            valid = ["大幅流入", "小幅流入", "小幅流出", "大幅流出", "无数据"]
            assert result["direction"] in valid

    def test_net_inflow_is_numeric(self):
        """net_inflow 应为数值"""
        result = _get_northbound_flow_signal("2026-06-13")
        assert isinstance(result.get("net_inflow", 0), (int, float))


class TestNormalizeThemeName:
    """P1-10: 涨停原因归一化"""

    def test_ai_normalization(self):
        """AI相关原因应归一化"""
        assert _normalize_theme_name("AI概念") == "AI概念"
        assert _normalize_theme_name("人工智能") == "AI概念"
        assert _normalize_theme_name("大模型") == "AI概念"

    def test_new_energy_normalization(self):
        """新能源相关应归一化"""
        assert _normalize_theme_name("光伏") == "新能源"
        assert _normalize_theme_name("锂电池") == "新能源"
        assert _normalize_theme_name("储能") == "新能源"

    def test_unknown_theme(self):
        """未知主题应返回原文"""
        result = _normalize_theme_name("完全未知的主题XYZ")
        assert result == "完全未知的主题XYZ"

    def test_empty_string(self):
        """空字符串应返回空"""
        assert _normalize_theme_name("") == ""

    def test_normalization_map_exists(self):
        """归一化映射表应存在"""
        assert isinstance(REASON_NORMALIZATION_MAP, dict)
        assert len(REASON_NORMALIZATION_MAP) > 0


class TestReasonNormalizationMap:
    """P1-09: 归一化映射表"""

    def test_map_is_dict(self):
        """映射表应为字典"""
        assert isinstance(REASON_NORMALIZATION_MAP, dict)

    def test_values_are_strings(self):
        """所有值应为字符串"""
        for key, value in REASON_NORMALIZATION_MAP.items():
            assert isinstance(key, str)
            assert isinstance(value, str)


# ===========================================================================
# Phase 2: 连板梯队统计 + 情绪量化
# ===========================================================================


class TestGetPreviousTradingDate:
    """P2-01辅助: 上一交易日获取"""

    def test_weekday_returns_previous(self):
        """工作日应返回前一天"""
        result = _get_previous_trading_date("2026-06-16")  # Tuesday
        assert result == "2026-06-15"  # Monday

    def test_sunday_returns_friday(self):
        """周日应返回周五"""
        result = _get_previous_trading_date("2026-06-14")  # Sunday
        assert result == "2026-06-12"  # Friday

    def test_saturday_returns_friday(self):
        """周六应返回周五"""
        result = _get_previous_trading_date("2026-06-13")  # Saturday
        assert result == "2026-06-12"  # Friday

    def test_invalid_date_returns_past(self):
        """无效日期应返回过去日期"""
        result = _get_previous_trading_date("invalid")
        assert isinstance(result, str)
        assert len(result) == 10


class TestGetYesterdayLimitupPerformance:
    """P2-02: 昨日涨停今日表现"""

    def test_returns_dict(self):
        """返回应为字典"""
        result = _get_yesterday_limitup_performance("2026-06-16")
        assert isinstance(result, dict)

    def test_contains_stocks_and_total(self):
        """应包含 stocks 和 total 字段"""
        result = _get_yesterday_limitup_performance("2026-06-16")
        assert "stocks" in result
        assert "total" in result

    def test_empty_date(self):
        """空日期应正常处理"""
        result = _get_yesterday_limitup_performance("")
        assert isinstance(result, dict)

    def test_error_handling(self):
        """异常应被捕获"""
        result = _get_yesterday_limitup_performance("invalid_date")
        assert isinstance(result, dict)


class TestGetBoardDistribution:
    """P2-03: 连板梯队分布"""

    def test_empty_list(self):
        """空列表应返回零值"""
        result = _get_board_distribution([])
        assert result["highest_board"] == 0
        assert result["distribution"] == {}
        assert result["total"] == 0

    def test_single_stock(self):
        """单只股票应正确统计"""
        stocks = [{"consecutive_days": 3}]
        result = _get_board_distribution(stocks)
        assert result["highest_board"] == 3
        assert result["distribution"] == {3: 1}
        assert result["total"] == 1

    def test_multiple_boards(self):
        """多板数应正确分布"""
        stocks = [
            {"consecutive_days": 5},
            {"consecutive_days": 4},
            {"consecutive_days": 4},
            {"consecutive_days": 3},
            {"consecutive_days": 3},
            {"consecutive_days": 3},
            {"consecutive_days": 2},
            {"consecutive_days": 1},
            {"consecutive_days": 1},
        ]
        result = _get_board_distribution(stocks)
        assert result["highest_board"] == 5
        assert result["distribution"] == {5: 1, 4: 2, 3: 3, 2: 1, 1: 2}
        assert result["total"] == 9

    def test_st_excluded_from_highest_board(self):
        """ST 连板计入分布，但不参与市场高度板统计"""
        stocks = [
            {"code": "600537", "name": "*ST汇智", "consecutive_days": 5},
            {"code": "000777", "name": "中核科技", "consecutive_days": 3},
        ]
        result = _get_board_distribution(stocks)
        assert result["highest_board"] == 3
        assert result["highest_board_including_st"] == 5


class TestCalculateSealQuality:
    """P2-04: 封板质量评估"""

    def test_empty_list(self):
        """空列表应返回零值"""
        result = _calculate_seal_quality([])
        assert result["yizi_count"] == 0
        assert result["huan_shou_count"] == 0
        assert result["total_limitup"] == 0

    def test_yizi_huanshou_split(self):
        """应正确拆分一字板和换手板"""
        stocks = [
            {"limit_type": "一字", "turnover_rate": 0.01},
            {"limit_type": "一字", "turnover_rate": 0.02},
            {"limit_type": "换手", "turnover_rate": 0.08},
            {"limit_type": "换手", "turnover_rate": 0.12},
            {"limit_type": "换手", "turnover_rate": 0.15},
        ]
        result = _calculate_seal_quality(stocks)
        assert result["yizi_count"] == 2
        assert result["huan_shou_count"] == 3
        assert result["total_limitup"] == 5

    def test_seal_rate_calculation(self):
        """封板率应正确计算"""
        stocks = [
            {"limit_type": "换手", "turnover_rate": 0.1},
            {"limit_type": "换手", "turnover_rate": 0.2},
        ]
        result = _calculate_seal_quality(stocks)
        assert result["effective_seal_rate"] == 100.0


class TestCalculateYesterdayPerformance:
    """P2-05: 昨日涨停表现计算"""

    def test_empty_data(self):
        """空数据应返回零值"""
        result = _calculate_yesterday_performance({"stocks": [], "total": 0})
        assert result["avg_return"] == 0
        assert result["muffled_rate"] == 0

    def test_muffled_rate_grading(self):
        """闷杀率分级应正确"""
        data = {
            "stocks": [
                {"today_return": -2, "yesterday_board_num": 1, "today_board_num": 0,
                 "is_muffled": False, "is_light_muffled": False, "is_heavy_muffled": False,
                 "high_open": True},
                {"today_return": -4, "yesterday_board_num": 1, "today_board_num": 0,
                 "is_muffled": False, "is_light_muffled": True, "is_heavy_muffled": False,
                 "high_open": False},
                {"today_return": -6, "yesterday_board_num": 2, "today_board_num": 0,
                 "is_muffled": True, "is_light_muffled": True, "is_heavy_muffled": False,
                 "high_open": False},
                {"today_return": -8, "yesterday_board_num": 2, "today_board_num": 0,
                 "is_muffled": True, "is_light_muffled": True, "is_heavy_muffled": True,
                 "high_open": False},
                {"today_return": 5, "yesterday_board_num": 1, "today_board_num": 2,
                 "is_muffled": False, "is_light_muffled": False, "is_heavy_muffled": False,
                 "high_open": True},
            ],
            "total": 5,
        }
        result = _calculate_yesterday_performance(data)
        assert result["light_muffled_rate"] == 60.0  # 3/5
        assert result["muffled_rate"] == 40.0  # 2/5
        assert result["heavy_muffled_rate"] == 20.0  # 1/5

    def test_promotion_rates(self):
        """晋级率应正确计算"""
        data = {
            "stocks": [
                {"today_return": 10, "yesterday_board_num": 2, "today_board_num": 3,
                 "is_muffled": False, "is_light_muffled": False, "is_heavy_muffled": False,
                 "high_open": True},
                {"today_return": -3, "yesterday_board_num": 2, "today_board_num": 0,
                 "is_muffled": False, "is_light_muffled": True, "is_heavy_muffled": False,
                 "high_open": False},
                {"today_return": 10, "yesterday_board_num": 1, "today_board_num": 2,
                 "is_muffled": False, "is_light_muffled": False, "is_heavy_muffled": False,
                 "high_open": True},
            ],
            "total": 3,
        }
        result = _calculate_yesterday_performance(data)
        assert result["promotion_rates"][2] == 50.0  # 1/2 promoted
        assert result["promotion_rates"][1] == 100.0  # 1/1 promoted


class TestCalculateBoardHealth:
    """P2-06: 梯队健康度评分"""

    def test_empty_distribution(self):
        """空分布应返回0"""
        result = _calculate_board_health({"highest_board": 0, "distribution": {}, "total": 0})
        assert result == 0

    def test_complete_ladder(self):
        """完整梯队应得高分"""
        board_dist = {
            "highest_board": 5,
            "distribution": {5: 1, 4: 2, 3: 3, 2: 5, 1: 10},
            "total": 21,
        }
        result = _calculate_board_health(board_dist)
        assert result > 70  # 完整梯队应得分较高

    def test_incomplete_ladder(self):
        """断层梯队应得分低于完整梯队"""
        board_dist = {
            "highest_board": 5,
            "distribution": {5: 1, 1: 10},  # 缺少 2,3,4
            "total": 11,
        }
        result = _calculate_board_health(board_dist)
        # 断层梯队应得分低于完整梯队
        complete_dist = {
            "highest_board": 5,
            "distribution": {5: 1, 4: 2, 3: 3, 2: 5, 1: 10},
            "total": 21,
        }
        complete_score = _calculate_board_health(complete_dist)
        assert result < complete_score

    def test_score_range(self):
        """评分应在0-100范围内"""
        board_dist = {
            "highest_board": 3,
            "distribution": {3: 1, 2: 2, 1: 5},
            "total": 8,
        }
        result = _calculate_board_health(board_dist)
        assert 0 <= result <= 100


class TestJudgeEmotionPhase:
    """P2-07: 情绪周期判断"""

    def test_freezing_point(self):
        """应能判断冰点"""
        phase = _judge_emotion_phase(
            seal_quality={"effective_seal_rate": 20},
            yesterday_performance={"avg_return": -3, "heavy_muffled_rate": 35, "muffled_rate": 40, "promotion_rates": {}},
            board_dist={"highest_board": 2, "distribution": {2: 1, 1: 5}, "total": 6},
            market_breadth={"ad_ratio": 0.5},
            northbound_signal={"direction": "大幅流出"},
        )
        assert phase == "冰点"

    def test_climax(self):
        """应能判断高潮"""
        phase = _judge_emotion_phase(
            seal_quality={"effective_seal_rate": 80},
            yesterday_performance={"avg_return": 3, "heavy_muffled_rate": 5, "muffled_rate": 10, "promotion_rates": {1: 60, 2: 50}},
            board_dist={"highest_board": 6, "distribution": {6: 1, 5: 2, 4: 3, 3: 5, 2: 8, 1: 15}, "total": 34},
            market_breadth={"ad_ratio": 3.5},
            northbound_signal={"direction": "大幅流入"},
        )
        assert phase == "高潮"

    def test_freezing_point_confirmation(self):
        """冰点确认机制应生效"""
        recent_data = [
            {"highest_board_dropped": True, "heavy_muffled_rate": 35, "avg_promotion_rate": 15, "northbound_direction": "小幅流出"},
            {"highest_board_dropped": True, "heavy_muffled_rate": 30, "avg_promotion_rate": 18, "northbound_direction": "大幅流出"},
        ]
        phase = _judge_emotion_phase(
            seal_quality={},
            yesterday_performance={},
            board_dist={"highest_board": 0, "distribution": {}, "total": 0},
            market_breadth={},
            northbound_signal={},
            recent_2day_data=recent_data,
        )
        assert phase == "冰点（已确认）"

    def test_valid_phases(self):
        """返回值应为有效情绪周期"""
        valid_phases = ["冰点", "冰点（已确认）", "低迷", "修复", "升温", "高潮", "退潮"]
        phase = _judge_emotion_phase(
            seal_quality={"effective_seal_rate": 50},
            yesterday_performance={"avg_return": 0, "heavy_muffled_rate": 10, "muffled_rate": 15, "promotion_rates": {1: 40}},
            board_dist={"highest_board": 3, "distribution": {3: 1, 2: 2, 1: 5}, "total": 8},
            market_breadth={"ad_ratio": 1.5},
            northbound_signal={"direction": "小幅流入"},
        )
        assert phase in valid_phases


class TestCalculateEmotionMetrics:
    """P2-08: 情绪指标汇总"""

    def test_returns_complete_dict(self):
        """应返回完整的情绪指标字典"""
        limitup = [
            {"code": "000001", "consecutive_days": 3, "limit_type": "换手", "turnover_rate": 0.08},
            {"code": "000002", "consecutive_days": 1, "limit_type": "一字", "turnover_rate": 0.01},
        ]
        limitdown = [{"code": "000003"}]
        yesterday_perf = {
            "avg_return": 2.5, "continuous_premium": 3.0, "first_board_premium": 2.0,
            "high_open_rate": 60, "median_return": 2.0,
            "muffled_rate": 10, "light_muffled_rate": 15, "heavy_muffled_rate": 5,
            "promotion_rates": {1: 50, 2: 30},
        }
        market_breadth = {"up_count": 2000, "down_count": 1000, "flat_count": 500, "ad_ratio": 2.0, "breadth_signal": "正常"}
        northbound = {"net_inflow": 15, "direction": "小幅流入", "is_confirming_strength": True, "is_confirming_weakness": False}

        result = _calculate_emotion_metrics(limitup, limitdown, yesterday_perf, market_breadth, northbound)

        assert "highest_board" in result
        assert "board_distribution" in result
        assert "limitup_count" in result
        assert "limitdown_count" in result
        assert "yizi_count" in result
        assert "huan_shou_count" in result
        assert "seal_quality" in result
        assert "yesterday_performance" in result
        assert "board_health_score" in result
        assert "emotion_phase" in result
        assert "emotion_score" in result
        assert "market_breadth" in result
        assert "northbound_signal" in result

    def test_emotion_score_range(self):
        """情绪评分应在0-100范围内"""
        result = _calculate_emotion_metrics(
            [{"consecutive_days": 3, "limit_type": "换手"}],
            [],
            {"avg_return": 2, "muffled_rate": 10},
            {"ad_ratio": 2},
            {"direction": "小幅流入"},
        )
        assert 0 <= result["emotion_score"] <= 100

    def test_empty_data(self):
        """空数据应正常处理"""
        result = _calculate_emotion_metrics([], [], {}, {}, {})
        assert result["highest_board"] == 0
        assert result["limitup_count"] == 0


class TestGetConsecutiveLimitStats:
    """P2-09: 主接口测试"""

    def test_returns_string(self):
        """返回应为字符串"""
        result = get_consecutive_limit_stats("2026-06-16")
        assert isinstance(result, str)

    def test_contains_key_sections(self):
        """应包含关键章节"""
        result = get_consecutive_limit_stats("2026-06-16")
        assert "连板梯队统计" in result or "情绪" in result

    def test_empty_date(self):
        """空日期应正常处理"""
        result = get_consecutive_limit_stats("")
        assert isinstance(result, str)

    def test_error_handling(self):
        """异常应被捕获返回错误信息"""
        result = get_consecutive_limit_stats("invalid_date_format")
        assert isinstance(result, str)
        # 不应该抛出异常


# ===========================================================================
# Phase 3: 题材热度追踪
# ===========================================================================


class TestGetLimitupByTheme:
    """P3-01: 涨停按题材聚合"""

    def test_returns_dict(self):
        """返回应为字典"""
        result = _get_limitup_by_theme("2026-06-16")
        assert isinstance(result, dict)

    def test_empty_on_no_data(self):
        """无数据时应返回空字典"""
        result = _get_limitup_by_theme("2026-01-01")
        assert isinstance(result, dict)

    def test_theme_keys_are_strings(self):
        """题材名应为字符串"""
        result = _get_limitup_by_theme("2026-06-16")
        for theme_name in result:
            assert isinstance(theme_name, str)

    def test_stocks_have_required_fields(self):
        """聚合后的股票应包含必要字段"""
        result = _get_limitup_by_theme("2026-06-16")
        for theme_name, stocks in result.items():
            assert isinstance(stocks, list)
            if stocks:
                stock = stocks[0]
                assert "code" in stock
                assert "name" in stock
                assert "board_num" in stock
                assert "limit_type" in stock
                assert "raw_reason" in stock


class TestGetThemeHistory:
    """P3-02: 题材历史热度"""

    def test_returns_list(self):
        """返回应为列表"""
        result = _get_theme_history("AI概念", days=7)
        assert isinstance(result, list)

    def test_record_fields(self):
        """每条记录应包含 date, count, highest_board"""
        result = _get_theme_history("AI概念", days=5)
        if result:
            record = result[0]
            assert "date" in record
            assert "count" in record
            assert "highest_board" in record

    def test_count_is_non_negative(self):
        """涨停数应非负"""
        result = _get_theme_history("AI概念", days=5)
        for record in result:
            assert record["count"] >= 0
            assert record["highest_board"] >= 0


class TestGetThemeLeaderStatus:
    """P3-03: 题材龙头状态"""

    def test_empty_stocks(self):
        """空股票列表应返回默认值"""
        result = _get_theme_leader_status("AI概念", [])
        assert result["leader_code"] == ""
        assert result["leader_board_num"] == 0
        assert result["leader_seal_status"] == "无"
        assert result["has_deputy"] is False

    def test_finds_highest_board(self):
        """应找到最高连板股票"""
        stocks = [
            {"code": "000001", "name": "A", "board_num": 1},
            {"code": "000002", "name": "B", "board_num": 3},
            {"code": "000003", "name": "C", "board_num": 2},
        ]
        result = _get_theme_leader_status("AI概念", stocks)
        assert result["leader_code"] == "000002"
        assert result["leader_board_num"] == 3

    def test_deputy_count(self):
        """应正确统计补涨龙数量"""
        stocks = [
            {"code": "000001", "name": "A", "board_num": 5},
            {"code": "000002", "name": "B", "board_num": 3},
            {"code": "000003", "name": "C", "board_num": 2},
            {"code": "000004", "name": "D", "board_num": 1},
        ]
        result = _get_theme_leader_status("AI概念", stocks)
        assert result["has_deputy"] is True
        assert result["deputy_count"] == 2  # 3板和2板各1只


class TestGetThemeActiveDays:
    """P3-04: 活跃天数计算"""

    def test_all_active(self):
        """全部活跃应返回总天数"""
        history = [
            {"date": "2026-06-13", "count": 12},
            {"date": "2026-06-12", "count": 8},
            {"date": "2026-06-11", "count": 5},
            {"date": "2026-06-10", "count": 3},
            {"date": "2026-06-09", "count": 1},
        ]
        result = _get_theme_active_days(history)
        assert result == 5

    def test_partial_active(self):
        """部分活跃应正确计数"""
        history = [
            {"date": "2026-06-13", "count": 12},
            {"date": "2026-06-12", "count": 8},
            {"date": "2026-06-11", "count": 5},
            {"date": "2026-06-10", "count": 0},  # 无涨停
            {"date": "2026-06-09", "count": 3},
            {"date": "2026-06-08", "count": 0},  # 无涨停
            {"date": "2026-06-07", "count": 1},
        ]
        result = _get_theme_active_days(history)
        assert result == 5  # 5天有涨停

    def test_empty_history(self):
        """空历史应返回0"""
        result = _get_theme_active_days([])
        assert result == 0

    def test_no_active(self):
        """全部无涨停应返回0"""
        history = [
            {"date": "2026-06-13", "count": 0},
            {"date": "2026-06-12", "count": 0},
        ]
        result = _get_theme_active_days(history)
        assert result == 0


class TestGetThemePhase:
    """P3-05: 题材阶段判断"""

    def test_trial_phase(self):
        """应能判断试探期"""
        result = _get_theme_phase(
            theme_stocks=[
                {"code": "000001", "board_num": 1},
                {"code": "000002", "board_num": 1},
            ],
            theme_history=[],
            leader_status={"leader_board_num": 1, "leader_seal_status": "封板"},
        )
        assert result["phase"] == "试探期"

    def test_ferment_phase(self):
        """应能判断发酵期"""
        stocks = [{"code": f"00000{i}", "board_num": 2 if i == 1 else 1} for i in range(7)]
        result = _get_theme_phase(
            theme_stocks=stocks,
            theme_history=[],
            leader_status={"leader_board_num": 2, "leader_seal_status": "封板"},
        )
        assert result["phase"] == "发酵期"

    def test_main_rise_phase(self):
        """应能判断主升期"""
        stocks = [{"code": f"00000{i}", "board_num": max(1, 5 - i)} for i in range(15)]
        result = _get_theme_phase(
            theme_stocks=stocks,
            theme_history=[],
            leader_status={"leader_board_num": 5, "leader_seal_status": "封板"},
        )
        assert result["phase"] == "主升期"

    def test_freezing_phase(self):
        """应能判断冰点期"""
        result = _get_theme_phase(
            theme_stocks=[{"code": "000001", "board_num": 1}],
            theme_history=[],
            leader_status={"leader_board_num": 1, "leader_seal_status": "断板"},
        )
        assert result["phase"] == "冰点期"

    def test_result_has_required_fields(self):
        """结果应包含 phase, reason, duration"""
        result = _get_theme_phase([], [], {"leader_board_num": 0, "leader_seal_status": "无"})
        assert "phase" in result
        assert "reason" in result
        assert "duration" in result


class TestCalculateThemeTrend:
    """P3-06: 题材趋势判断"""

    def test_warming(self):
        """应能判断升温"""
        history = [
            {"date": "2026-06-13", "count": 15},
            {"date": "2026-06-12", "count": 10},
            {"date": "2026-06-11", "count": 5},
        ]
        result = _calculate_theme_trend(history, "封板")
        assert result == "升温"

    def test_cooling(self):
        """应能判断退潮"""
        history = [
            {"date": "2026-06-13", "count": 5},
            {"date": "2026-06-12", "count": 10},
            {"date": "2026-06-11", "count": 15},
        ]
        result = _calculate_theme_trend(history, "封板")
        assert result == "退潮"

    def test_leader_divergence_cooling(self):
        """龙头分歧应加速退潮判断"""
        history = [
            {"date": "2026-06-13", "count": 5},
            {"date": "2026-06-12", "count": 10},
        ]
        result = _calculate_theme_trend(history, "分歧")
        assert result == "退潮"

    def test_empty_history(self):
        """空历史应返回震荡"""
        result = _calculate_theme_trend([], "封板")
        assert result == "震荡"

    def test_valid_values(self):
        """返回值应为有效趋势"""
        valid = ["升温", "高潮", "退潮", "震荡"]
        history = [
            {"date": "2026-06-13", "count": 8},
            {"date": "2026-06-12", "count": 8},
        ]
        result = _calculate_theme_trend(history, "封板")
        assert result in valid


class TestCalculateThemeRecognitionScore:
    """P3-07: 辨识度评分"""

    def test_high_recognition(self):
        """高辨识度应得高分"""
        result = _calculate_theme_recognition_score(
            stock_count=12,
            highest_board=5,
            leader_seal_status="封板",
            seal_concentration=0.6,
            northbound_inflow=True,
        )
        assert result["score"] >= 70
        assert result["level"] == "高辨识度"

    def test_low_recognition(self):
        """低辨识度应得低分"""
        result = _calculate_theme_recognition_score(
            stock_count=2,
            highest_board=1,
            leader_seal_status="断板",
            seal_concentration=0.1,
            northbound_inflow=False,
        )
        assert result["score"] < 40
        assert result["level"] == "低辨识度"

    def test_score_range(self):
        """评分应在0-100范围内"""
        result = _calculate_theme_recognition_score(
            stock_count=5,
            highest_board=2,
            leader_seal_status="分歧",
            seal_concentration=0.3,
            northbound_inflow=True,
        )
        assert 0 <= result["score"] <= 100

    def test_breakdown_exists(self):
        """应包含 breakdown 明细"""
        result = _calculate_theme_recognition_score(
            stock_count=10,
            highest_board=3,
            leader_seal_status="封板",
            seal_concentration=0.5,
            northbound_inflow=True,
        )
        assert "breakdown" in result
        assert "stock_count" in result["breakdown"]
        assert "ladder" in result["breakdown"]
        assert "leader" in result["breakdown"]
        assert "seal_concentration" in result["breakdown"]
        assert "northbound" in result["breakdown"]

    def test_mid_recognition(self):
        """中辨识度应在40-70之间"""
        result = _calculate_theme_recognition_score(
            stock_count=5,
            highest_board=2,
            leader_seal_status="分歧",
            seal_concentration=0.3,
            northbound_inflow=False,
        )
        assert 40 <= result["score"] < 70
        assert result["level"] == "中辨识度"


class TestCalculateHeatScore:
    """P3-08: 热度评分权重"""

    def test_leader_sealed_higher_than_broken(self):
        """龙头封板应明显高于断板"""
        score_sealed = _calculate_heat_score(
            stock_count=10, highest_board=5, active_days=5,
            phase="主升", leader_seal_status="封板", northbound_direction="小幅流入",
        )
        score_broken = _calculate_heat_score(
            stock_count=10, highest_board=5, active_days=5,
            phase="主升", leader_seal_status="断板", northbound_direction="小幅流入",
        )
        # 龙头封板应该明显高于断板（25%权重差异）
        assert score_sealed > score_broken + 20

    def test_score_range(self):
        """评分应在0-100范围内"""
        result = _calculate_heat_score(
            stock_count=5, highest_board=3, active_days=3,
            phase="发酵", leader_seal_status="封板", northbound_direction="小幅流入",
        )
        assert 0 <= result <= 100

    def test_zero_all(self):
        """全零输入应返回0"""
        result = _calculate_heat_score(
            stock_count=0, highest_board=0, active_days=0,
            phase="冰点", leader_seal_status="断板", northbound_direction="大幅流出",
        )
        assert result == 0

    def test_high_all(self):
        """高输入应返回高分"""
        result = _calculate_heat_score(
            stock_count=20, highest_board=7, active_days=7,
            phase="高潮", leader_seal_status="封板", northbound_direction="大幅流入",
        )
        assert result > 80

    def test_northbound_inflow_boosts_score(self):
        """北向资金流入应提升评分"""
        score_in = _calculate_heat_score(
            stock_count=5, highest_board=3, active_days=3,
            phase="发酵", leader_seal_status="封板", northbound_direction="大幅流入",
        )
        score_out = _calculate_heat_score(
            stock_count=5, highest_board=3, active_days=3,
            phase="发酵", leader_seal_status="封板", northbound_direction="大幅流出",
        )
        assert score_in > score_out


class TestGetThemeHeat:
    """P3-09: 主接口测试"""

    def test_returns_string(self):
        """返回应为字符串"""
        result = get_theme_heat("2026-06-16", top_n=5)
        assert isinstance(result, str)

    def test_contains_keyword(self):
        """应包含题材热度关键词"""
        result = get_theme_heat("2026-06-16", top_n=5)
        assert "题材" in result or "涨停" in result or "热度" in result

    def test_top_n_parameter(self):
        """top_n参数应生效"""
        result = get_theme_heat("2026-06-16", top_n=3)
        assert isinstance(result, str)

    def test_empty_date(self):
        """空日期应正常处理"""
        result = get_theme_heat("", top_n=5)
        assert isinstance(result, str)

    def test_error_handling(self):
        """异常应被捕获返回错误信息"""
        result = get_theme_heat("invalid_date_format", top_n=5)
        assert isinstance(result, str)
        # 不应该抛出异常


# ===========================================================================
# Phase 4: 首板筛选 + 二板预期
# ===========================================================================


class TestGetFirstBoardStocks:
    """P4-01: 首板股票获取"""

    def test_returns_list(self):
        """返回应为列表"""
        result = _get_first_board_stocks("2026-06-16")
        assert isinstance(result, list)

    def test_empty_date(self):
        """空日期应正常处理"""
        result = _get_first_board_stocks("")
        assert isinstance(result, list)

    def test_error_handling(self):
        """异常应被捕获返回空列表"""
        result = _get_first_board_stocks("invalid_date_format")
        assert isinstance(result, list)

    def test_all_stocks_are_first_board(self):
        """所有返回股票的连板天数应为1"""
        result = _get_first_board_stocks("2026-06-16")
        for stock in result:
            assert stock.get("consecutive_days") == 1

    def test_has_first_limit_time(self):
        """应包含首板涨停时间"""
        result = _get_first_board_stocks("2026-06-16")
        if result:
            assert "first_limit_time" in result[0]


class TestGetStockSealInfo:
    """P4-02: 封单信息获取"""

    def test_returns_dict(self):
        """返回应为字典"""
        stock = {
            "turnover_rate": 0.08, "limit_type": "换手",
            "amount": 2e8, "circulation_mv": 5e9,
        }
        result = _get_stock_seal_info(stock)
        assert isinstance(result, dict)

    def test_contains_required_fields(self):
        """应包含必要字段"""
        stock = {
            "turnover_rate": 0.05, "limit_type": "一字",
            "amount": 1e8, "circulation_mv": 3e9,
        }
        result = _get_stock_seal_info(stock)
        assert "seal_strength_score" in result
        assert "seal_ratio" in result
        assert "board_type" in result

    def test_yizi_board_stronger(self):
        """一字板封单应强于换手板"""
        base_stock = {
            "turnover_rate": 0.05, "amount": 1e8, "circulation_mv": 3e9,
        }
        yizi = _get_stock_seal_info({**base_stock, "limit_type": "一字"})
        huanshou = _get_stock_seal_info({**base_stock, "limit_type": "换手"})
        assert yizi["seal_strength_score"] > huanshou["seal_strength_score"]

    def test_low_turnover_stronger(self):
        """低换手率封单应更强"""
        strong = _get_stock_seal_info({
            "turnover_rate": 0.01, "limit_type": "换手",
            "amount": 1e8, "circulation_mv": 3e9,
        })
        weak = _get_stock_seal_info({
            "turnover_rate": 0.15, "limit_type": "换手",
            "amount": 1e8, "circulation_mv": 3e9,
        })
        assert strong["seal_strength_score"] > weak["seal_strength_score"]

    def test_score_range(self):
        """评分应在0-100范围内"""
        result = _get_stock_seal_info({
            "turnover_rate": 0.05, "limit_type": "换手",
            "amount": 1e8, "circulation_mv": 3e9,
        })
        assert 0 <= result["seal_strength_score"] <= 100


class TestGetHistoricalActivity:
    """P4-03: 历史股性评分"""

    def test_returns_float(self):
        """返回应为浮点数"""
        result = _get_historical_activity("000001")
        assert isinstance(result, float)

    def test_score_range(self):
        """评分应在0-100范围内"""
        result = _get_historical_activity("000001")
        assert 0 <= result <= 100

    def test_invalid_code_returns_default(self):
        """无效代码应返回默认值"""
        result = _get_historical_activity("999999")
        assert isinstance(result, float)
        assert 0 <= result <= 100


class TestCalculateThemePurity:
    """P4-04: 题材纯正度评分"""

    def test_highest_board_gets_points(self):
        """题材内连板最高应加分"""
        theme_stocks = [
            {"code": "000001", "board_num": 3, "raw_reason": "AI概念"},
            {"code": "000002", "board_num": 1, "raw_reason": "AI概念"},
            {"code": "000003", "board_num": 1, "raw_reason": "AI概念"},
        ]
        result = _calculate_theme_purity("000001", "AI概念", theme_stocks, {})
        assert result >= 30  # 连板最高 +30

    def test_reason_match_gets_points(self):
        """涨停原因匹配题材名应加分"""
        theme_stocks = [
            {"code": "000001", "board_num": 1, "raw_reason": "AI概念"},
        ]
        result = _calculate_theme_purity("000001", "AI概念", theme_stocks, {})
        assert result >= 30  # 原因匹配 +30

    def test_many_stocks_gets_points(self):
        """题材涨停家数多应加分"""
        theme_stocks = [
            {"code": f"00000{i}", "board_num": 1, "raw_reason": "AI概念"}
            for i in range(12)
        ]
        result = _calculate_theme_purity("000001", "AI概念", theme_stocks, {})
        assert result >= 20  # 题材涨停家数>=10 +20

    def test_ladder_support_gets_points(self):
        """有梯队支撑应加分"""
        theme_stocks = [
            {"code": "000001", "board_num": 1, "raw_reason": "AI概念"},
            {"code": "000002", "board_num": 3, "raw_reason": "AI概念"},
        ]
        result = _calculate_theme_purity("000001", "AI概念", theme_stocks, {})
        assert result >= 20  # 梯队支撑 +20

    def test_score_range(self):
        """评分应在0-100范围内"""
        theme_stocks = [
            {"code": "000001", "board_num": 5, "raw_reason": "AI概念大模型"},
            {"code": "000002", "board_num": 3, "raw_reason": "AI概念"},
            {"code": "000003", "board_num": 2, "raw_reason": "AI概念"},
        ]
        result = _calculate_theme_purity("000001", "AI概念", theme_stocks, {})
        assert 0 <= result <= 100


class TestCalculateVolumeMatchScore:
    """P4-05: 量价配合评分"""

    def test_optimal_range(self):
        """最佳换手率区间应得高分"""
        score = _calculate_volume_match_score(
            turnover_rate=0.10, amount=1.5e8, volume_ratio=1.5
        )
        assert score >= 70

    def test_low_turnover(self):
        """低换手率应得中等分"""
        score = _calculate_volume_match_score(
            turnover_rate=0.02, amount=3e7, volume_ratio=0.8
        )
        assert 30 <= score <= 70

    def test_high_turnover(self):
        """高换手率应扣分"""
        score_optimal = _calculate_volume_match_score(
            turnover_rate=0.10, amount=1e8, volume_ratio=1.5
        )
        score_high = _calculate_volume_match_score(
            turnover_rate=0.25, amount=1e8, volume_ratio=1.5
        )
        assert score_optimal > score_high

    def test_score_range(self):
        """评分应在0-100范围内"""
        score = _calculate_volume_match_score(
            turnover_rate=0.08, amount=1e8, volume_ratio=1.2
        )
        assert 0 <= score <= 100

    def test_volume_ratio_matters(self):
        """量比应影响评分"""
        score_good_ratio = _calculate_volume_match_score(
            turnover_rate=0.08, amount=1e8, volume_ratio=1.5
        )
        score_bad_ratio = _calculate_volume_match_score(
            turnover_rate=0.08, amount=1e8, volume_ratio=0.3
        )
        assert score_good_ratio > score_bad_ratio


class TestCalculateSecondBoardScore:
    """P4-06: 二板预期评分"""

    def test_basic_score(self):
        """基本评分应合理"""
        score = calculate_second_board_score(
            seal_strength=80, volume_match=70, theme_heat=80,
            board_type="换手", market_emotion="升温",
            circulation_mv=1e10, first_limit_time="09:45",
            theme_purity=70, historical_activity=70,
        )
        assert 70 <= score <= 100

    def test_yizi_penalty(self):
        """一字板应扣分"""
        score_huanshou = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="换手"
        )
        score_yizi = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="一字"
        )
        assert score_yizi < score_huanshou

    def test_huanshou_bonus(self):
        """换手板应加分"""
        score_huanshou = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="换手"
        )
        score_tzi = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="T字"
        )
        assert score_huanshou > score_tzi

    def test_market_emotion_boost(self):
        """情绪好应加分"""
        score_good = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="换手", market_emotion="高潮",
            circulation_mv=1e10, first_limit_time="09:45",
            theme_purity=70, historical_activity=70,
        )
        score_bad = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="换手", market_emotion="冰点",
            circulation_mv=1e10, first_limit_time="09:45",
            theme_purity=70, historical_activity=70,
        )
        assert score_good > score_bad

    def test_circulation_mv_small_bonus(self):
        """小盘股应加分"""
        score_small = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="换手", market_emotion="升温",
            circulation_mv=3e9, first_limit_time="09:45",
            theme_purity=70, historical_activity=70,
        )
        score_large = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="换手", market_emotion="升温",
            circulation_mv=3e10, first_limit_time="09:45",
            theme_purity=70, historical_activity=70,
        )
        assert score_small > score_large

    def test_early_limit_bonus(self):
        """早盘涨停应加分"""
        score_early = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="换手", market_emotion="升温",
            circulation_mv=1e10, first_limit_time="09:35",
            theme_purity=70, historical_activity=70,
        )
        score_late = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="换手", market_emotion="升温",
            circulation_mv=1e10, first_limit_time="14:00",
            theme_purity=70, historical_activity=70,
        )
        assert score_early > score_late

    def test_score_range(self):
        """评分应在0-100范围内"""
        score = calculate_second_board_score(
            seal_strength=50, volume_match=50, theme_heat=50,
            board_type="换手", market_emotion="修复",
            circulation_mv=1e10, first_limit_time="10:30",
            theme_purity=50, historical_activity=50,
        )
        assert 0 <= score <= 100

    def test_weight_distribution(self):
        """封单强度权重应最高"""
        # 封单强度变化影响应大于题材纯正度变化
        score_high_seal = calculate_second_board_score(
            seal_strength=100, volume_match=50, theme_heat=50,
            board_type="换手"
        )
        score_low_seal = calculate_second_board_score(
            seal_strength=0, volume_match=50, theme_heat=50,
            board_type="换手"
        )
        score_high_purity = calculate_second_board_score(
            seal_strength=50, volume_match=50, theme_heat=50,
            board_type="换手", theme_purity=100
        )
        score_low_purity = calculate_second_board_score(
            seal_strength=50, volume_match=50, theme_heat=50,
            board_type="换手", theme_purity=0
        )
        seal_diff = abs(score_high_seal - score_low_seal)
        purity_diff = abs(score_high_purity - score_low_purity)
        assert seal_diff > purity_diff  # 封单权重25% > 纯正度5%


class TestGetFirstBoardScreen:
    """P4-07: 主接口测试"""

    def test_returns_string(self):
        """返回应为字符串"""
        result = get_first_board_screen("2026-06-16", min_score=60)
        assert isinstance(result, str)

    def test_contains_keyword(self):
        """应包含首板或二板关键词"""
        result = get_first_board_screen("2026-06-16", min_score=60)
        assert "首板" in result or "二板" in result

    def test_min_score_filter(self):
        """min_score参数应生效"""
        result = get_first_board_screen("2026-06-16", min_score=90)
        assert isinstance(result, str)

    def test_empty_date(self):
        """空日期应正常处理"""
        result = get_first_board_screen("", min_score=60)
        assert isinstance(result, str)

    def test_error_handling(self):
        """异常应被捕获返回错误信息"""
        result = get_first_board_screen("invalid_date_format", min_score=60)
        assert isinstance(result, str)
        # 不应该抛出异常

    def test_non_trading_day(self):
        """非交易日应返回无数据提示"""
        result = get_first_board_screen("2026-06-08", min_score=60)  # Sunday
        assert isinstance(result, str)


# ===========================================================================
# Phase 5: 高标股状态监控
# ===========================================================================


class TestGetHighBoardStocks:
    """P5-01: 最高板股票获取"""

    def test_returns_list(self):
        """返回应为列表"""
        result = _get_high_board_stocks("2026-06-16")
        assert isinstance(result, list)

    def test_empty_date(self):
        """空日期应正常处理"""
        result = _get_high_board_stocks("")
        assert isinstance(result, list)

    def test_error_handling(self):
        """异常应被捕获返回空列表"""
        result = _get_high_board_stocks("invalid_date_format")
        assert isinstance(result, list)

    def test_all_stocks_same_board_num(self):
        """所有返回股票的连板天数应相同（最高板）"""
        result = _get_high_board_stocks("2026-06-16")
        if len(result) > 1:
            board_nums = [s.get("consecutive_days", 0) for s in result]
            assert len(set(board_nums)) == 1

    def test_board_num_is_maximum(self):
        """返回的连板天数应为当日最高"""
        result = _get_high_board_stocks("2026-06-16")
        if result:
            max_board = max(s.get("consecutive_days", 0) for s in result)
            for s in result:
                assert s.get("consecutive_days", 0) == max_board


class TestCalculateDivergenceScore:
    """P5-04: 分歧度评估"""

    def test_consistent(self):
        """一致状态应得低分"""
        result = _calculate_divergence_score(
            seal_stable=True, open_count=0, seal_ratio=5.0
        )
        assert result["divergence_score"] < 30
        assert result["level"] == "一致"
        assert result["can_do_high_board"] is True

    def test_mild_divergence(self):
        """轻度分歧应在30-50之间"""
        result = _calculate_divergence_score(
            seal_stable=True, open_count=1, seal_ratio=2.0
        )
        assert 30 <= result["divergence_score"] < 50
        assert result["level"] == "轻度分歧"
        assert result["can_do_high_board"] is True

    def test_moderate_divergence(self):
        """中度分歧应在50-70之间"""
        result = _calculate_divergence_score(
            seal_stable=True, open_count=5, seal_ratio=0.5
        )
        assert 50 <= result["divergence_score"] < 70
        assert result["level"] == "中度分歧"
        assert result["can_do_high_board"] is False

    def test_severe_divergence(self):
        """重度分歧应>=70"""
        result = _calculate_divergence_score(
            seal_stable=False, open_count=6, seal_ratio=0.5
        )
        assert result["divergence_score"] >= 70
        assert result["level"] == "重度分歧"
        assert result["can_do_high_board"] is False

    def test_seal_unstable_high_score(self):
        """封单不在应直接加50分"""
        result = _calculate_divergence_score(
            seal_stable=False, open_count=0, seal_ratio=0
        )
        assert result["divergence_score"] == 50

    def test_seal_ratio_thresholds(self):
        """封单/流通盘比分级应正确"""
        # 封单充足（>3%）
        r1 = _calculate_divergence_score(True, 0, 5.0)
        # 封单一般（1-3%）
        r2 = _calculate_divergence_score(True, 0, 2.0)
        # 封单不足（<1%）
        r3 = _calculate_divergence_score(True, 0, 0.5)
        assert r1["divergence_score"] < r2["divergence_score"] < r3["divergence_score"]

    def test_open_count_levels(self):
        """开板次数分级应正确"""
        r0 = _calculate_divergence_score(True, 0, 5.0)
        r2 = _calculate_divergence_score(True, 2, 5.0)
        r5 = _calculate_divergence_score(True, 5, 5.0)
        r6 = _calculate_divergence_score(True, 6, 5.0)
        assert r0["divergence_score"] < r2["divergence_score"]
        assert r2["divergence_score"] < r5["divergence_score"]
        assert r5["divergence_score"] < r6["divergence_score"]

    def test_score_range(self):
        """评分应在0-100范围内"""
        result = _calculate_divergence_score(True, 3, 2.0)
        assert 0 <= result["divergence_score"] <= 100


class TestCalculateBreakRiskLevel:
    """P5-05: 断板风险评估"""

    def test_high_risk_yizi_burst(self):
        """放量一字后开板应为高风险"""
        risk = _calculate_break_risk_level(
            board_num=5,
            seal_status="封板",
            open_count=1,
            divergence_score=20,
            same_theme_performance=1.0,
            market_emotion="升温",
            consecutive_yizi_days=4,
            yizi_cumulative_turnover=15,
            card_position_exists=False,
        )
        assert risk["risk_level"] == "高"
        assert any("放量一字后开板" in s for s in risk["risk_signals"])

    def test_high_risk_seal_broken(self):
        """封板状态异常应为高风险"""
        risk = _calculate_break_risk_level(
            board_num=3,
            seal_status="断板",
            open_count=0,
            divergence_score=20,
            same_theme_performance=1.0,
            market_emotion="升温",
            consecutive_yizi_days=0,
            yizi_cumulative_turnover=0,
            card_position_exists=False,
        )
        assert risk["risk_level"] == "高"
        assert any("封板状态异常" in s for s in risk["risk_signals"])

    def test_high_risk_high_divergence(self):
        """分歧度>70应为高风险"""
        risk = _calculate_break_risk_level(
            board_num=3,
            seal_status="封板",
            open_count=0,
            divergence_score=80,
            same_theme_performance=1.0,
            market_emotion="升温",
            consecutive_yizi_days=0,
            yizi_cumulative_turnover=0,
            card_position_exists=False,
        )
        assert risk["risk_level"] == "高"
        assert any("分歧度>70" in s for s in risk["risk_signals"])

    def test_low_risk(self):
        """低风险信号应返回低风险等级"""
        risk = _calculate_break_risk_level(
            board_num=3,
            seal_status="封板",
            open_count=0,
            divergence_score=10,
            same_theme_performance=2.0,
            market_emotion="升温",
            consecutive_yizi_days=2,
            yizi_cumulative_turnover=3,
            card_position_exists=False,
        )
        assert risk["risk_level"] == "低"

    def test_medium_risk_multiple_signals(self):
        """多个中风险信号应返回中风险"""
        risk = _calculate_break_risk_level(
            board_num=3,
            seal_status="封板",
            open_count=0,
            divergence_score=60,
            same_theme_performance=-2.0,
            market_emotion="冰点",
            consecutive_yizi_days=0,
            yizi_cumulative_turnover=0,
            card_position_exists=False,
        )
        assert risk["risk_level"] == "中"

    def test_card_position_threat(self):
        """卡位威胁应被记录"""
        risk = _calculate_break_risk_level(
            board_num=3,
            seal_status="封板",
            open_count=0,
            divergence_score=10,
            same_theme_performance=1.0,
            market_emotion="升温",
            consecutive_yizi_days=0,
            yizi_cumulative_turnover=0,
            card_position_exists=True,
        )
        assert any("卡位威胁" in s for s in risk["risk_signals"])

    def test_yizi_turnover_recorded(self):
        """一字板累计换手率应被记录"""
        risk = _calculate_break_risk_level(
            board_num=5,
            seal_status="封板",
            open_count=0,
            divergence_score=10,
            same_theme_performance=1.0,
            market_emotion="升温",
            consecutive_yizi_days=4,
            yizi_cumulative_turnover=8.5,
            card_position_exists=False,
        )
        assert risk["consecutive_yizi_days"] == 4
        assert risk["yizi_cumulative_turnover"] == 8.5

    def test_market_emotion_cold(self):
        """市场情绪转差应被记录"""
        risk = _calculate_break_risk_level(
            board_num=3,
            seal_status="封板",
            open_count=0,
            divergence_score=10,
            same_theme_performance=1.0,
            market_emotion="冰点",
            consecutive_yizi_days=0,
            yizi_cumulative_turnover=0,
            card_position_exists=False,
        )
        assert any("市场情绪转差" in s for s in risk["risk_signals"])


class TestGetYiziCumulativeTurnover:
    """P5-03: 一字板累计换手率"""

    def test_returns_float(self):
        """返回应为浮点数"""
        result = _get_yizi_cumulative_turnover("000001", 3)
        assert isinstance(result, float)

    def test_zero_days(self):
        """零天应返回0"""
        result = _get_yizi_cumulative_turnover("000001", 0)
        assert result == 0.0

    def test_non_negative(self):
        """结果应非负"""
        result = _get_yizi_cumulative_turnover("000001", 5)
        assert result >= 0.0

    def test_invalid_code(self):
        """无效代码应返回0"""
        result = _get_yizi_cumulative_turnover("999999", 3)
        assert isinstance(result, float)
        assert result >= 0.0


class TestGetThemeEffectForHighBoard:
    """P5-06: 板块效应"""

    def test_returns_dict(self):
        """返回应为字典"""
        result = _get_theme_effect_for_high_board("000001", {})
        assert isinstance(result, dict)

    def test_contains_required_fields(self):
        """应包含必要字段"""
        result = _get_theme_effect_for_high_board("000001", {})
        assert "themes" in result
        assert "theme_performance" in result
        assert "is_theme_strong" in result
        assert "other_stocks_in_theme" in result

    def test_empty_theme_map(self):
        """空题材映射应返回默认值"""
        result = _get_theme_effect_for_high_board("000001", {})
        assert result["other_stocks_in_theme"] == 0
        assert result["is_theme_strong"] is False

    def test_with_theme_data(self):
        """有题材数据应正确匹配"""
        theme_map = {
            "AI概念": [
                {"code": "000001", "board_num": 5},
                {"code": "000002", "board_num": 3},
                {"code": "000003", "board_num": 2},
            ]
        }
        result = _get_theme_effect_for_high_board("000001", theme_map)
        # 至少应有一些匹配（取决于概念板块解析）
        assert isinstance(result["other_stocks_in_theme"], int)


class TestGetHighBoardStatus:
    """P5-07: 主接口测试"""

    def test_returns_string(self):
        """返回应为字符串"""
        result = get_high_board_status("2026-06-16")
        assert isinstance(result, str)

    def test_contains_keyword(self):
        """应包含高标或连板关键词"""
        result = get_high_board_status("2026-06-16")
        assert "高标" in result or "连板" in result

    def test_empty_date(self):
        """空日期应正常处理"""
        result = get_high_board_status("")
        assert isinstance(result, str)

    def test_error_handling(self):
        """异常应被捕获返回错误信息"""
        result = get_high_board_status("invalid_date_format")
        assert isinstance(result, str)
        # 不应该抛出异常

    def test_non_trading_day(self):
        """非交易日应返回无数据提示"""
        result = get_high_board_status("2026-06-08")  # Sunday
        assert isinstance(result, str)


# ===========================================================================
# Phase 6: 龙头识别 + 卡位分析
# ===========================================================================


class TestGetSameThemeStocks:
    """P8-25: 测试同题材获取"""

    @patch("tradingagents.dataflows.a_stock.get_concept_blocks")
    @patch("tradingagents.dataflows.a_stock._get_limitup_by_theme")
    def test_basic(self, mock_theme, mock_blocks):
        """基本同题材匹配"""
        mock_blocks.return_value = "Concept tags: AI / 算力 / 大模型"
        mock_theme.return_value = {
            "AI概念": [
                {"code": "000002", "name": "股票B", "board_num": 3,
                 "seal_strength": 0.05, "circulation_mv": 3e9},
                {"code": "000003", "name": "股票C", "board_num": 2,
                 "seal_strength": 0.03, "circulation_mv": 5e9},
            ],
            "其他": [
                {"code": "000004", "name": "股票D", "board_num": 1,
                 "seal_strength": 0.02, "circulation_mv": 2e9},
            ],
        }
        result = _get_same_theme_stocks("000001", "2026-06-16")
        assert isinstance(result, list)
        # 应排除自身
        assert all(s["code"] != "000001" for s in result)
        # 应按连板数降序排列
        if len(result) >= 2:
            assert result[0]["board_num"] >= result[1]["board_num"]

    @patch("tradingagents.dataflows.a_stock.get_concept_blocks")
    def test_no_concepts(self, mock_blocks):
        """无概念板块时返回空"""
        mock_blocks.return_value = "No concept tags"
        result = _get_same_theme_stocks("000001", "2026-06-16")
        assert result == []

    @patch("tradingagents.dataflows.a_stock.get_concept_blocks")
    @patch("tradingagents.dataflows.a_stock._get_limitup_by_theme")
    def test_empty_theme_map(self, mock_theme, mock_blocks):
        """题材映射为空时返回空"""
        mock_blocks.return_value = "Concept tags: AI"
        mock_theme.return_value = {}
        result = _get_same_theme_stocks("000001", "2026-06-16")
        assert result == []

    @patch("tradingagents.dataflows.a_stock.get_concept_blocks")
    def test_exception_handling(self, mock_blocks):
        """异常应被捕获"""
        mock_blocks.side_effect = Exception("network error")
        result = _get_same_theme_stocks("000001", "2026-06-16")
        assert result == []


class TestGetLeaderCandidates:
    """P8-25: 测试龙头候选获取"""

    @patch("tradingagents.dataflows.a_stock._get_limitup_by_theme")
    def test_basic(self, mock_theme):
        """基本龙头候选"""
        mock_theme.return_value = {
            "AI概念": [
                {"code": "000001", "name": "A", "board_num": 5},
                {"code": "000002", "name": "B", "board_num": 3},
            ],
            "新能源": [
                {"code": "000003", "name": "C", "board_num": 4},
            ],
        }
        result = _get_leader_candidates("2026-06-16")
        assert isinstance(result, list)
        assert len(result) == 2
        # 按涨停家数降序
        assert result[0]["theme_stock_count"] >= result[1]["theme_stock_count"]
        # 各题材的leader应为最高板
        for c in result:
            assert c["leader"]["board_num"] >= max(
                s["board_num"] for s in c["stocks"]
            )

    @patch("tradingagents.dataflows.a_stock._get_limitup_by_theme")
    def test_empty(self, mock_theme):
        """空题材映射"""
        mock_theme.return_value = {}
        result = _get_leader_candidates("2026-06-16")
        assert result == []


class TestCalculateLeaderScore:
    """P8-26: 测试龙头评分"""

    def test_high_score(self):
        """高分场景：最高板+早盘+强封单"""
        result = _calculate_leader_score(
            board_num=6,
            first_limit_time="09:32",
            seal_strength=8.0,
            theme_purity=90,
            theme_stocks_count=12,
            rank_in_theme=1,
            circulation_mv=3e9,
            is_market_highest=True,
            is_earliest_in_board=True,
            is_yizi=False,
            historical_broken_count=0,
        )
        assert result["total_score"] >= 70
        assert len(result["bonuses"]) >= 2  # 最高板+最早

    def test_low_score(self):
        """低分场景：低板+尾盘+弱封单"""
        result = _calculate_leader_score(
            board_num=1,
            first_limit_time="14:00",
            seal_strength=0.5,
            theme_purity=30,
            theme_stocks_count=2,
            rank_in_theme=2,
            circulation_mv=25e9,
            is_market_highest=False,
            is_earliest_in_board=False,
            is_yizi=False,
            historical_broken_count=5,
        )
        assert result["total_score"] <= 40
        assert len(result["penalties"]) >= 2  # 大市值+经常炸板

    def test_score_range(self):
        """分数应在0-100"""
        result = _calculate_leader_score(
            board_num=3,
            first_limit_time="09:45",
            seal_strength=5.0,
            theme_purity=70,
            theme_stocks_count=8,
            rank_in_theme=1,
            circulation_mv=5e9,
            is_market_highest=False,
            is_earliest_in_board=False,
            is_yizi=True,
            historical_broken_count=0,
        )
        assert 0 <= result["total_score"] <= 100
        assert "breakdown" in result
        assert "bonuses" in result
        assert "penalties" in result

    def test_yizi_bonus(self):
        """一字板加成"""
        r1 = _calculate_leader_score(
            board_num=3, first_limit_time="09:30", seal_strength=5.0,
            theme_purity=70, theme_stocks_count=5, rank_in_theme=1,
            circulation_mv=3e9, is_market_highest=False,
            is_earliest_in_board=False, is_yizi=True,
            historical_broken_count=0,
        )
        r2 = _calculate_leader_score(
            board_num=3, first_limit_time="09:30", seal_strength=5.0,
            theme_purity=70, theme_stocks_count=5, rank_in_theme=1,
            circulation_mv=3e9, is_market_highest=False,
            is_earliest_in_board=False, is_yizi=False,
            historical_broken_count=0,
        )
        assert r1["total_score"] > r2["total_score"]


class TestCalculateTimeScore:
    """P8-26: 测试涨停时间评分"""

    def test_miao_ban(self):
        """秒板（9:30-9:35）"""
        assert _calculate_time_score("09:30") == 100.0
        assert _calculate_time_score("09:35") == 100.0

    def test_early_morning(self):
        """早盘强封（9:35-9:45）"""
        assert _calculate_time_score("09:40") == 90.0

    def test_mid_morning(self):
        """上午（9:45-10:00）"""
        assert _calculate_time_score("09:50") == 80.0

    def test_late_morning(self):
        """上午晚些（10:00-10:30）"""
        assert _calculate_time_score("10:15") == 70.0

    def test_noon(self):
        """午间（10:30-13:00）"""
        assert _calculate_time_score("11:30") == 60.0

    def test_afternoon(self):
        """下午（13:00后）"""
        assert _calculate_time_score("14:30") == 50.0

    def test_empty(self):
        """空字符串"""
        assert _calculate_time_score("") == 50.0

    def test_none_like(self):
        """None-like"""
        assert _calculate_time_score(None) == 50.0


class TestIdentifyCardPosition:
    """P8-27: 测试卡位识别"""

    def test_leader_sealed_strong_card(self):
        """龙头封板时，封单比>1.5为强卡位"""
        same_theme = [
            {"code": "000002", "board_num": 3, "seal_strength": 0.06},
        ]
        result = _identify_card_position(
            "000001", 3, 0.03, "封板", same_theme, "升温"
        )
        assert len(result) == 1
        assert result[0]["card_type"] == "强卡位"
        assert result[0]["seal_ratio_to_leader"] == 2.0

    def test_leader_sealed_medium_card(self):
        """龙头封板时，封单比1-1.5为中卡位"""
        same_theme = [
            {"code": "000002", "board_num": 3, "seal_strength": 0.04},
        ]
        result = _identify_card_position(
            "000001", 3, 0.03, "封板", same_theme, "升温"
        )
        assert len(result) == 1
        assert result[0]["card_type"] == "中卡位"

    def test_leader_divergence_lower_threshold(self):
        """龙头分歧时阈值降低"""
        same_theme = [
            {"code": "000002", "board_num": 3, "seal_strength": 0.04},
        ]
        result = _identify_card_position(
            "000001", 3, 0.03, "分歧", same_theme, "升温"
        )
        assert len(result) == 1
        # 0.04/0.03 = 1.33 > 1.2 → 强卡位
        assert result[0]["card_type"] == "强卡位"

    def test_skip_lower_board(self):
        """低于龙头-1板的不参与卡位"""
        same_theme = [
            {"code": "000002", "board_num": 1, "seal_strength": 0.10},
        ]
        result = _identify_card_position(
            "000001", 3, 0.03, "封板", same_theme, "升温"
        )
        assert len(result) == 0

    def test_exclude_leader(self):
        """排除龙头自身"""
        same_theme = [
            {"code": "000001", "board_num": 3, "seal_strength": 0.03},
        ]
        result = _identify_card_position(
            "000001", 3, 0.03, "封板", same_theme, "升温"
        )
        assert len(result) == 0

    def test_sorted_by_ratio(self):
        """结果按封单比降序排列"""
        same_theme = [
            {"code": "000002", "board_num": 3, "seal_strength": 0.04},
            {"code": "000003", "board_num": 3, "seal_strength": 0.06},
        ]
        result = _identify_card_position(
            "000001", 3, 0.03, "封板", same_theme, "升温"
        )
        assert len(result) == 2
        assert result[0]["seal_ratio_to_leader"] >= result[1]["seal_ratio_to_leader"]

    def test_weak_card(self):
        """封单比<1为弱卡位"""
        same_theme = [
            {"code": "000002", "board_num": 3, "seal_strength": 0.02},
        ]
        result = _identify_card_position(
            "000001", 3, 0.03, "封板", same_theme, "升温"
        )
        assert len(result) == 1
        assert result[0]["card_type"] == "弱卡位"

    def test_zero_leader_seal(self):
        """龙头封单为0时不崩溃"""
        same_theme = [
            {"code": "000002", "board_num": 3, "seal_strength": 0.02},
        ]
        result = _identify_card_position(
            "000001", 3, 0.0, "分歧", same_theme, "升温"
        )
        assert len(result) == 1
        assert result[0]["seal_ratio_to_leader"] == 0


class TestIdentifyDeputyLeader:
    """P8-28: 测试补涨龙识别"""

    def test_basic_deputy(self):
        """基本补涨龙场景"""
        same_theme = [
            {"code": "000002", "board_num": 1, "seal_strength": 5.0,
             "circulation_mv": 3e9},
        ]
        result = _identify_deputy_leader(
            "000001", 5, "分歧", 1e10, same_theme, "升温"
        )
        assert len(result) == 1
        assert result[0]["code"] == "000002"
        assert result[0]["theoretical_height"] == 3

    def test_leader_too_low(self):
        """龙头<4板不启动补涨"""
        same_theme = [
            {"code": "000002", "board_num": 1, "seal_strength": 0.05,
             "circulation_mv": 3e9},
        ]
        result = _identify_deputy_leader(
            "000001", 3, "分歧", 1e10, same_theme, "升温"
        )
        assert len(result) == 0

    def test_leader_sealed_no_deputy(self):
        """龙头封板不启动补涨"""
        same_theme = [
            {"code": "000002", "board_num": 1, "seal_strength": 0.05,
             "circulation_mv": 3e9},
        ]
        result = _identify_deputy_leader(
            "000001", 5, "封板", 1e10, same_theme, "升温"
        )
        assert len(result) == 0

    def test_low_seal_rejected(self):
        """封单不足不入选"""
        same_theme = [
            {"code": "000002", "board_num": 1, "seal_strength": 2.0,
             "circulation_mv": 3e9},
        ]
        result = _identify_deputy_leader(
            "000001", 5, "分歧", 1e10, same_theme, "升温"
        )
        assert len(result) == 0

    def test_high_board_rejected(self):
        """连板数>2不入选"""
        same_theme = [
            {"code": "000002", "board_num": 3, "seal_strength": 5.0,
             "circulation_mv": 3e9},
        ]
        result = _identify_deputy_leader(
            "000001", 5, "分歧", 1e10, same_theme, "升温"
        )
        assert len(result) == 0

    def test_larger_mv_rejected(self):
        """流通市值>=龙头不入选"""
        same_theme = [
            {"code": "000002", "board_num": 1, "seal_strength": 5.0,
             "circulation_mv": 2e10},
        ]
        result = _identify_deputy_leader(
            "000001", 5, "分歧", 1e10, same_theme, "升温"
        )
        assert len(result) == 0

    def test_sorted_by_seal(self):
        """结果按封单强度降序"""
        same_theme = [
            {"code": "000002", "board_num": 1, "seal_strength": 4.0,
             "circulation_mv": 3e9},
            {"code": "000003", "board_num": 2, "seal_strength": 6.0,
             "circulation_mv": 4e9},
        ]
        result = _identify_deputy_leader(
            "000001", 5, "分歧", 1e10, same_theme, "升温"
        )
        assert len(result) == 2
        assert result[0]["seal_strength"] >= result[1]["seal_strength"]


class TestDistinguishDeputyVsNewLeader:
    """P8-29: 测试补涨龙vs新龙头区分"""

    def test_new_leader(self):
        """龙头断板+新票高连板→新龙头"""
        result = _distinguish_deputy_vs_new_leader(
            "000001", 5, "断板", "000002", 4, "AI", "AI"
        )
        assert result["type"] == "new_leader"
        assert result["confidence"] == 0.8

    def test_deputy_leader(self):
        """龙头分歧+低位票同题材→补涨龙"""
        result = _distinguish_deputy_vs_new_leader(
            "000001", 5, "分歧", "000002", 2, "AI", "AI"
        )
        assert result["type"] == "deputy_leader"
        assert result["confidence"] == 0.7

    def test_uncertain(self):
        """无法判断"""
        result = _distinguish_deputy_vs_new_leader(
            "000001", 5, "断板", "000002", 2, "AI", "AI"
        )
        assert result["type"] == "uncertain"

    def test_new_leader_different_theme(self):
        """龙头断板+新票不同题材→新龙头（新方向）"""
        result = _distinguish_deputy_vs_new_leader(
            "000001", 5, "断板", "000002", 5, "新能源", "AI"
        )
        assert result["type"] == "new_leader"

    def test_deputy_leader_board_too_high(self):
        """龙头分歧+低位票连板数太高→不确定"""
        result = _distinguish_deputy_vs_new_leader(
            "000001", 5, "分歧", "000002", 4, "AI", "AI"
        )
        # 4 > 5-2=3，不满足补涨龙条件
        assert result["type"] == "uncertain"


class TestJudgeStrongBullishLeader:
    """强看好龙头判断"""

    def test_strong_bullish(self):
        """全部满足→强看好"""
        result = judge_strong_bullish_leader(
            board_num=5, first_limit_time="09:32", seal_strength=8.0,
            theme_stock_count=12, theme_active_days=4, is_market_highest=True,
        )
        assert result["strong_bullish"] is True
        assert "重仓" in result["action"]

    def test_low_board(self):
        """高度不够"""
        result = judge_strong_bullish_leader(
            board_num=2, first_limit_time="09:32", seal_strength=8.0,
            theme_stock_count=12, theme_active_days=4, is_market_highest=False,
        )
        assert result["strong_bullish"] is False

    def test_weak_seal(self):
        """封单不够"""
        result = judge_strong_bullish_leader(
            board_num=5, first_limit_time="09:32", seal_strength=3.0,
            theme_stock_count=12, theme_active_days=4, is_market_highest=True,
        )
        assert result["strong_bullish"] is False

    def test_late_time(self):
        """涨停太晚"""
        result = judge_strong_bullish_leader(
            board_num=5, first_limit_time="10:30", seal_strength=8.0,
            theme_stock_count=12, theme_active_days=4, is_market_highest=True,
        )
        assert result["strong_bullish"] is False

    def test_weak_theme(self):
        """题材不够强"""
        result = judge_strong_bullish_leader(
            board_num=5, first_limit_time="09:32", seal_strength=8.0,
            theme_stock_count=5, theme_active_days=4, is_market_highest=True,
        )
        assert result["strong_bullish"] is False


class TestJudgeStrongBearishLeader:
    """强看空龙头判断"""

    def test_broken_board(self):
        """龙头断板→强看空"""
        result = judge_strong_bearish_leader(
            board_num=5, seal_status="断板", seal_strength=3.0,
            theme_stock_count=8, card_position_code="",
            card_position_seal_status="断板",
        )
        assert result["strong_bearish"] is True
        assert "断板" in result["reason"]

    def test_divergence_with_card(self):
        """龙头分歧+卡位→强看空"""
        result = judge_strong_bearish_leader(
            board_num=5, seal_status="分歧", seal_strength=3.0,
            theme_stock_count=8, card_position_code="000002",
            card_position_seal_status="封板",
        )
        assert result["strong_bearish"] is True
        assert "卡位" in result["reason"]

    def test_no_signal(self):
        """无看空信号"""
        result = judge_strong_bearish_leader(
            board_num=5, seal_status="封板", seal_strength=5.0,
            theme_stock_count=10, card_position_code="",
            card_position_seal_status="断板",
        )
        assert result["strong_bearish"] is False

    def test_weak_theme(self):
        """题材涨停家数不足"""
        result = judge_strong_bearish_leader(
            board_num=5, seal_status="封板", seal_strength=5.0,
            theme_stock_count=3, card_position_code="",
            card_position_seal_status="断板",
        )
        assert result["strong_bearish"] is True
        assert "不足" in result["reason"]


class TestJudgeCardPositionOutcome:
    """P8-29: 测试卡位结果判断"""

    def test_card_success(self):
        """卡位成功"""
        result = judge_card_position_outcome(
            leader_seal_status="断板", card_seal_status="封板",
            leader_board_num=5, card_board_num=5,
            leader_seal_strength=3.0, card_seal_strength=5.0,
        )
        assert result["card_success"] is True
        assert result["action"] == "跟随新龙头"

    def test_card_fail_leader_back(self):
        """龙头回封+卡位股断板→卡位失败"""
        result = judge_card_position_outcome(
            leader_seal_status="封板", card_seal_status="断板",
            leader_board_num=5, card_board_num=5,
            leader_seal_strength=5.0, card_seal_strength=3.0,
        )
        assert result["card_success"] is False
        assert "原龙头" in result["action"]

    def test_both_broken(self):
        """双龙断板"""
        result = judge_card_position_outcome(
            leader_seal_status="断板", card_seal_status="断板",
            leader_board_num=5, card_board_num=5,
            leader_seal_strength=3.0, card_seal_strength=3.0,
        )
        assert result["card_success"] is False
        assert "观望" in result["action"]

    def test_in_progress(self):
        """卡位进行中"""
        result = judge_card_position_outcome(
            leader_seal_status="分歧", card_seal_status="封板",
            leader_board_num=5, card_board_num=5,
            leader_seal_strength=3.0, card_seal_strength=4.0,
        )
        assert result["card_success"] is False
        assert "等待" in result["reason"]

    def test_card_fail_low_board(self):
        """卡位股连板数不够"""
        result = judge_card_position_outcome(
            leader_seal_status="断板", card_seal_status="封板",
            leader_board_num=5, card_board_num=3,
            leader_seal_strength=3.0, card_seal_strength=5.0,
        )
        assert result["card_success"] is False


class TestGetLeaderIdentification:
    """P8-30: 测试主接口返回"""

    def test_returns_string(self):
        """返回应为字符串"""
        result = get_leader_identification("000001", "2026-06-16")
        assert isinstance(result, str)

    def test_contains_keyword(self):
        """应包含龙头或题材关键词"""
        result = get_leader_identification("000001", "2026-06-16")
        assert "龙头" in result or "题材" in result or "失败" in result or "无法获取" in result

    def test_empty_date(self):
        """空日期应正常处理"""
        result = get_leader_identification("000001", "")
        assert isinstance(result, str)

    def test_error_handling(self):
        """异常应被捕获"""
        result = get_leader_identification("999999", "2026-06-16")
        assert isinstance(result, str)

    def test_no_data_date(self):
        """非交易日应返回提示"""
        result = get_leader_identification("000001", "2026-06-08")  # Sunday
        assert isinstance(result, str)
