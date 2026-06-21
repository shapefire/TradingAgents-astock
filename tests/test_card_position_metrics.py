"""Tests for card position metrics (R2)."""

from unittest.mock import patch

from tradingagents.dataflows.a_stock import (
    _get_card_position_metrics,
    _get_same_theme_performance,
)
from tradingagents.logic.trading_hard_logic import apply_gates, HardSignal


class TestSameThemePerformance:
    def test_average_change_pct(self):
        theme_map = {
            "AI": [
                {"code": "000001", "change_pct": 10.0},
                {"code": "000002", "change_pct": 8.0},
            ],
        }
        pool = [
            {"code": "000001", "change_pct": 10.0, "reason": "AI"},
            {"code": "000002", "change_pct": 8.0, "reason": "AI"},
        ]
        with patch(
            "tradingagents.dataflows.a_stock._get_limitup_by_theme",
            return_value=theme_map,
        ), patch(
            "tradingagents.dataflows.a_stock._get_limitup_stocks",
            return_value=pool,
        ):
            avg = _get_same_theme_performance("AI", "2026-06-16", exclude_code="000001")
        assert avg == 8.0


class TestCardPositionMetrics:
    def test_broken_leader_card_success(self):
        theme_stocks = [
            {
                "code": "000001",
                "name": "A",
                "board_num": 3,
                "limit_type": "断板",
                "seal_strength": 0.02,
                "first_limit_time": "09:30",
            },
            {
                "code": "000002",
                "name": "B",
                "board_num": 3,
                "limit_type": "换手",
                "seal_strength": 0.05,
                "first_limit_time": "09:35",
            },
        ]
        pool = [
            {
                "code": "000001",
                "consecutive_days": 3,
                "limit_type": "断板",
                "reason": "AI",
                "change_pct": -7.0,
            },
            {
                "code": "000002",
                "consecutive_days": 3,
                "limit_type": "换手",
                "reason": "AI",
                "change_pct": 10.0,
            },
        ]
        theme_map = {"AI": theme_stocks}

        with patch(
            "tradingagents.dataflows.a_stock._get_limitup_by_theme",
            return_value=theme_map,
        ), patch(
            "tradingagents.dataflows.a_stock._get_limitup_stocks",
            return_value=pool,
        ), patch(
            "tradingagents.dataflows.a_stock._get_stock_seal_info",
            return_value={"seal_ratio": 3.0, "seal_strength_score": 50},
        ):
            metrics = _get_card_position_metrics("000001", "2026-06-16", theme="AI")

        assert metrics["card_position_exists"]
        assert metrics["card_position_success"]


class TestGateDipBuyCardPosition:
    def test_card_success_blocks_dip_buy(self):
        signal = HardSignal(
            ticker="000001",
            trade_date="2026-06-16",
            emotion_phase="修复",
            emotion_score=55.0,
            in_limitup_pool=False,
            consecutive_days=0,
            role="断板龙头",
            theme="AI",
            theme_rank=2,
            change_pct=-7.0,
            card_position_success=True,
            card_position_exists=True,
        )
        result = apply_gates(signal)
        strategies = [g for g in result.gates_passed if g.startswith("G3-")]
        assert "G3-龙头低吸" not in strategies
