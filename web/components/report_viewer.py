"""Render the completed analysis report with expandable sections and PDF download."""

from __future__ import annotations

import json
import re
from typing import Any

import streamlit as st

from web.pdf_export import generate_markdown, generate_pdf


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _signal_style(signal: str) -> tuple[str, str]:
    s = signal.upper()
    if "BUY" in s:
        return "#22c55e", "买入"
    if "SELL" in s:
        return "#ef4444", "卖出"
    return "#fbbf24", "持有"


def _parse_hard_signal(json_str: str) -> dict[str, Any]:
    if not json_str:
        return {}
    try:
        data = json.loads(json_str)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _render_hard_signal_section(final_state: dict[str, Any]) -> None:
    """Render programmatic trading gates (collapsible)."""
    summary = final_state.get("hard_signal_summary", "")
    json_str = final_state.get("hard_signal", "")
    if not summary and not json_str:
        return

    data = _parse_hard_signal(str(json_str))
    can_trade = data.get("can_trade")
    action = data.get("action", "—")
    position_cap = data.get("position_cap")
    emotion_phase = data.get("emotion_phase", "—")
    role = data.get("role", "—")

    if can_trade is True:
        badge_color, badge_text = "#22c55e", "✅ 可交易"
    elif can_trade is False:
        badge_color, badge_text = "#ef4444", "❌ 不可交易"
    else:
        badge_color, badge_text = "#888", "—"

    cap_text = f"{position_cap:.0%}" if isinstance(position_cap, (int, float)) else "—"

    st.markdown(
        f"""
        <div style="
            background: #12121f;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 1rem 1.25rem;
            margin: 0.5rem 0 1rem;
        ">
            <div style="display:flex; align-items:center; gap:0.75rem; flex-wrap:wrap;">
                <span style="font-size:1rem; font-weight:700; color:#f5f1eb;">🎯 交易硬逻辑</span>
                <span style="
                    background:{badge_color}22;
                    color:{badge_color};
                    border:1px solid {badge_color}55;
                    border-radius:999px;
                    padding:0.15rem 0.65rem;
                    font-size:0.8rem;
                    font-weight:600;
                ">{badge_text}</span>
                <span style="color:#888; font-size:0.85rem;">
                    情绪 {emotion_phase} · 角色 {role} · 策略 {action} · 仓位上限 {cap_text}
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("🎯 交易硬逻辑详情（程序化 Gate，不可被 LLM 覆盖）", expanded=False):
        if summary:
            st.markdown(_strip_think(str(summary)))
        vetoes = data.get("veto_reasons") or []
        if vetoes:
            st.warning("硬否决：" + "、".join(str(v) for v in vetoes))


_ANALYST_SECTIONS = [
    ("market_report", "📊 技术分析"),
    ("sentiment_report", "💬 市场情绪"),
    ("news_report", "📰 新闻舆情"),
    ("fundamentals_report", "📋 基本面"),
    ("policy_report", "🏛️ 政策分析"),
    ("hot_money_report", "🔥 游资追踪"),
    ("lockup_report", "🔒 解禁/减持"),
    ("short_term_report", "⚡ 短线博弈"),
]


def render_report(
    final_state: dict[str, Any],
    ticker: str,
    trade_date: str,
    signal: str,
    elapsed: float | None = None,
) -> None:
    """Render the full analysis report."""

    color, cn_signal = _signal_style(signal)

    stats_html = ""
    if elapsed is not None:
        m, s = divmod(int(elapsed), 60)
        stats_html = f'<div style="font-size:0.9rem; color:#888; margin-top:0.3rem;">耗时 {m}:{s:02d}</div>'

    st.markdown(
        f"""
        <div style="
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border: 1px solid #333;
            border-radius: 16px;
            padding: 2rem;
            text-align: center;
            margin: 1rem 0 2rem;
        ">
            <div style="font-size:0.9rem; color:#888; letter-spacing:2px;">TRADING SIGNAL</div>
            <div style="font-size:3.5rem; font-weight:900; color:{color}; margin:0.3rem 0;">
                {signal.upper()}
            </div>
            <div style="font-size:1.2rem; color:#f5f1eb;">
                {ticker} · {trade_date}
            </div>
            {stats_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption("⚠️ 本报告由 AI 自动生成，仅供学习研究，不构成投资建议。")

    _render_hard_signal_section(final_state)

    # Markdown export always works (no font dependency); PDF is generated
    # lazily and guarded so a PDF/font failure never crashes the results page.
    col_md, col_pdf, col_spacer = st.columns([1, 1, 2])
    with col_md:
        md_text = generate_markdown(final_state, ticker, trade_date, signal)
        st.download_button(
            "📥 下载 Markdown",
            data=md_text.encode("utf-8"),
            file_name=f"TradingAgents-Astock_{ticker}_{trade_date}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with col_pdf:
        try:
            pdf_bytes = generate_pdf(final_state, ticker, trade_date, signal)
            st.download_button(
                "📄 下载 PDF",
                data=pdf_bytes,
                file_name=f"TradingAgents-Astock_{ticker}_{trade_date}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as exc:  # noqa: BLE001 — never let PDF crash the page
            st.button(
                "📄 PDF 不可用",
                disabled=True,
                use_container_width=True,
                help=f"PDF 生成失败，请改用 Markdown 导出。原因：{exc}",
            )

    st.markdown("---")

    inv_plan = final_state.get("investment_plan", "")
    if inv_plan:
        st.markdown("### 👔 最终投资建议")
        st.markdown(_strip_think(str(inv_plan)))
        st.markdown("---")

    st.markdown("### 📊 分析师报告")

    for key, title in _ANALYST_SECTIONS:
        content = final_state.get(key, "")
        if not content:
            continue
        with st.expander(title, expanded=False):
            st.markdown(_strip_think(str(content)))

    debate = final_state.get("investment_debate_state")
    if debate and isinstance(debate, dict):
        st.markdown("### ⚔️ 多空辩论")
        tab_bull, tab_bear, tab_judge = st.tabs(["多方", "空方", "研究经理"])
        with tab_bull:
            st.markdown(_strip_think(debate.get("bull_history", "") or "无数据"))
        with tab_bear:
            st.markdown(_strip_think(debate.get("bear_history", "") or "无数据"))
        with tab_judge:
            st.markdown(_strip_think(debate.get("judge_decision", "") or "无数据"))

    trader_decision = final_state.get("trader_investment_decision", "")
    if trader_decision:
        with st.expander("💹 交易员决策", expanded=False):
            st.markdown(_strip_think(str(trader_decision)))

    risk = final_state.get("risk_debate_state")
    if risk and isinstance(risk, dict):
        st.markdown("### 🛡️ 风控评估")
        tab_agg, tab_con, tab_neu, tab_rj = st.tabs(["激进", "保守", "中性", "风控决策"])
        with tab_agg:
            st.markdown(_strip_think(risk.get("aggressive_history", "") or "无数据"))
        with tab_con:
            st.markdown(_strip_think(risk.get("conservative_history", "") or "无数据"))
        with tab_neu:
            st.markdown(_strip_think(risk.get("neutral_history", "") or "无数据"))
        with tab_rj:
            st.markdown(_strip_think(risk.get("judge_decision", "") or "无数据"))

    dqs = final_state.get("data_quality_summary", "")
    if dqs:
        with st.expander("✅ 数据质量", expanded=False):
            st.markdown(str(dqs))
