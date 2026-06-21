"""P3 scan mode and auction strength tests (no network)."""

from unittest.mock import patch

import pytest

from tradingagents.dataflows.a_stock import (
    _calculate_auction_strength_metrics,
    _get_regulatory_alert_metrics,
    scan_first_board_candidates,
)
from tradingagents.logic.trading_hard_logic import (
    AUCTION_STRENGTH_MIN_DABAN,
    HardSignal,
    _match_gate3_strategies,
)


@pytest.mark.unit
class TestAuctionStrength:
    def test_early_seal_scores_high(self):
        pool = {
            "code": "000001",
            "first_limit_time": "09:32:00",
            "first_limit_time_confirmed": True,
            "limit_type": "换手",
            "open_times": 0,
            "change_pct": 10.0,
            "turnover_rate": 0.05,
            "circulation_mv": 5e9,
            "amount": 2e8,
            "seal_amount": 5e7,
        }
        with patch(
            "tradingagents.dataflows.a_stock._get_stock_seal_info",
            return_value={"seal_strength_score": 80, "seal_ratio": 5.0, "data_sources": {}},
        ):
            metrics = _calculate_auction_strength_metrics("000001", "2026-06-16", pool)
        assert metrics["auction_strength_score"] >= 70
        assert metrics["auction_strength_level"] == "强"
        assert metrics["data_confidence"] == "[确认]"

    def test_regulatory_alert_keyword_match(self):
        fake_ann = [{
            "announcementTime": 1717200000000,
            "announcementTitle": "关于股票交易异常波动的公告",
        }]
        with patch(
            "tradingagents.dataflows.a_stock._fetch_cninfo_announcements_list",
            return_value=fake_ann,
        ):
            metrics = _get_regulatory_alert_metrics("000001", "2024-06-01", lookback_days=60)
        assert metrics["has_regulatory_alert"] is True
        assert metrics["alert_count"] >= 1


@pytest.mark.unit
class TestGate3AuctionFilter:
    def test_daban_requires_auction_strength(self):
        signal = HardSignal(
            ticker="000001",
            trade_date="2026-06-16",
            emotion_phase="修复",
            emotion_score=55,
            role="首板候选",
            consecutive_days=1,
            second_board_score=75,
            seal_ratio=5.0,
            first_limit_time="09:35:00",
            theme_rank=2,
            auction_strength_score=30,
        )
        matches = _match_gate3_strategies(signal, {})
        daban = [m for m in matches if m.action == "打板"]
        assert not daban

        signal.auction_strength_score = AUCTION_STRENGTH_MIN_DABAN
        matches = _match_gate3_strategies(signal, {})
        daban = [m for m in matches if m.action == "打板"]
        assert daban


@pytest.mark.unit
class TestScanFirstBoardCandidates:
    @patch("tradingagents.dataflows.a_stock._build_scored_first_board_stocks")
    def test_scan_filters_and_sorts(self, mock_build):
        mock_build.return_value = (
            [
                {"code": "000001", "name": "A", "second_board_score": 80},
                {"code": "000002", "name": "B", "second_board_score": 55},
                {"code": "000003", "name": "C", "second_board_score": 72},
            ],
            "修复",
            {},
        )
        result = scan_first_board_candidates("2026-06-16", min_score=60)
        assert len(result) == 2
        assert result[0]["code"] == "000001"
        assert result[1]["code"] == "000003"
