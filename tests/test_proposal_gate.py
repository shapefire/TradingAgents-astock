"""Tests for proposal_gate clamp (R1)."""

from tradingagents.agents.schemas import ShortTermAction, ShortTermProposal, TraderAction, TraderProposal
from tradingagents.logic.proposal_gate import (
    append_hard_logic_footer,
    clamp_short_term_proposal,
    clamp_trader_proposal,
)
from tradingagents.logic.trading_hard_logic import HardSignal


def _signal(**kwargs) -> HardSignal:
    defaults = {
        "ticker": "000001",
        "trade_date": "2026-06-16",
        "can_trade": True,
        "position_cap": 0.15,
        "action": "打板",
    }
    defaults.update(kwargs)
    return HardSignal(**defaults)


class TestClampShortTermProposal:
    def test_can_trade_false_blocks_aggressive(self):
        proposal = ShortTermProposal(
            action=ShortTermAction.DABAN,
            strategy="首板打板",
            reasoning="test",
            position=0.5,
            entry_price=10.0,
            stop_loss=9.0,
        )
        signal = _signal(can_trade=False, action="回避", position_cap=0.0)
        clamped, notes = clamp_short_term_proposal(proposal, signal)
        assert clamped.action in (ShortTermAction.WATCH, ShortTermAction.AVOID)
        assert clamped.position == 0.0
        assert clamped.entry_price is None
        assert clamped.stop_loss is None
        assert notes

    def test_position_clamp_to_cap(self):
        proposal = ShortTermProposal(
            action=ShortTermAction.DABAN,
            strategy="首板打板",
            reasoning="test",
            position=0.5,
        )
        signal = _signal(position_cap=0.15)
        clamped, notes = clamp_short_term_proposal(proposal, signal)
        assert clamped.position == 0.15
        assert any("clamp" in n.lower() or "仓位" in n for n in notes)

    def test_signal_passive_action_overrides_aggressive(self):
        proposal = ShortTermProposal(
            action=ShortTermAction.RELAY,
            strategy="二板接力",
            reasoning="test",
            position=0.2,
        )
        signal = _signal(action="观望", position_cap=0.05, can_trade=True)
        clamped, notes = clamp_short_term_proposal(proposal, signal)
        assert clamped.action == ShortTermAction.WATCH
        assert clamped.position <= 0.05

    def test_no_change_when_within_bounds(self):
        proposal = ShortTermProposal(
            action=ShortTermAction.DABAN,
            strategy="首板打板",
            reasoning="test",
            position=0.10,
            stop_loss=9.0,
        )
        signal = _signal()
        clamped, notes = clamp_short_term_proposal(proposal, signal)
        assert clamped.position == 0.10
        assert clamped.action == ShortTermAction.DABAN
        assert notes == []


class TestClampTraderProposal:
    def test_buy_downgraded_when_can_trade_false(self):
        proposal = TraderProposal(
            action=TraderAction.BUY,
            reasoning="test",
            position_sizing="20% of portfolio",
            entry_price=10.0,
        )
        signal = _signal(can_trade=False, position_cap=0.0)
        clamped, notes = clamp_trader_proposal(proposal, signal)
        assert clamped.action == TraderAction.HOLD
        assert clamped.entry_price is None

    def test_sizing_clamped_to_cap(self):
        proposal = TraderProposal(
            action=TraderAction.BUY,
            reasoning="test",
            position_sizing="allocate 25%",
        )
        signal = _signal(position_cap=0.15)
        clamped, notes = clamp_trader_proposal(proposal, signal)
        assert "15%" in clamped.position_sizing
        assert notes


class TestAppendFooter:
    def test_footer_includes_cap(self):
        signal = _signal(position_cap=0.15, can_trade=False)
        text = append_hard_logic_footer("body", signal)
        assert "HardLogic Override" in text
        assert "15%" in text
