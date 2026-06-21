"""Tests for main-force flow metrics and Gate 3 wiring (R3)."""

from unittest.mock import patch

import pytest

from tradingagents.dataflows.a_stock import (
    _classify_main_force_signal,
    _get_main_force_flow_metrics,
    calculate_second_board_score,
)
from tradingagents.logic.trading_hard_logic import (
    HardSignal,
    _main_force_allows_daban,
    _main_force_allows_relay,
    apply_gates,
)


class TestClassifyMainForceSignal:
    def test_weak_outflow(self):
        assert _classify_main_force_signal(-5000.0, 0.0) == "弱势"
        assert _classify_main_force_signal(-6000.0, 10000.0) == "弱势"

    def test_strong_inflow(self):
        assert _classify_main_force_signal(3000.0, 0.0) == "强势"
        assert _classify_main_force_signal(100.0, 8000.0) == "强势"

    def test_neutral(self):
        assert _classify_main_force_signal(-100.0, 1000.0) == "中性"


class TestGetMainForceFlowMetrics:
    def test_daily_match_trade_date(self):
        from tradingagents.dataflows.a_stock import clear_session_cache

        clear_session_cache()
        daily = [
            {"date": "2026-06-14", "main_wan": 100.0},
            {"date": "2026-06-16", "main_wan": -5200.0},
        ]
        with patch(
            "tradingagents.dataflows.a_stock._fetch_em_daily_fund_flow",
            return_value=daily,
        ):
            metrics = _get_main_force_flow_metrics("000001", "2026-06-16")

        assert metrics["main_net_inflow_wan"] == -5200.0
        assert metrics["flow_signal"] == "弱势"
        assert metrics["data_confidence"] == "[确认]"

    def test_no_data_returns_empty(self):
        from tradingagents.dataflows.a_stock import clear_session_cache

        clear_session_cache()
        with patch(
            "tradingagents.dataflows.a_stock._fetch_em_daily_fund_flow",
            return_value=[],
        ), patch(
            "tradingagents.dataflows.a_stock._fetch_em_realtime_main_wan",
            return_value=None,
        ):
            metrics = _get_main_force_flow_metrics("000099", "2026-06-16")

        assert metrics["data_confidence"] == "[无数据]"
        assert metrics["flow_signal"] == ""


class TestMainForceGateHelpers:
    def test_relay_blocked_on_weak_outflow(self):
        signal = HardSignal(
            ticker="000001",
            trade_date="2026-06-16",
            main_force_net_wan=-5200.0,
            main_force_signal="弱势",
            data_sources={"main_force_flow": "[确认]"},
        )
        assert _main_force_allows_relay(signal) is False

    def test_relay_allowed_on_positive_inflow(self):
        signal = HardSignal(
            ticker="000001",
            trade_date="2026-06-16",
            main_force_net_wan=100.0,
            main_force_signal="弱势",
            data_sources={"main_force_flow": "[确认]"},
        )
        assert _main_force_allows_relay(signal) is True

    def test_daban_blocked_on_negative_inflow(self):
        signal = HardSignal(
            ticker="000001",
            trade_date="2026-06-16",
            main_force_net_wan=-100.0,
            main_force_signal="中性",
            data_sources={"main_force_flow": "[确认]"},
        )
        assert _main_force_allows_daban(signal) is False


class TestGate3MainForce:
    def _relay_signal(self, **overrides) -> HardSignal:
        defaults = dict(
            ticker="000001",
            trade_date="2026-06-16",
            emotion_phase="修复",
            emotion_score=55.0,
            can_trade=True,
            market_gate_passed=True,
            in_limitup_pool=True,
            role="题材龙头",
            consecutive_days=2,
            promotion_rate=50.0,
            divergence_score=30,
            is_sealed=True,
            theme_rank=2,
            main_force_net_wan=2000.0,
            main_force_signal="强势",
            data_sources={"main_force_flow": "[确认]"},
        )
        defaults.update(overrides)
        return HardSignal(**defaults)

    def test_second_board_relay_blocked_on_weak_outflow(self):
        signal = self._relay_signal(
            main_force_net_wan=-5200.0,
            main_force_signal="弱势",
        )
        result = apply_gates(signal)
        assert result.action != "接力"
        assert "G3-二板接力" not in result.gates_passed

    def test_second_board_relay_on_strong_inflow(self):
        signal = self._relay_signal()
        result = apply_gates(signal)
        assert result.action == "接力"
        assert result.strategy == "二板接力"
        assert "G3-二板接力" in result.gates_passed

    def test_first_board_daban_blocked_on_outflow(self):
        signal = HardSignal(
            ticker="000001",
            trade_date="2026-06-16",
            emotion_phase="修复",
            emotion_score=58,
            can_trade=True,
            market_gate_passed=True,
            in_limitup_pool=True,
            role="首板候选",
            theme_rank=2,
            consecutive_days=1,
            second_board_score=75,
            seal_ratio=4.5,
            first_limit_time="09:35:00",
            main_force_net_wan=-200.0,
            main_force_signal="中性",
            data_sources={"main_force_flow": "[确认]"},
        )
        result = apply_gates(signal)
        assert result.action != "打板"
        assert "G3-首板打板" not in result.gates_passed


class TestSecondBoardMainForcePenalty:
    def test_weak_main_force_reduces_score(self):
        base = calculate_second_board_score(
            seal_strength=80,
            volume_match=80,
            theme_heat=80,
            board_type="换手",
            market_emotion="修复",
        )
        penalized = calculate_second_board_score(
            seal_strength=80,
            volume_match=80,
            theme_heat=80,
            board_type="换手",
            market_emotion="修复",
            main_force_penalty=-7.0,
        )
        assert penalized == pytest.approx(base - 7.0)
