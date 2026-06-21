"""Streamlit page: short-term scan mode (no full agent graph)."""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv(_PROJECT_ROOT / ".env.enterprise", override=False)

from tradingagents.dataflows.config import set_config
from tradingagents.default_config import DEFAULT_CONFIG
from web.scan_runner import ScanTracker, run_scan_in_thread

st.set_page_config(page_title="短线扫描", page_icon="⚡", layout="wide")
set_config(DEFAULT_CONFIG.copy())

st.title("⚡ 短线扫描模式")
st.caption("首板候选 + HardSignal，不运行完整 8 Agent 分析链")
st.info(
    "首次扫描需拉取涨停池与情绪数据（东财限流约 1s/请求），"
    "通常 30–120 秒；下方会显示实时进度。",
    icon="ℹ️",
)

trade_date = st.date_input("交易日").strftime("%Y-%m-%d")
top_n = st.slider("TOP N", min_value=5, max_value=50, value=20, step=5)
min_score = st.slider("最低二板预期分", min_value=50, max_value=90, value=60, step=5)

tracker: ScanTracker | None = st.session_state.get("scan_tracker")

if st.button("开始扫描", type="primary", disabled=bool(tracker and tracker.is_running)):
    tracker = ScanTracker(trade_date=trade_date, top_n=top_n, min_score=min_score)
    st.session_state["scan_tracker"] = tracker
    run_scan_in_thread(trade_date, top_n, min_score, tracker)
    st.rerun()

tracker = st.session_state.get("scan_tracker")

if tracker and tracker.is_running:
    st.warning(f"扫描进行中：{tracker.message or '请稍候…'}")
    st.progress(tracker.progress or 0.05)
    time.sleep(1.5)
    st.rerun()

elif tracker and tracker.error:
    st.error(f"扫描失败：{tracker.error}")
    if st.button("清除并重试"):
        st.session_state.pop("scan_tracker", None)
        st.rerun()

elif tracker and tracker.is_complete:
    if not tracker.rows:
        st.warning("无首板候选（非交易日、盘后未更新或分数过滤后为空）")
    else:
        st.success(f"共 {len(tracker.rows)} 只候选（交易日 {tracker.trade_date}）")
        st.dataframe(tracker.rows, use_container_width=True)
        if tracker.details_md:
            with st.expander("HardSignal 详情", expanded=False):
                st.markdown(tracker.details_md)
    if st.button("重新扫描"):
        st.session_state.pop("scan_tracker", None)
        st.rerun()
