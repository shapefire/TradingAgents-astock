"""Tests for MarketContext batch evaluate (R4)."""

from unittest.mock import patch

from tradingagents.logic.trading_hard_logic import (
    HardSignal,
    MarketContext,
    apply_gates,
    build_market_context,
    evaluate,
    evaluate_with_context,
)


def _sample_context(trade_date: str = "2026-06-16") -> MarketContext:
    return MarketContext(
        trade_date=trade_date,
        metrics={
            "emotion_phase": "修复",
            "emotion_score": 55.0,
            "yesterday_performance": {
                "avg_return": 1.0,
                "promotion_rates": {1: 45.0},
            },
            "market_breadth": {"breadth_signal": "正常", "ad_ratio": 1.0},
        },
        limitup_stocks=[
            {
                "code": "000001",
                "name": "平安",
                "consecutive_days": 1,
                "limit_type": "换手",
                "reason": "AI",
                "turnover_rate": 0.05,
                "first_limit_time": "09:35:00",
                "circulation_mv": 5e9,
                "amount": 2e8,
                "change_pct": 10.0,
            },
        ],
        theme_map={"AI": [{"code": "000001", "board_num": 1}]},
        theme_ranks={"AI": 1},
        max_board=1,
    )


class TestBuildMarketContext:
    @patch("tradingagents.dataflows.a_stock._build_lhb_seat_metrics_map")
    @patch("tradingagents.logic.trading_hard_logic._get_limitup_by_theme")
    @patch("tradingagents.logic.trading_hard_logic._get_recent_emotion_history")
    @patch("tradingagents.logic.trading_hard_logic._get_northbound_flow_signal")
    @patch("tradingagents.logic.trading_hard_logic._get_market_breadth")
    @patch("tradingagents.logic.trading_hard_logic._calculate_yesterday_performance")
    @patch("tradingagents.logic.trading_hard_logic._get_yesterday_limitup_performance")
    @patch("tradingagents.logic.trading_hard_logic._get_limitdown_stocks")
    @patch("tradingagents.logic.trading_hard_logic._get_limitup_stocks")
    def test_builds_shared_snapshot(
        self,
        mock_limitup,
        mock_limitdown,
        mock_yesterday_raw,
        mock_yesterday_perf,
        mock_breadth,
        mock_northbound,
        mock_recent,
        mock_themes,
        mock_lhb_map,
    ):
        limitup = [{"code": "000001", "consecutive_days": 1, "name": "A"}]
        mock_limitup.return_value = limitup
        mock_limitdown.return_value = []
        mock_yesterday_raw.return_value = {}
        mock_yesterday_perf.return_value = {"avg_return": 0.0}
        mock_breadth.return_value = {"breadth_signal": "正常", "ad_ratio": 1.0}
        mock_northbound.return_value = {}
        mock_recent.return_value = []
        mock_themes.return_value = {"AI": limitup}
        mock_lhb_map.return_value = {}

        ctx = build_market_context("2026-06-16")

        assert ctx.trade_date == "2026-06-16"
        assert ctx.limitup_stocks == limitup
        assert ctx.theme_ranks == {"AI": 1}
        mock_lhb_map.assert_called_once_with("2026-06-16")


class TestEvaluateWithContext:
    @patch("tradingagents.logic.trading_hard_logic._get_main_force_flow_metrics")
    @patch("tradingagents.logic.trading_hard_logic._get_regulatory_alert_metrics")
    @patch("tradingagents.logic.trading_hard_logic._calculate_auction_strength_metrics")
    @patch("tradingagents.logic.trading_hard_logic._get_unlock_pressure_metrics")
    @patch("tradingagents.logic.trading_hard_logic._get_lhb_seat_metrics")
    @patch("tradingagents.logic.trading_hard_logic._get_stock_seal_info")
    def test_matches_evaluate_with_same_context(
        self,
        mock_seal,
        mock_lhb,
        mock_unlock,
        mock_auction,
        mock_reg,
        mock_flow,
    ):
        mock_unlock.return_value = {
            "unlock_pressure_pct": 0.0,
            "has_data": False,
        }
        mock_auction.return_value = {
            "auction_strength_score": -1,
            "auction_strength_level": "",
            "data_confidence": "[估算]",
        }
        mock_reg.return_value = {"has_regulatory_alert": False}
        mock_flow.return_value = {
            "main_net_inflow_wan": 100.0,
            "flow_signal": "强势",
            "data_confidence": "[确认]",
        }
        mock_lhb.return_value = {"hot_money_buy": False, "institutional_net_wan": 0}
        mock_seal.return_value = {
            "seal_ratio": 4.5,
            "seal_strength_score": 80,
            "board_type": "换手",
            "data_sources": {"seal_ratio": "[确认]"},
        }

        ctx = _sample_context()

        with patch(
            "tradingagents.logic.trading_hard_logic.build_market_context",
            return_value=ctx,
        ):
            single = evaluate("000001", "2026-06-16")

        batch = evaluate_with_context("000001", ctx)

        assert single.ticker == batch.ticker
        assert single.trade_date == batch.trade_date
        assert single.emotion_phase == batch.emotion_phase
        assert single.role == batch.role
        assert single.action == batch.action
        assert single.strategy == batch.strategy
        assert single.position_cap == batch.position_cap
        assert single.can_trade == batch.can_trade


class TestBatchScanContextReuse:
    @patch("tradingagents.logic.trading_hard_logic.evaluate_with_context")
    @patch("tradingagents.logic.trading_hard_logic.build_market_context")
    def test_scan_builds_context_once(self, mock_build, mock_eval_ctx):
        from cli.scan_short_term import main

        ctx = _sample_context()
        mock_build.return_value = ctx
        mock_eval_ctx.side_effect = lambda code, _ctx: apply_gates(
            HardSignal(
                ticker=code,
                trade_date=ctx.trade_date,
                emotion_phase="修复",
                can_trade=True,
                role="首板候选",
                theme_rank=1,
            )
        )

        candidates = [
            {"code": f"00000{i}", "name": f"S{i}", "second_board_score": 70 + i}
            for i in range(1, 21)
        ]

        with patch(
            "cli.scan_short_term.scan_first_board_candidates",
            return_value=candidates,
        ), patch("cli.scan_short_term.clear_session_cache"), patch(
            "cli.scan_short_term.console"
        ), patch("cli.scan_short_term._print_em_interval_hint"):
            main(date="2026-06-16", top=20, min_score=60)

        mock_build.assert_called_once_with("2026-06-16")
        assert mock_eval_ctx.call_count == 20
        for call in mock_eval_ctx.call_args_list:
            assert call.args[1] is ctx
