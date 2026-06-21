"""Unit tests for TradingHardLogic gates (no network)."""

from unittest.mock import patch

import pytest

from tradingagents.logic.trading_hard_logic import (
    HardSignal,
    apply_gates,
    evaluate,
    gate_check_portfolio_rating,
    hard_signal_to_json,
    hard_signal_to_markdown,
)


def _base_signal(**overrides) -> HardSignal:
    defaults = dict(
        ticker="000001",
        trade_date="2026-06-16",
        emotion_phase="修复",
        emotion_score=55.0,
        can_trade=True,
        market_gate_passed=True,
        in_limitup_pool=True,
        consecutive_days=1,
        role="首板候选",
        theme_rank=2,
    )
    defaults.update(overrides)
    return HardSignal(**defaults)


class TestGateIcePoint:
    def test_gate_ice_point_blocks_trade(self):
        signal = _base_signal(emotion_phase="冰点（已确认）")
        result = apply_gates(signal)
        assert result.can_trade is False
        assert result.action in ("观望", "回避")
        assert result.position_cap == 0.0
        assert "冰点确认" in result.veto_reasons

    def test_gate_ice_point_unconfirmed(self):
        signal = _base_signal(emotion_phase="冰点")
        result = apply_gates(signal)
        assert result.can_trade is False
        assert result.action == "观望"


class TestGateFirstBoard:
    def test_gate_first_board_daban(self):
        signal = _base_signal(
            emotion_phase="修复",
            emotion_score=58,
            role="首板候选",
            theme_rank=2,
            consecutive_days=1,
            second_board_score=72,
            seal_ratio=4.5,
            first_limit_time="09:35:00",
        )
        result = apply_gates(signal)
        assert result.can_trade is True
        assert result.action == "打板"
        assert result.position_cap <= 0.15
        assert "G3-首板打板" in result.gates_passed


class TestGateHighDivergence:
    def test_gate_high_divergence_veto(self):
        signal = _base_signal(
            divergence_score=75,
            role="高标",
            consecutive_days=5,
        )
        result = apply_gates(signal)
        assert result.can_trade is False
        assert result.action == "回避"
        assert "高标重度分歧" in result.veto_reasons


class TestGateYiziUnbuyable:
    def test_yizi_unbuyable_veto(self):
        signal = _base_signal(is_yizi_unbuyable=True, role="首板候选")
        result = apply_gates(signal)
        assert result.can_trade is False
        assert "一字不可买" in result.veto_reasons


class TestPortfolioRatingDowngrade:
    def test_portfolio_rating_downgrade(self):
        signal = _base_signal(
            emotion_phase="冰点（已确认）",
            can_trade=False,
            veto_reasons=["冰点确认"],
        )
        rating, reasons = gate_check_portfolio_rating("Buy", signal)
        assert rating == "Hold"
        assert len(reasons) > 0

    def test_buy_allowed_when_can_trade(self):
        signal = _base_signal(can_trade=True, position_cap=0.15)
        rating, reasons = gate_check_portfolio_rating("Buy", signal)
        assert rating == "Buy"
        assert reasons == []

    def test_overweight_downgrade_low_cap(self):
        signal = _base_signal(can_trade=True, position_cap=0.08)
        rating, reasons = gate_check_portfolio_rating("Overweight", signal)
        assert rating == "Hold"
        assert reasons

    def test_many_vetoes_downgrade_to_underweight(self):
        signal = _base_signal(
            can_trade=False,
            veto_reasons=["冰点确认", "解禁重压", "一字不可买"],
        )
        rating, reasons = gate_check_portfolio_rating("Buy", signal)
        assert rating == "Hold"

        signal2 = _base_signal(
            can_trade=True,
            position_cap=0.15,
            veto_reasons=["冰点确认", "解禁重压", "一字不可买"],
        )
        rating2, _ = gate_check_portfolio_rating("Overweight", signal2)
        assert rating2 == "Underweight"


class TestGateUnlockPressure:
    """VS-09: 解禁重压否决"""

    def test_unlock_pressure_veto_blocks_trade(self):
        signal = _base_signal(unlock_pressure_pct=15.0)
        result = apply_gates(signal)
        assert result.can_trade is False
        assert result.action == "回避"
        assert "解禁重压" in result.veto_reasons
        assert "G2-05-解禁重压" in result.gates_passed

    def test_unlock_pressure_zero_no_veto(self):
        signal = _base_signal(unlock_pressure_pct=0.0)
        result = apply_gates(signal)
        assert "解禁重压" not in result.veto_reasons
        assert result.can_trade is True

    def test_unlock_pressure_moderate_no_veto(self):
        signal = _base_signal(unlock_pressure_pct=8.0)
        result = apply_gates(signal)
        assert "解禁重压" not in result.veto_reasons
        assert "G2-解禁压力可控" in result.gates_passed


class TestGateClimaxReduce:
    def test_g1_05_caps_position_on_climax(self):
        signal = _base_signal(
            emotion_phase="高潮（减仓）",
            emotion_score=75.0,
            role="高标",
            consecutive_days=4,
            divergence_score=40,
            break_risk="低",
            theme_rank=2,
        )
        result = apply_gates(signal)
        assert result.can_trade is True
        assert result.position_cap <= 0.20
        assert "G1-05-高潮减仓" in result.gates_passed
        assert "G3-高标接力" in result.gates_passed


