"""CLI scan mode: TOP N first-board candidates + HardSignal (no full agent graph)."""

from __future__ import annotations

import os
import time
from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table

from tradingagents.dataflows.a_stock import clear_session_cache, scan_first_board_candidates
from tradingagents.logic.trading_hard_logic import (
    build_market_context,
    evaluate_with_context,
    hard_signal_to_markdown,
)

console = Console()


def _print_em_interval_hint() -> None:
    em_interval = float(os.environ.get("EM_MIN_INTERVAL", "1.0"))
    if em_interval < 1.5:
        console.print(
            "[yellow]批量扫描建议设置环境变量 EM_MIN_INTERVAL=1.5 "
            "以降低东财限流风险（当前 "
            f"{em_interval}）[/yellow]"
        )


def main(
    date: str = typer.Option("", "--date", "-d", help="Trade date YYYY-MM-DD"),
    top: int = typer.Option(20, "--top", "-n", help="Max candidates to evaluate"),
    min_score: int = typer.Option(60, "--min-score", help="Minimum second-board score"),
) -> None:
    """Scan first-board candidates and print HardSignal summaries (no LLM / no agent graph)."""
    trade_date = date.strip() or datetime.now().strftime("%Y-%m-%d")
    clear_session_cache()
    _print_em_interval_hint()
    t0 = time.perf_counter()

    console.print(
        f"[dim]正在拉取 {trade_date} 首板数据（同花顺+东财+K线缓存，"
        f"首次运行可能需 30-90 秒）…[/dim]"
    )
    fetch_t0 = time.perf_counter()
    candidates = scan_first_board_candidates(trade_date, min_score=min_score)
    fetch_elapsed = time.perf_counter() - fetch_t0
    console.print(f"[dim]首板评分完成，耗时 {fetch_elapsed:.1f}s[/dim]")
    if not candidates:
        console.print("[yellow]无首板候选（非交易日或盘后未更新）[/yellow]")
        raise typer.Exit(code=0)

    selected = candidates[:top]
    console.print(
        f"[green]找到 {len(candidates)} 只候选，评估 TOP {len(selected)} 的 HardSignal…[/green]"
    )
    ctx = build_market_context(trade_date)
    table = Table(title=f"短线扫描 {trade_date} | 二板预期>={min_score} | TOP {len(selected)}")
    table.add_column("排名", justify="right")
    table.add_column("代码")
    table.add_column("名称")
    table.add_column("二板分", justify="right")
    table.add_column("题材")
    table.add_column("策略")
    table.add_column("仓位", justify="right")
    table.add_column("可交易")

    for idx, stock in enumerate(selected, start=1):
        code = stock["code"]
        signal = evaluate_with_context(code, ctx)
        table.add_row(
            str(idx),
            code,
            stock.get("name", ""),
            str(stock.get("second_board_score", "")),
            stock.get("best_theme", ""),
            f"{signal.strategy}({signal.action})",
            f"{signal.position_cap:.0%}",
            "Y" if signal.can_trade else "N",
        )
        console.print(hard_signal_to_markdown(signal))
        console.print()

    elapsed = time.perf_counter() - t0
    console.print(table)
    console.print(
        f"[dim]扫描 {len(selected)} 只耗时 {elapsed:.1f}s（无 LLM / 无完整 Agent 图）[/dim]"
    )


def entrypoint() -> None:
    typer.run(main)


if __name__ == "__main__":
    entrypoint()
