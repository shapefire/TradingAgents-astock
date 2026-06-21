# MVP 验证场景

> 每个场景对应 TASK_CHECKLIST 中的验收任务。P0 完成后必须全部通过。

## 场景索引

| 场景 ID | 名称 | 阶段 | 关联任务 |
|---------|------|------|----------|
| VS-01 | 冰点日总开关 | P0 | T0-20, T0-21 |
| VS-02 | 修复日首板打板 | P0 | T0-20, T0-22 |
| VS-03 | 高标重度分歧回避 | P0 | T0-20, T0-23 |
| VS-04 | leader 工具参数正确 | P0 | T0-01, T0-02 |
| VS-05 | 决策链含短线上下文 | P0 | T0-10 ~ T0-14 |
| VS-06 | PM 评级 Gate 降级 | P2 | T2-08 |
| VS-07 | 真实封单比 | P1 | T1-01 |
| VS-08 | 炸板率纳入封板质量 | P1 | T1-03 |
| VS-09 | 解禁重压否决 | P1 | T1-10 |
| VS-10 | 扫描模式 TOP N | P3 | T3-03 |

---

## VS-01：冰点日总开关

**前置：** 选取或 mock 一个 `emotion_phase=冰点(已确认)` 的 `trade_date`。

**执行：**

```python
from tradingagents.logic.trading_hard_logic import evaluate

signal = evaluate("000001", "2026-01-XX")  # 替换为已知冰点日
```

**期望：**

| 字段 | 期望值 |
|------|--------|
| `can_trade` | `False` |
| `action` | `观望` 或 `回避` |
| `veto_reasons` | 含 `冰点确认` 或等价描述 |
| `position_cap` | `0.0` |

**自动化：**

```bash
pytest tests/test_trading_hard_logic.py::test_gate_ice_point_blocks_trade -v
```

---

## VS-02：修复日首板打板

**前置：** 情绪阶段=修复，`second_board_score≥70`，标的在首板池，题材 TOP3。

**期望：**

| 字段 | 期望值 |
|------|--------|
| `can_trade` | `True` |
| `action` | `打板` |
| `position_cap` | `≤ 0.15` |
| `gates_passed` | 含 `G3-首板打板` 或等价 |

**自动化：**

```bash
pytest tests/test_trading_hard_logic.py::test_gate_first_board_daban -v
```

---

## VS-03：高标重度分歧回避

**前置：** `divergence_score >= 70` 或 `break_risk=高`。

**期望：**

| 字段 | 期望值 |
|------|--------|
| `action` | `回避` |
| `veto_reasons` | 含 `高标重度分歧` |
| `position_cap` | `0.0` |

---

## VS-04：leader 工具参数正确

**执行：**

```python
from tradingagents.agents.utils.signal_data_tools import get_leader_identification

# 经 tool / route_to_vendor 路径
result = get_leader_identification.invoke({
    "ticker": "000001",
    "trade_date": "2026-06-16",
    "theme": "",
})
```

**期望：**

- 返回字符串，包含 `000001` 或该股名称
- 不包含「请指定 ticker 或 theme 参数」
- 不把 `2026-06-16` 当作股票代码解析

**自动化：**

```bash
pytest tests/test_short_term_integration.py::test_leader_identification_tool_params -v
```

---

## VS-05：决策链含短线上下文

**执行：** 跑一轮完整 propagate（可用 mock LLM 或 snapshot 测试）。

**期望：**

- `final_state` 含 `hard_signal` 或 `hard_signal_summary`
- Bull/Bear / Trader 的 logged prompt 或 snapshot 含 `short_term_report` 片段
- Quality Gate 输出含 `short_term` 评级行

**自动化：**

```bash
pytest tests/test_trading_hard_logic_integration.py::test_decision_chain_includes_short_term -v
```

---

## VS-06：PM 评级 Gate 降级（P2）

**前置：** `HardSignal.can_trade=False`，PM 原始输出 `Buy`。

**期望：**

- 最终 `portfolio_rating` 为 `Hold`
- 报告中注明 Gate 否决原因

---

## VS-07：真实封单比（P1）

**执行：** 对当日涨停股调用 `_get_stock_seal_info` 或 `evaluate()`。

**期望：**

- `seal_ratio` 来自 `seal_amount / circulation_mv`（当 EM 有值）
- `data_sources.seal_ratio` 标注 `[确认]` 而非 `[估算]`

---

## VS-08：炸板率纳入封板质量（P1）

**期望：**

- `get_consecutive_limit_stats` 输出含炸板率或炸板家数
- `_calculate_seal_quality` 使用炸板池数据

---

## VS-09：解禁重压否决（P1）

**前置：** 标的 30 日内解禁占比 > 10%。

**期望：**

- `unlock_pressure_pct > 10`
- `veto_reasons` 含 `解禁重压`
- `can_trade=False`（打板/接力场景）

---

## VS-10：扫描模式 TOP N（P3）

**执行：**

```bash
python -m cli.scan_short_term --date 2026-06-16 --top 20
```

**期望：**

- 输出 20 只首板候选 + 各 `HardSignal` 摘要
- 不触发完整 8 Agent 流程
- 耗时显著低于完整 propagate

---

## Mock 测试数据约定

单元测试使用 fixture，不依赖网络：

```python
# tests/fixtures/hard_signal_fixtures.py

ICE_POINT_MARKET = {
    "emotion_phase": "冰点(已确认)",
    "emotion_score": 15,
    "can_trade": False,
}

FIRST_BOARD_CANDIDATE = {
    "emotion_phase": "修复",
    "emotion_score": 58,
    "second_board_score": 72,
    "theme_rank": 2,
    "seal_ratio": 4.5,
}
```

Live smoke 测试使用 `@pytest.mark.live` 标记，CI 默认跳过。

---

## 回归命令（合并门槛）

```bash
# P0 合并前
python -m pytest tests/test_trading_hard_logic.py tests/test_short_term_integration.py -v

# P0 合并前全量
python -m pytest tests/ -v -m "not live"

# P1+ 含 live smoke（本地手动）
python -m pytest tests/ -v -m live
```