class TestUnlockPressureMetrics:
    @patch("tradingagents.dataflows.a_stock._eastmoney_datacenter")
    def test_sums_upcoming_ratios(self, mock_dc):
        from tradingagents.dataflows.a_stock import _get_unlock_pressure_metrics

        mock_dc.return_value = [
            {"FREE_DATE": "2026-06-20", "FREE_RATIO": 6.5, "LIMITED_STOCK_TYPE": "定增"},
            {"FREE_DATE": "2026-06-25", "FREE_RATIO": "5.5%", "LIMITED_STOCK_TYPE": "首发"},
        ]
        result = _get_unlock_pressure_metrics("000001", "2026-06-16", forward_days=30)
        assert result["unlock_pressure_pct"] == 12.0
        assert result["has_data"] is True
        assert result["upcoming_count"] == 2

    @patch("tradingagents.dataflows.a_stock._eastmoney_datacenter")
    def test_empty_returns_zero_no_veto(self, mock_dc):
        from tradingagents.dataflows.a_stock import _get_unlock_pressure_metrics

        mock_dc.return_value = []
        result = _get_unlock_pressure_metrics("000001", "2026-06-16")
        assert result["unlock_pressure_pct"] == 0.0
        assert result["has_data"] is False


class TestEvaluateUnlockPressure:
    @patch("tradingagents.logic.trading_hard_logic._get_unlock_pressure_metrics")
    @patch("tradingagents.logic.trading_hard_logic.evaluate_market")
    @patch("tradingagents.logic.trading_hard_logic._get_limitup_stocks")
    @patch("tradingagents.logic.trading_hard_logic._get_limitup_by_theme")
    def test_evaluate_wires_unlock_pressure(
        self, mock_themes, mock_limitup, mock_market, mock_unlock,
    ):
        mock_market.return_value = {
            "emotion_phase": "修复",
            "emotion_score": 55.0,
            "yesterday_performance": {"avg_return": 1.0},
            "market_breadth": {"breadth_signal": "正常"},
        }
        mock_limitup.return_value = []
        mock_themes.return_value = {}
        mock_unlock.return_value = {
            "unlock_pressure_pct": 12.5,
            "has_data": True,
            "upcoming_count": 1,
            "events": [{"date": "2026-06-20", "ratio_pct": 12.5}],
        }

        signal = evaluate("000001", "2026-06-16")
        assert signal.unlock_pressure_pct == 12.5
        assert signal.can_trade is False
        assert "解禁重压" in signal.veto_reasons
        assert signal.data_sources.get("unlock_pressure_pct") == "[确认]"

    @patch("tradingagents.logic.trading_hard_logic._get_unlock_pressure_metrics")
    @patch("tradingagents.logic.trading_hard_logic.evaluate_market")
    @patch("tradingagents.logic.trading_hard_logic._get_limitup_stocks")
    @patch("tradingagents.logic.trading_hard_logic._get_limitup_by_theme")
    def test_evaluate_no_unlock_data_defaults_zero(
        self, mock_themes, mock_limitup, mock_market, mock_unlock,
    ):
        mock_market.return_value = {
            "emotion_phase": "修复",
            "emotion_score": 55.0,
            "yesterday_performance": {"avg_return": 1.0},
            "market_breadth": {"breadth_signal": "正常"},
        }
        mock_limitup.return_value = [
            {"code": "000001", "consecutive_days": 1, "name": "平安", "limit_type": "换手"},
        ]
        mock_themes.return_value = {}
        mock_unlock.return_value = {
            "unlock_pressure_pct": 0.0,
            "has_data": False,
            "upcoming_count": 0,
            "events": [],
        }

        signal = evaluate("000001", "2026-06-16")
        assert signal.unlock_pressure_pct == 0.0
        assert "解禁重压" not in signal.veto_reasons
        assert signal.data_sources.get("unlock_pressure_pct") == "[无数据]"


class TestHardSignalSerialization:
    def test_to_json_roundtrip(self):
        signal = _base_signal()
        data = hard_signal_to_json(signal)
        assert "000001" in data
        assert "emotion_phase" in data

    def test_to_markdown_contains_key_fields(self):
        signal = apply_gates(_base_signal(
            seal_ratio=4.5,
            data_sources={"seal_ratio": "[确认]"},
        ))
        md = hard_signal_to_markdown(signal)
        assert "硬逻辑信号" in md
        assert "情绪阶段" in md
        assert "4.50% [确认]" in md
        assert "个股全景" in md


