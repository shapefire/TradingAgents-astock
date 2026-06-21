"""Background thread runner for short-term scan (no LLM)."""

from __future__ import annotations

import os
import threading
import traceback

from tradingagents.dataflows.a_stock import clear_session_cache, scan_first_board_candidates
from tradingagents.logic.trading_hard_logic import (
    build_market_context,
    evaluate_with_context,
    hard_signal_to_markdown,
)


class ScanTracker:
    """Thread-safe scan progress for Streamlit UI polling."""

    def __init__(self, trade_date: str, top_n: int, min_score: int) -> None:
        self.trade_date = trade_date
        self.top_n = top_n
        self.min_score = min_score
        self.is_running = False
        self.is_complete = False
        self.error: str | None = None
        self.message = ""
        self.progress = 0.0
        self.rows: list[dict] = []
        self.details_md: str = ""
        self._lock = threading.Lock()

    def set_message(self, message: str, progress: float | None = None) -> None:
        with self._lock:
            self.message = message
            if progress is not None:
                self.progress = max(0.0, min(1.0, progress))

    def mark_complete(self, rows: list[dict], details_md: str) -> None:
        with self._lock:
            self.rows = rows
            self.details_md = details_md
            self.is_running = False
            self.is_complete = True
            self.progress = 1.0
            self.message = "扫描完成"

    def mark_error(self, err: str) -> None:
        with self._lock:
            self.error = err
            self.is_running = False
            self.message = ""


def _run_scan(trade_date: str, top_n: int, min_score: int, tracker: ScanTracker) -> None:
    try:
        tracker.is_running = True
        tracker.set_message("正在加载首板数据（东财/同花顺，约 30–90 秒）…", 0.05)
        clear_session_cache()
        candidates = scan_first_board_candidates(trade_date, min_score=min_score)
        if not candidates:
            tracker.mark_complete([], "")
            return

        selected = candidates[:top_n]
        total = len(selected)
        rows: list[dict] = []
        detail_parts: list[str] = []

        ctx = build_market_context(trade_date)

        for idx, stock in enumerate(selected, start=1):
            code = stock["code"]
            tracker.set_message(
                f"计算 HardSignal：{code} {stock.get('name', '')} ({idx}/{total})",
                0.1 + 0.85 * (idx - 1) / max(total, 1),
            )
            signal = evaluate_with_context(code, ctx)
            rows.append({
                "代码": code,
                "名称": stock.get("name", ""),
                "二板分": stock.get("second_board_score"),
                "题材": stock.get("best_theme", ""),
                "策略": f"{signal.strategy}({signal.action})",
                "仓位上限": f"{signal.position_cap:.0%}",
                "可交易": signal.can_trade,
            })
            detail_parts.append(hard_signal_to_markdown(signal))

        tracker.mark_complete(rows, "\n\n---\n\n".join(detail_parts))
    except Exception as exc:
        tracker.mark_error(f"{exc}\n\n{traceback.format_exc()}")


def run_scan_in_thread(
    trade_date: str,
    top_n: int,
    min_score: int,
    tracker: ScanTracker,
) -> None:
    tracker.is_running = True
    tracker.message = "正在启动扫描…"
    thread = threading.Thread(
        target=_run_scan,
        args=(trade_date, top_n, min_score, tracker),
        daemon=True,
    )
    thread.start()
