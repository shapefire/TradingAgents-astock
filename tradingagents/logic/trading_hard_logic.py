"""Trading hard logic layer — deterministic gates between data scores and LLM decisions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from tradingagents.dataflows.a_stock import (
    _calculate_emotion_metrics,
    _calculate_yesterday_performance,
    _get_limitdown_stocks,
    _get_limitup_by_theme,
    _get_limitup_stocks,
    _get_market_breadth,
    _get_northbound_flow_signal,
    _get_recent_emotion_history,
    _get_stock_realtime_quote,
    _get_stock_seal_info,
    _get_unlock_pressure_metrics,
    _get_yesterday_limitup_performance,
    _calculate_auction_strength_metrics,
    _get_regulatory_alert_metrics,
    _non_st_limitup_stocks,
    calculate_second_board_score,
    _calculate_volume_match_score,
    _calculate_divergence_score,
    _calculate_break_risk_level,
    _get_lhb_seat_metrics,
    _get_card_position_metrics,
    _get_same_theme_performance,
    _get_main_force_flow_metrics,
)
from tradingagents.dataflows.utils import safe_ticker_component

ICE_POINT_PHASES = frozenset({"冰点", "冰点（已确认）"})
RETREAT_PHASES = frozenset({"退潮", "退潮（确认）"})
RELAY_FORBIDDEN_PHASES = ICE_POINT_PHASES | RETREAT_PHASES | {"低迷"}
REPAIR_PHASES = frozenset({"修复", "修复（可操作）"})
CLIMAX_PHASES = frozenset({"高潮", "高潮（减仓）"})
WARMING_PHASES = frozenset({"升温"})

SEAL_RATIO_THRESHOLD_DABAN = 3.0
FIRST_LIMIT_TIME_DABAN = "10:30"
AUCTION_STRENGTH_MIN_DABAN = 50
CIRC_MV_DABAN_FORBIDDEN = 30e9  # 300亿
SEAL_THRESHOLD_20CM_MULT = 0.8
POSITION_20CM_MULT = 0.5


@dataclass
class HardSignal:
    ticker: str
    trade_date: str

    emotion_phase: str = "修复"
    emotion_score: float = 50.0
    breadth_signal: str = "正常"
    yesterday_limitup_avg_return: float = 0.0
    can_trade: bool = True
    market_gate_passed: bool = True

    in_limitup_pool: bool = False
    consecutive_days: int = 0
    role: str = "无关"
    theme: str = ""
    theme_rank: int = 0
    second_board_score: int = -1
    leader_score: int = -1
    divergence_score: int = -1
    break_risk: str = "不适用"
    seal_ratio: float = -1.0
    is_yizi_unbuyable: bool = False
    is_20cm_board: bool = False
    circulation_mv: float = 0.0
    first_limit_time: str = ""
    turnover_rate: float = 0.0
    change_pct: float = 0.0
    is_sealed: bool = True
    promotion_rate: float = 0.0
    ad_ratio: float = 1.0
    card_position_exists: bool = False
    card_position_success: bool = False
    card_position_threat: str = "无"

    unlock_pressure_pct: float = 0.0
    has_regulatory_alert: bool = False
    st_flag: bool = False

    auction_strength_score: int = -1
    auction_strength_level: str = ""

    main_force_net_wan: float = 0.0
    main_force_signal: str = ""

    action: str = "观望"
    position_cap: float = 0.0
    strategy: str = ""
    veto_reasons: list[str] = field(default_factory=list)
    gates_passed: list[str] = field(default_factory=list)
    confidence: str = "medium"

    data_sources: dict = field(default_factory=dict)


def _normalize_ticker(ticker: str) -> str:
    raw = ticker.split(".")[0] if "." in ticker else ticker
    return safe_ticker_component(raw)


def _is_20cm_board(code: str) -> bool:
    """创业板(300) / 科创板(688) 20cm 涨跌停板。"""
    return code.startswith("300") or code.startswith("688")


def _promotion_rate_for_board(consecutive_days: int, promotion_rates: dict) -> float:
    """取该连板数对应的昨日晋级率（如 2 板接力看 1→2 晋级率）。"""
    if consecutive_days >= 2:
        return float(promotion_rates.get(consecutive_days - 1, 0))
    return float(promotion_rates.get(1, 0))


def _compute_confidence(data_sources: dict) -> str:
    low_fields = ("seal_ratio", "first_limit_time", "open_times")
    low_count = sum(
        1 for f in low_fields
        if data_sources.get(f) in ("[估算]", "[无数据]")
    )
    if low_count >= 3:
        return "low"
    confirmed = sum(1 for v in data_sources.values() if v == "[确认]")
    if confirmed >= 3 and low_count == 0:
        return "high"
    return "medium"


@dataclass
class MarketContext:
    """Shared market snapshot for batch evaluate (one fetch per scan batch)."""

    trade_date: str
    metrics: dict
    limitup_stocks: list[dict]
    theme_map: dict[str, list[dict]]
    theme_ranks: dict[str, int]
    max_board: int


@dataclass
class _StrategyMatch:
    action: str
    strategy: str
    position_cap: float
    gate_id: str


def _compute_theme_ranks_from_map(theme_map: dict[str, list[dict]]) -> dict[str, int]:
    theme_scores: list[tuple[str, float]] = []
    for theme_name, stocks in theme_map.items():
        count = len(stocks)
        highest = max((s.get("consecutive_days", 0) for s in stocks), default=0)
        score = min(100, count * 8 + highest * 15)
        theme_scores.append((theme_name, score))
    theme_scores.sort(key=lambda x: x[1], reverse=True)
    return {name: i + 1 for i, (name, _) in enumerate(theme_scores)}


def _compute_theme_ranks(trade_date: str) -> dict[str, int]:
    return _compute_theme_ranks_from_map(_get_limitup_by_theme(trade_date))


def build_market_context(trade_date: str = "") -> MarketContext:
    """Fetch shared market data once for batch evaluate / scan."""
    if not trade_date or not trade_date.strip():
        trade_date = datetime.now().strftime("%Y-%m-%d")

    limitup = _get_limitup_stocks(trade_date)
    limitdown = _get_limitdown_stocks(trade_date)
    yesterday_raw = _get_yesterday_limitup_performance(trade_date)
    yesterday_perf = _calculate_yesterday_performance(yesterday_raw)
    breadth = _get_market_breadth(trade_date)
    northbound = _get_northbound_flow_signal(trade_date)
    recent = _get_recent_emotion_history(trade_date, days=3)

    metrics = _calculate_emotion_metrics(
        limitup,
        limitdown,
        yesterday_perf,
        breadth,
        northbound,
        recent_emotion_history=recent,
        trade_date=trade_date,
    )

    theme_map = _get_limitup_by_theme(trade_date)
    theme_ranks = _compute_theme_ranks_from_map(theme_map)
    non_st = _non_st_limitup_stocks(limitup) or []
    max_board = max((s.get("consecutive_days", 0) for s in non_st), default=0)

    from tradingagents.dataflows.a_stock import _build_lhb_seat_metrics_map

    _build_lhb_seat_metrics_map(trade_date)

    return MarketContext(
        trade_date=trade_date,
        metrics=metrics,
        limitup_stocks=limitup,
        theme_map=theme_map,
        theme_ranks=theme_ranks,
        max_board=max_board,
    )


def evaluate_market(trade_date: str = "") -> dict:
    """Aggregate market-wide emotion metrics."""
    return build_market_context(trade_date).metrics


def _resolve_stock_in_pool(code: str, limitup_stocks: list[dict]) -> dict | None:
    for stock in limitup_stocks:
        if stock.get("code") == code:
            return stock
    return None


def _resolve_stock_in_pool_by_date(code: str, trade_date: str) -> dict | None:
    return _resolve_stock_in_pool(code, _get_limitup_stocks(trade_date))


def _resolve_role(
    code: str,
    stock: dict | None,
    emotion_phase: str,
    theme_rank: int,
    max_board: int,
) -> str:
    if not stock:
        return "无关"
    boards = stock.get("consecutive_days", 0)
    name = stock.get("name", "")
    if "ST" in name.upper():
        return "ST"
    if boards >= max_board and max_board >= 3:
        return "总龙头" if boards == max_board else "高标"
    if boards == 1:
        return "首板候选"
    if emotion_phase in RELAY_FORBIDDEN_PHASES and boards >= 2:
        return "跟风"
    if theme_rank <= 3 and boards >= 2:
        return "题材龙头"
    if boards >= 2:
        return "高标"
    return "跟风"


def evaluate_with_context(ticker: str, ctx: MarketContext) -> HardSignal:
    """Evaluate hard trading logic using a pre-built market context."""
    trade_date = ctx.trade_date
    code = _normalize_ticker(ticker)
    metrics = ctx.metrics
    yp = metrics.get("yesterday_performance", {})
    mb = metrics.get("market_breadth", {})

    pool_stock = _resolve_stock_in_pool(code, ctx.limitup_stocks)
    theme_ranks = ctx.theme_ranks
    max_board = ctx.max_board

    theme = ""
    theme_rank = 0
    if pool_stock:
        raw_reason = pool_stock.get("reason", "")
        reasons = [r.strip() for r in raw_reason.replace("，", "+").split("+") if r.strip()]
        if reasons:
            from tradingagents.dataflows.a_stock import _normalize_theme_name

            theme = _normalize_theme_name(reasons[0])
            theme_rank = theme_ranks.get(theme, 0)

    st_flag = pool_stock is not None and "ST" in pool_stock.get("name", "").upper()
    consecutive = pool_stock.get("consecutive_days", 0) if pool_stock else 0
    turnover = (pool_stock or {}).get("turnover_rate", 0) or 0
    limit_type = (pool_stock or {}).get("limit_type", "")
    circulation_mv = float((pool_stock or {}).get("circulation_mv", 0) or 0)
    first_limit_time = (pool_stock or {}).get("first_limit_time", "") or ""
    change_pct = float((pool_stock or {}).get("change_pct", 0) or 0)
    is_sealed = pool_stock is not None and limit_type != "断板"
    is_yizi_unbuyable = (
        pool_stock is not None
        and limit_type == "一字"
        and turnover < 0.005
    )
    is_20cm = _is_20cm_board(code)

    if not pool_stock:
        quote = _get_stock_realtime_quote(code)
        if quote:
            change_pct = float(quote.get("change_pct", 0) or 0)
            if not circulation_mv and quote.get("float_mcap_yi"):
                circulation_mv = float(quote["float_mcap_yi"]) * 1e8
            turnover = float(quote.get("turnover_pct", 0) or 0) / 100.0

    promotion_rates = yp.get("promotion_rates", {})
    promotion_rate = _promotion_rate_for_board(consecutive, promotion_rates)

    role = _resolve_role(code, pool_stock, metrics["emotion_phase"], theme_rank, max_board)
    if (
        not pool_stock
        and role == "无关"
        and -9 <= change_pct <= -5
        and theme_rank > 0
        and theme_rank <= 5
    ):
        role = "断板龙头"

    seal_ratio = -1.0
    data_sources: dict[str, str] = {}
    if pool_stock:
        seal_info = _get_stock_seal_info(pool_stock)
        seal_ratio = float(seal_info.get("seal_ratio", -1))
        data_sources = dict(seal_info.get("data_sources") or {})
        if pool_stock.get("first_limit_time_confirmed"):
            data_sources["first_limit_time"] = "[确认]"
        elif first_limit_time:
            data_sources["first_limit_time"] = "[估算]"

    unlock_metrics = _get_unlock_pressure_metrics(code, trade_date, forward_days=30)
    unlock_pressure_pct = float(unlock_metrics.get("unlock_pressure_pct", 0.0))
    if unlock_metrics.get("has_data"):
        data_sources["unlock_pressure_pct"] = "[确认]"
    else:
        data_sources["unlock_pressure_pct"] = "[无数据]"

    auction_metrics = _calculate_auction_strength_metrics(code, trade_date, pool_stock)
    auction_strength_score = int(auction_metrics.get("auction_strength_score", -1))
    auction_strength_level = str(auction_metrics.get("auction_strength_level", ""))
    data_sources["auction_strength"] = auction_metrics.get("data_confidence", "[估算]")

    regulatory_metrics = _get_regulatory_alert_metrics(code, trade_date)
    has_regulatory_alert = bool(regulatory_metrics.get("has_regulatory_alert"))
    if has_regulatory_alert:
        data_sources["regulatory_alert"] = "[确认]"

    main_force_metrics = _get_main_force_flow_metrics(code, trade_date)
    main_force_net_wan = float(main_force_metrics.get("main_net_inflow_wan", 0.0))
    main_force_signal = str(main_force_metrics.get("flow_signal", ""))
    if main_force_metrics.get("data_confidence"):
        data_sources["main_force_flow"] = main_force_metrics["data_confidence"]

    card_position_exists = False
    card_position_success = False
    card_position_threat = "无"
    if theme or (pool_stock and consecutive >= 2):
        card_metrics = _get_card_position_metrics(code, trade_date, theme=theme)
        card_position_exists = bool(card_metrics.get("card_position_exists"))
        card_position_success = bool(card_metrics.get("card_position_success"))
        card_position_threat = str(card_metrics.get("card_position_threat", "无"))
        if card_metrics.get("data_confidence"):
            data_sources["card_position"] = card_metrics["data_confidence"]

    second_board_score = -1
    divergence_score = -1
    break_risk = "不适用"
    lhb_metrics = _get_lhb_seat_metrics(code, trade_date)

    if pool_stock and consecutive == 1:
        seal_info = _get_stock_seal_info(pool_stock)
        theme_map = ctx.theme_map
        theme_stocks = theme_map.get(theme, [])
        from tradingagents.dataflows.a_stock import (
            _calculate_theme_purity,
            _get_historical_activity,
        )

        purity = _calculate_theme_purity(code, theme, theme_stocks, theme_map) if theme else 0
        activity = _get_historical_activity(code)
        theme_heat = 0.0
        if theme:
            count = len(theme_stocks)
            highest = max((s.get("board_num", 0) for s in theme_stocks), default=0)
            theme_heat = min(100, count * 8 + highest * 15)
        volume_score = _calculate_volume_match_score(
            turnover_rate=pool_stock.get("turnover_rate", 0),
            amount=pool_stock.get("amount", 0),
        )
        hot_money_boost = 10.0 if lhb_metrics.get("hot_money_buy") else 0.0
        main_force_penalty = -7.0 if main_force_signal == "弱势" else 0.0
        second_board_score = int(calculate_second_board_score(
            seal_strength=seal_info.get("seal_strength_score", 0),
            volume_match=volume_score,
            theme_heat=theme_heat,
            board_type=seal_info.get("board_type", pool_stock.get("limit_type", "换手")),
            market_emotion=metrics.get("emotion_phase", "修复"),
            circulation_mv=pool_stock.get("circulation_mv", 0),
            first_limit_time=pool_stock.get("first_limit_time", ""),
            theme_purity=purity,
            historical_activity=activity,
            hot_money_boost=hot_money_boost,
            main_force_penalty=main_force_penalty,
        ))

    if pool_stock and consecutive >= 3:
        seal_info = _get_stock_seal_info(pool_stock)
        open_count = int(pool_stock.get("open_times", 0) or 0)
        seal_stable = pool_stock.get("limit_type") != "断板"
        div = _calculate_divergence_score(
            seal_stable=seal_stable,
            open_count=open_count,
            seal_ratio=float(seal_info.get("seal_ratio", 0)),
        )
        divergence_score = int(div.get("divergence_score", -1))
        same_theme_perf = (
            _get_same_theme_performance(theme, trade_date, exclude_code=code)
            if theme
            else 0.0
        )
        risk = _calculate_break_risk_level(
            board_num=consecutive,
            seal_status="封板" if seal_stable else "断板",
            open_count=open_count,
            divergence_score=float(divergence_score),
            same_theme_performance=same_theme_perf,
            market_emotion=metrics.get("emotion_phase", "修复"),
            consecutive_yizi_days=consecutive if pool_stock.get("limit_type") == "一字" else 0,
            yizi_cumulative_turnover=0.0,
            card_position_exists=card_position_exists,
            institutional_net_wan=float(lhb_metrics.get("institutional_net_wan", 0)),
        )
        break_risk = risk.get("risk_level", "不适用")

    signal = HardSignal(
        ticker=code,
        trade_date=trade_date,
        emotion_phase=metrics.get("emotion_phase", "修复"),
        emotion_score=float(metrics.get("emotion_score", 50)),
        breadth_signal=mb.get("breadth_signal", "正常"),
        yesterday_limitup_avg_return=float(yp.get("avg_return", 0)),
        ad_ratio=float(mb.get("ad_ratio", 1.0)),
        in_limitup_pool=pool_stock is not None,
        consecutive_days=consecutive,
        role=role,
        theme=theme,
        theme_rank=theme_rank,
        st_flag=st_flag,
        is_yizi_unbuyable=is_yizi_unbuyable,
        is_20cm_board=is_20cm,
        circulation_mv=circulation_mv,
        first_limit_time=first_limit_time,
        turnover_rate=turnover,
        change_pct=change_pct,
        is_sealed=is_sealed,
        promotion_rate=promotion_rate,
        card_position_exists=card_position_exists,
        card_position_success=card_position_success,
        card_position_threat=card_position_threat,
        seal_ratio=seal_ratio,
        unlock_pressure_pct=unlock_pressure_pct,
        has_regulatory_alert=has_regulatory_alert,
        auction_strength_score=auction_strength_score,
        auction_strength_level=auction_strength_level,
        main_force_net_wan=main_force_net_wan,
        main_force_signal=main_force_signal,
        second_board_score=second_board_score,
        divergence_score=divergence_score,
        break_risk=break_risk,
        data_sources=data_sources,
        confidence=_compute_confidence(data_sources),
    )

    return apply_gates(signal)


def evaluate(ticker: str, trade_date: str = "") -> HardSignal:
    """Evaluate hard trading logic for a single ticker."""
    ctx = build_market_context(trade_date)
    return evaluate_with_context(ticker, ctx)


HARD_VETO_CHECKS: list[tuple[str, str]] = [
    ("冰点确认", "emotion_phase"),
    ("高标重度分歧", "divergence"),
    ("一字不可买", "yizi"),
    ("ST股", "st"),
]


def _check_hard_veto(signal: HardSignal) -> list[str]:
    """Gate 4: 硬否决（不可被 LLM 覆盖）。"""
    vetoes: list[str] = []
    if signal.emotion_phase == "冰点（已确认）":
        vetoes.append("冰点确认")
    if signal.divergence_score >= 70:
        vetoes.append("高标重度分歧")
    if signal.is_yizi_unbuyable:
        vetoes.append("一字不可买")
    if signal.st_flag:
        vetoes.append("ST股")
    if signal.role == "断板龙头" and signal.emotion_phase in RETREAT_PHASES | ICE_POINT_PHASES:
        vetoes.append("断板龙头+退潮")
    if signal.unlock_pressure_pct > 10:
        vetoes.append("解禁重压")
    if signal.has_regulatory_alert:
        vetoes.append("监管异动")
    return vetoes


def _apply_gate2_stock_tradability(
    signal: HardSignal,
    vetoes: list[str],
    passed: list[str],
) -> dict[str, Any]:
    """Gate 2: 个股可交易性 G2-01~G2-06。"""
    constraints: dict[str, Any] = {
        "seal_threshold_mult": 1.0,
        "position_mult": 1.0,
        "daban_forbidden": False,
        "relay_forbidden": False,
        "low_emotion": False,
        "climax_cap": 1.0,
    }

    if signal.st_flag:
        if "ST股" not in vetoes:
            vetoes.append("ST股")
        passed.append("G2-01-ST")

    if signal.is_yizi_unbuyable:
        if "一字不可买" not in vetoes:
            vetoes.append("一字不可买")
        passed.append("G2-02-一字不可买")

    if signal.is_20cm_board:
        constraints["seal_threshold_mult"] = SEAL_THRESHOLD_20CM_MULT
        constraints["position_mult"] = POSITION_20CM_MULT
        passed.append("G2-03-20cm折算")

    if signal.circulation_mv > CIRC_MV_DABAN_FORBIDDEN:
        constraints["daban_forbidden"] = True
        passed.append("G2-04-大市值禁打板")

    if signal.unlock_pressure_pct > 10:
        if "解禁重压" not in vetoes:
            vetoes.append("解禁重压")
        passed.append("G2-05-解禁重压")
    elif signal.unlock_pressure_pct > 0:
        passed.append("G2-解禁压力可控")

    if signal.has_regulatory_alert:
        if "监管异动" not in vetoes:
            vetoes.append("监管异动")
        passed.append("G2-06-监管异动")

    return constraints


def _apply_gate1_market(
    signal: HardSignal,
    passed: list[str],
    constraints: dict[str, Any],
) -> None:
    """Gate 1: 市场环境 G1-01~G1-05。"""
    if signal.emotion_phase in ICE_POINT_PHASES:
        signal.can_trade = False
        signal.market_gate_passed = False
        signal.action = "观望"
        signal.position_cap = 0.0
        signal.strategy = "空仓观望"
        passed.append("G1-冰点")
        constraints["relay_forbidden"] = True
        constraints["daban_forbidden"] = True
        return

    signal.market_gate_passed = True
    passed.append("G1-市场环境")

    if signal.emotion_score < 30:
        constraints["low_emotion"] = True
        constraints["daban_forbidden"] = True
        constraints["relay_forbidden"] = True
        passed.append("G1-02-情绪低迷")

    if signal.breadth_signal == "弱势" and signal.ad_ratio < 0.8:
        constraints["relay_forbidden"] = True
        passed.append("G1-03-广度弱势禁接力")

    if signal.yesterday_limitup_avg_return < -3 and signal.consecutive_days >= 3:
        constraints["relay_forbidden"] = True
        passed.append("G1-04-负溢价禁高位接力")

    if signal.emotion_phase in CLIMAX_PHASES and signal.emotion_score > 70:
        constraints["climax_cap"] = 0.20
        passed.append("G1-05-高潮减仓")


def _emotion_allows_daban(signal: HardSignal) -> bool:
    if signal.emotion_phase in ICE_POINT_PHASES | {"低迷"}:
        return False
    if signal.emotion_phase in REPAIR_PHASES | WARMING_PHASES | CLIMAX_PHASES:
        return True
    return signal.emotion_score >= 40


def _main_force_allows_relay(signal: HardSignal) -> bool:
    """Gate 3 auxiliary: weak main-force outflow blocks relay strategies."""
    if signal.data_sources.get("main_force_flow") == "[无数据]":
        return True
    if signal.main_force_net_wan > 0:
        return True
    return signal.main_force_signal != "弱势"


def _main_force_allows_daban(signal: HardSignal) -> bool:
    """Gate 3 auxiliary: negative main-force net blocks first-board daban."""
    if signal.data_sources.get("main_force_flow") == "[无数据]":
        return True
    return signal.main_force_net_wan >= 0


def _match_gate3_strategies(
    signal: HardSignal,
    constraints: dict[str, Any],
) -> list[_StrategyMatch]:
    """Gate 3: 策略匹配。回避优先于策略；多策略满足时取 position_cap 最高。"""
    avoid: list[_StrategyMatch] = []

    if signal.break_risk == "高":
        avoid.append(_StrategyMatch("回避", "高标断板风险", 0.0, "G3-回避"))
    if signal.divergence_score >= 70:
        avoid.append(_StrategyMatch("回避", "重度分歧", 0.0, "G3-回避"))
    if signal.role == "断板龙头" and signal.emotion_phase in RETREAT_PHASES | ICE_POINT_PHASES:
        avoid.append(_StrategyMatch("回避", "断板+退潮", 0.0, "G3-回避"))
    if avoid:
        return avoid

    seal_thresh = SEAL_RATIO_THRESHOLD_DABAN * constraints.get("seal_threshold_mult", 1.0)
    matches: list[_StrategyMatch] = []

    if (
        not constraints.get("daban_forbidden")
        and signal.role == "首板候选"
        and signal.consecutive_days == 1
        and _emotion_allows_daban(signal)
        and signal.second_board_score >= 70
        and signal.seal_ratio > seal_thresh
        and signal.first_limit_time
        and signal.first_limit_time < FIRST_LIMIT_TIME_DABAN
        and 0 < signal.theme_rank <= 3
        and (
            signal.auction_strength_score < 0
            or signal.auction_strength_score >= AUCTION_STRENGTH_MIN_DABAN
        )
        and _main_force_allows_daban(signal)
    ):
        matches.append(_StrategyMatch("打板", "首板打板", 0.15, "G3-首板打板"))

    if (
        not constraints.get("relay_forbidden")
        and signal.role in ("题材龙头", "总龙头")
        and signal.emotion_phase in REPAIR_PHASES | WARMING_PHASES
        and signal.is_sealed
        and signal.promotion_rate > 40
        and (signal.divergence_score < 50 or signal.divergence_score < 0)
        and signal.consecutive_days >= 2
        and _main_force_allows_relay(signal)
    ):
        matches.append(_StrategyMatch("接力", "二板接力", 0.20, "G3-二板接力"))

    if (
        signal.emotion_phase in CLIMAX_PHASES
        and signal.role == "高标"
        and 0 <= signal.divergence_score < 70
        and signal.break_risk == "低"
        and 0 < signal.theme_rank <= 3
        and signal.consecutive_days >= 3
        and _main_force_allows_relay(signal)
    ):
        matches.append(_StrategyMatch("接力", "高标接力", 0.10, "G3-高标接力"))

    if (
        signal.role == "断板龙头"
        and -9 <= signal.change_pct <= -5
        and 0 < signal.theme_rank <= 5
        and not signal.card_position_success
    ):
        matches.append(_StrategyMatch("低吸", "龙头低吸", 0.10, "G3-龙头低吸"))

    return matches


def _apply_position_constraints(
    signal: HardSignal,
    cap: float,
    constraints: dict[str, Any],
) -> float:
    cap *= constraints.get("position_mult", 1.0)
    cap = min(cap, constraints.get("climax_cap", 1.0))
    if constraints.get("low_emotion"):
        cap = min(cap, 0.10)
    return cap


def apply_gates(signal: HardSignal) -> HardSignal:
    """Apply Gate 1-4，填充 can_trade / action / position_cap / veto_reasons。"""
    passed: list[str] = []
    vetoes = _check_hard_veto(signal)
    constraints = _apply_gate2_stock_tradability(signal, vetoes, passed)
    _apply_gate1_market(signal, passed, constraints)

    if vetoes:
        signal.can_trade = False
        signal.action = "回避"
        signal.position_cap = 0.0
        signal.strategy = "硬否决"
    elif signal.emotion_phase in ICE_POINT_PHASES:
        pass  # G1-01 已在 _apply_gate1_market 设置
    elif signal.can_trade or constraints.get("low_emotion"):
        strategies = _match_gate3_strategies(signal, constraints)
        if strategies:
            best = max(strategies, key=lambda s: s.position_cap)
            signal.action = best.action
            signal.strategy = best.strategy
            signal.position_cap = _apply_position_constraints(
                signal, best.position_cap, constraints,
            )
            passed.append(best.gate_id)
            if best.action in ("打板", "接力"):
                signal.can_trade = True
            elif best.action == "低吸":
                signal.can_trade = True
            elif best.action == "回避":
                signal.can_trade = False
        elif not signal.in_limitup_pool:
            signal.action = "观望"
            signal.strategy = "非涨停池"
            signal.position_cap = 0.0
            signal.can_trade = False
        else:
            signal.action = "观望"
            signal.strategy = "条件不足"
            signal.position_cap = 0.05
            signal.can_trade = True

    if vetoes:
        signal.can_trade = False
        signal.action = "回避"
        signal.position_cap = 0.0
        signal.strategy = "硬否决"

    signal.veto_reasons = list(dict.fromkeys(vetoes))
    signal.gates_passed = passed
    return signal


def gate_check_portfolio_rating(rating: str, signal: HardSignal) -> tuple[str, list[str]]:
    """Downgrade Buy/Overweight when hard gates block trading."""
    reasons: list[str] = []
    if rating in ("Buy", "Overweight") and not signal.can_trade:
        reasons.extend(signal.veto_reasons or ["硬逻辑禁止交易"])
        return "Hold", reasons
    if rating == "Buy" and signal.position_cap <= 0:
        reasons.append("仓位上限为0")
        return "Hold", reasons
    if rating == "Overweight" and signal.position_cap <= 0.10:
        reasons.append(f"仓位上限仅 {signal.position_cap:.0%}")
        return "Hold", reasons
    if (
        rating in ("Buy", "Overweight")
        and len(signal.veto_reasons) >= 3
    ):
        reasons.extend(signal.veto_reasons)
        return "Underweight", reasons
    return rating, reasons


def hard_signal_to_dict(signal: HardSignal) -> dict:
    return asdict(signal)


def hard_signal_from_json(raw: str) -> HardSignal | None:
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
        return HardSignal(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def hard_signal_to_json(signal: HardSignal) -> str:
    return json.dumps(hard_signal_to_dict(signal), ensure_ascii=False, indent=2)


def _build_ticker_panorama_section(signal: HardSignal) -> str:
    """个股全景 Markdown 节：涨停池 / 题材 / 龙头 / 高标。"""
    pool_flag = "在涨停池" if signal.in_limitup_pool else "不在涨停池"
    lines = [
        "### 个股全景",
        f"- **涨停池**: {pool_flag} | 连板 {signal.consecutive_days} 天",
        f"- **龙头定位**: {signal.role}",
    ]
    if signal.theme:
        lines.append(
            f"- **题材**: {signal.theme}（热度排名 #{signal.theme_rank or '—'}）"
        )
    else:
        lines.append("- **题材**: 未归属当日热门题材")

    if signal.consecutive_days == 1 and signal.second_board_score >= 0:
        lines.append(f"- **首板二板预期**: {signal.second_board_score} 分")
    if signal.consecutive_days >= 3:
        div_text = (
            f"{signal.divergence_score}"
            if signal.divergence_score >= 0
            else "—"
        )
        lines.append(
            f"- **高标监控**: {signal.consecutive_days}板 | 分歧度 {div_text} | 断板风险 {signal.break_risk}"
        )
    if signal.unlock_pressure_pct > 0:
        lines.append(f"- **解禁压力(30日)**: {signal.unlock_pressure_pct:.1f}%")
    if signal.main_force_signal:
        flow_suffix = _source_suffix_from_dict(signal.data_sources, "main_force_flow")
        lines.append(
            f"- **主力资金**: {signal.main_force_net_wan:.0f}万 "
            f"({signal.main_force_signal}){flow_suffix}"
        )
    if signal.card_position_exists or signal.card_position_threat != "无":
        competitor_note = "是" if signal.card_position_success else "否"
        lines.append(
            f"- **卡位**: 威胁={signal.card_position_threat} | "
            f"竞争者存在={'是' if signal.card_position_exists else '否'} | "
            f"卡位成功={competitor_note}"
        )
    return "\n".join(lines)


def hard_signal_to_markdown(signal: HardSignal) -> str:
    veto = "、".join(signal.veto_reasons) if signal.veto_reasons else "无"
    passed = "、".join(signal.gates_passed) if signal.gates_passed else "无"
    trade_flag = "[可交易]" if signal.can_trade else "[不可交易]"
    seal_suffix = _source_suffix_from_dict(signal.data_sources, "seal_ratio")
    seal_display = (
        f"{signal.seal_ratio:.2f}%{seal_suffix}"
        if signal.seal_ratio >= 0
        else "—"
    )
    return (
        f"## 硬逻辑信号 — {signal.ticker} ({signal.trade_date})\n\n"
        f"| 维度 | 值 |\n|------|-----|\n"
        f"| 情绪阶段 | {signal.emotion_phase} (score={signal.emotion_score:.0f}) |\n"
        f"| 个股角色 | {signal.role} |\n"
        f"| 连板天数 | {signal.consecutive_days} |\n"
        f"| 封单比 | {seal_display} |\n"
        + (
            f"| 竞价强度 | {signal.auction_strength_score} ({signal.auction_strength_level})"
            f"{_source_suffix_from_dict(signal.data_sources, 'auction_strength')} |\n"
            if signal.auction_strength_score >= 0
            else ""
        )
        + f"| 解禁压力(30日) | {signal.unlock_pressure_pct:.1f}%"
        f"{_source_suffix_from_dict(signal.data_sources, 'unlock_pressure_pct')} |\n"
        + (
            f"| 主力资金 | {signal.main_force_net_wan:.0f}万 "
            f"({signal.main_force_signal})"
            f"{_source_suffix_from_dict(signal.data_sources, 'main_force_flow')} |\n"
            if signal.main_force_signal
            else ""
        )
        + f"| 题材 | {signal.theme or '—'} (排名 {signal.theme_rank or '—'}) |\n"
        f"| 建议策略 | {signal.strategy} ({signal.action}) |\n"
        f"| 仓位上限 | {signal.position_cap:.0%} |\n"
        f"| 总开关 | {trade_flag} |\n\n"
        f"{_build_ticker_panorama_section(signal)}\n\n"
        f"**通过 Gate:** {passed}\n"
        f"**否决:** {veto}\n"
        f"**置信度:** {signal.confidence}\n"
    )


def _source_suffix_from_dict(data_sources: dict | None, field: str) -> str:
    tag = (data_sources or {}).get(field, "")
    return f" {tag}" if tag else ""