class TestEvaluatePanorama:
    @patch("tradingagents.logic.trading_hard_logic._get_lhb_seat_metrics")
    @patch("tradingagents.logic.trading_hard_logic.evaluate_market")
    @patch("tradingagents.logic.trading_hard_logic._get_limitup_stocks")
    @patch("tradingagents.logic.trading_hard_logic._get_limitup_by_theme")
    def test_evaluate_populates_panorama_fields(
        self, mock_themes, mock_limitup, mock_market, mock_lhb,
    ):
        mock_market.return_value = {
            "emotion_phase": "修复",
            "emotion_score": 55.0,
            "yesterday_performance": {"avg_return": 1.0},
            "market_breadth": {"breadth_signal": "正常"},
        }
        mock_limitup.return_value = [
            {
                "code": "000001",
                "name": "平安",
                "consecutive_days": 1,
                "limit_type": "换手",
                "reason": "AI概念",
                "turnover_rate": 0.08,
                "amount": 1e9,
                "circulation_mv": 5e9,
                "first_limit_time": "09:35:00",
            },
        ]
        mock_themes.return_value = {
            "AI概念": [{"code": "000001", "board_num": 1}],
        }
        mock_lhb.return_value = {
            "hot_money_buy": False,
            "institutional_net_wan": 0.0,
            "has_data": False,
        }

        with patch(
            "tradingagents.logic.trading_hard_logic._get_unlock_pressure_metrics",
            return_value={"unlock_pressure_pct": 0.0, "has_data": False},
        ):
            with patch(
                "tradingagents.logic.trading_hard_logic._get_stock_seal_info",
                return_value={
                    "seal_strength_score": 70,
                    "board_type": "换手",
                    "seal_ratio": 4.0,
                    "data_sources": {},
                },
            ):
                with patch(
                    "tradingagents.dataflows.a_stock._calculate_theme_purity",
                    return_value=80,
                ):
                    with patch(
                        "tradingagents.dataflows.a_stock._get_historical_activity",
                        return_value=60,
                    ):
                        signal = evaluate("000001", "2026-06-16")

        assert signal.second_board_score >= 0
        md = hard_signal_to_markdown(signal)
        assert "首板二板预期" in md


class TestGate2StockTradability:
    def test_g2_03_20cm_reduces_position_cap(self):
        signal = _base_signal(
            emotion_phase="修复",
            emotion_score=58,
            role="首板候选",
            theme_rank=2,
            consecutive_days=1,
            second_board_score=75,
            seal_ratio=3.5,
            first_limit_time="09:30:00",
            is_20cm_board=True,
            ticker="300750",
        )
        result = apply_gates(signal)
        assert result.can_trade is True
        assert result.action == "打板"
        assert result.position_cap <= 0.075  # 0.15 * 0.5
        assert "G2-03-20cm折算" in result.gates_passed

    def test_g2_04_large_cap_forbids_daban(self):
        signal = _base_signal(
            emotion_phase="修复",
            emotion_score=58,
            role="首板候选",
            theme_rank=2,
            consecutive_days=1,
            second_board_score=75,
            seal_ratio=5.0,
            first_limit_time="09:30:00",
            circulation_mv=35e9,
        )
        result = apply_gates(signal)
        assert result.action != "打板"
        assert "G2-04-大市值禁打板" in result.gates_passed

    def test_g2_06_regulatory_veto(self):
        signal = _base_signal(has_regulatory_alert=True)
        result = apply_gates(signal)
        assert result.can_trade is False
        assert "监管异动" in result.veto_reasons


class TestGate3Strategies:
    def test_second_board_relay(self):
        signal = _base_signal(
            emotion_phase="修复",
            role="题材龙头",
            consecutive_days=2,
            promotion_rate=50.0,
            divergence_score=30,
            is_sealed=True,
            theme_rank=2,
        )
        result = apply_gates(signal)
        assert result.action == "接力"
        assert result.strategy == "二板接力"
        assert result.position_cap <= 0.20
        assert "G3-二板接力" in result.gates_passed

    def test_leader_low_buy(self):
        signal = _base_signal(
            in_limitup_pool=False,
            role="断板龙头",
            change_pct=-7.0,
            theme_rank=3,
            emotion_phase="修复",
        )
        result = apply_gates(signal)
        assert result.action == "低吸"
        assert result.strategy == "龙头低吸"
        assert "G3-龙头低吸" in result.gates_passed

    def test_avoid_high_break_risk(self):
        signal = _base_signal(
            role="高标",
            consecutive_days=5,
            break_risk="高",
            divergence_score=40,
        )
        result = apply_gates(signal)
        assert result.action == "回避"
        assert "G3-回避" in result.gates_passed


class TestIs20cmBoard:
    def test_300_is_20cm(self):
        from tradingagents.logic.trading_hard_logic import _is_20cm_board

        assert _is_20cm_board("300750") is True

    def test_688_is_20cm(self):
        from tradingagents.logic.trading_hard_logic import _is_20cm_board

        assert _is_20cm_board("688001") is True

    def test_main_board_not_20cm(self):
        from tradingagents.logic.trading_hard_logic import _is_20cm_board

        assert _is_20cm_board("000001") is False


class TestPortfolioManagerGateWiring:
    def test_pm_source_has_gate_check(self):
        import inspect

        from tradingagents.agents.managers import portfolio_manager

        source = inspect.getsource(portfolio_manager.create_portfolio_manager)
        assert "gate_check_portfolio_rating" in source
        assert "hard_signal_from_json" in source
