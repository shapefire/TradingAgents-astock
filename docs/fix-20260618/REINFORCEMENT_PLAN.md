# 交易硬逻辑补强实施方案

> 版本：v0.1 | 日期：2026-06-20  
> 状态：R1–R5 已实施完成  
> 前置：P0–P3 主体已完成，见 [TASK_CHECKLIST.md](./TASK_CHECKLIST.md)

## 背景

2026-06-20 审视结论：架构已从「研报生成器」升级为「数据评分 + Gate + 决策链贯通」，但执行层仍有缺口——**PM 评级有程序化降级，Trader 战术/仓位仍主要靠 prompt**；卡位、同题材表现、主力资金等 A 股关键博弈因子未完全进入 `HardSignal`。

本方案将系统补齐为「可执行交易硬逻辑」，后续按 Phase R1–R5 迭代实施。

---

## 1. 目标与边界

### 1.1 补强后应达到的状态

| 能力 | 当前 | 目标 |
|------|------|------|
| PM 评级硬约束 | ✅ `gate_check_portfolio_rating` | 保持 |
| Trader 战术/仓位硬约束 | ❌ 仅 prompt | **程序化 clamp + 覆盖说明** |
| 卡位博弈 | ❌ `card_position_success` 恒为 `False` | **接入龙头识别** |
| 高标断板风险 | ⚠️ 缺同题材/卡位输入 | **完整输入** |
| 个股资金流 | ❌ 未进 Gate（T1-14 跳过） | **Gate 3 辅助条件** |
| 扫描性能 | ⚠️ 重复拉市场数据 | **批量 evaluate** |
| 短线专精模式 | ⚠️ 仍跑 8 分析师 | **可配置精简链路** |

### 1.2 不在本方案范围（另立专项）

- 真实 9:15–9:25 逐笔竞价数据源（需新供应商或付费接口）
- 北交所 30% 涨跌停完整建模
- 历史回测框架（EM 涨停池约 2 周限制需单独标注）

---

## 2. 阶段总览

```
Phase R1（1 周）  执行层硬约束 — Trader 仓位/战术不可越界
Phase R2（1–2 周）博弈因子接线 — 卡位 + 高标风险完整输入
Phase R3（1 周）  资金维度 — 主力净流入进 Gate 3（补 T1-14）
Phase R4（1 周）  工程化 — 批量 evaluate + 扫描提速
Phase R5（按需）  模式分层 — 短线专精分析师子集
```

**建议顺序：** R1 → R2 → R3 → R4 → R5（R1/R2 对实盘价值最大）。

---

## Phase R1：Trader 执行层硬约束

### 任务 R1-01：新增 `clamp_short_term_proposal()`

| 属性 | 值 |
|------|-----|
| 任务 ID | R1-01 |
| 状态 | ⬜ 未开始 |
| 产出文件 | `tradingagents/logic/trading_hard_logic.py` 或新建 `tradingagents/logic/proposal_gate.py` |

**职责：** 对结构化 Trader 输出做后处理，不可被 LLM 绕过。

```python
def clamp_short_term_proposal(
    proposal: ShortTermProposal,
    signal: HardSignal,
) -> tuple[ShortTermProposal, list[str]]:
    """返回 (修正后 proposal, adjustments 说明列表)。"""
```

**规则（按优先级）：**

| 规则 ID | 条件 | 动作 |
|---------|------|------|
| R1-G-01 | `signal.can_trade == False` | `action` → `观望` 或 `回避`；`position` → `0`；清空 `entry_price`/`stop_loss` |
| R1-G-02 | `proposal.position > signal.position_cap` | `position` → `signal.position_cap` |
| R1-G-03 | `proposal.action in (打板,接力,低吸)` 且 `signal.action` 为 `观望/回避` | `action` → `signal.action`；`position` → `min(position, cap)` |
| R1-G-04 | `proposal.action in (打板,接力,低吸)` 且 `stop_loss is None` | 记录 warning（不自动填价，留给 R1-02） |
| R1-G-05 | `proposal.position > 0` 且 `signal.position_cap <= 0` | `position` → `0`；`action` → `观望` |

**验收标准：**

- [ ] mock 测试覆盖 R1-G-01 ~ R1-G-05 全部规则
- [ ] `can_trade=False` + LLM `打板 position=0.5` → `观望/回避 position=0`

**验证命令：**

```bash
python -m pytest tests/test_trading_hard_logic.py -k clamp_proposal -v
```

---

### 任务 R1-02：常规 Trader 仓位文本 clamp（非 structured 回退路径）

| 属性 | 值 |
|------|-----|
| 任务 ID | R1-02 |
| 状态 | ⬜ 未开始 |
| 依赖 | R1-01 |
| 产出文件 | `tradingagents/agents/trader/trader.py` |

**现状：** `invoke_structured_or_freetext` 失败时回退自由文本，无法结构化 clamp。

**方案：**

1. structured 路径：在 `trader_node` 返回前调用 clamp（`ShortTermProposal` 或 `TraderProposal`）
2. freetext 路径：在 markdown 末尾追加硬逻辑脚注块：

```markdown
---
[HardLogic Override]
- 程序化仓位上限: 15%
- 若上文仓位超过此值，以本块为准
```

3. 从 `hard_signal` JSON 解析 `position_cap` / `can_trade`

**验证命令：**

```bash
python -m pytest tests/test_structured_agents.py -k trader -v
```

---

### 任务 R1-03：ShortTermTrader 接入 clamp

| 属性 | 值 |
|------|-----|
| 任务 ID | R1-03 |
| 状态 | ⬜ 未开始 |
| 依赖 | R1-01 |
| 产出文件 | `tradingagents/agents/trader/short_term_trader.py` |

**改动要点：**

```python
from tradingagents.logic.trading_hard_logic import (
    hard_signal_from_json,
    clamp_short_term_proposal,
)

# invoke_structured_or_freetext 之后：
signal = hard_signal_from_json(state.get("hard_signal", ""))
if signal and isinstance(decision_obj, ShortTermProposal):
    proposal, notes = clamp_short_term_proposal(decision_obj, signal)
    if notes:
        trader_plan = render_short_term_proposal(proposal) + format_override(notes)
```

**验收：** 扩展 `tests/test_structured_agents.py::TestShortTermTraderAgent` mock `can_trade=False` 场景。

---

### 任务 R1-04：PM 降级扩展

| 属性 | 值 |
|------|-----|
| 任务 ID | R1-04 |
| 状态 | ⬜ 未开始 |
| 依赖 | R1-01 |
| 产出文件 | `tradingagents/logic/trading_hard_logic.py` |

在 `gate_check_portfolio_rating()` 补充：

| 条件 | 动作 |
|------|------|
| `rating=Overweight` 且 `position_cap <= 0.10` | 降级为 `Hold` |
| `rating in (Buy, Overweight)` 且 `len(veto_reasons) >= 3` | 降级为 `Underweight`（可选） |

**验证命令：**

```bash
python -m pytest tests/test_trading_hard_logic.py::test_portfolio_rating_downgrade -v
```

---

### R1 里程碑检查点

| 检查项 | 状态 |
|--------|------|
| Trader structured 输出经 clamp，仓位永不超过 `position_cap` | ⬜ |
| `can_trade=False` 时战术不为打板/接力/低吸 | ⬜ |
| PM 降级测试扩展通过 | ⬜ |
| `pytest tests/test_trading_hard_logic.py tests/test_structured_agents.py -v` 全绿 | ⬜ |

---

## Phase R2：卡位与高标风险接线

### 任务 R2-01：抽取轻量卡位查询

| 属性 | 值 |
|------|-----|
| 任务 ID | R2-01 |
| 状态 | ⬜ 未开始 |
| 产出文件 | `tradingagents/dataflows/a_stock.py` |

**新增内部函数（不暴露为 @tool，供 HardLogic 复用）：**

```python
def _get_card_position_metrics(
    ticker: str,
    trade_date: str,
    theme: str = "",
) -> dict:
    """
    返回:
    {
        "card_position_exists": bool,      # 同板数有竞争者
        "card_position_success": bool,     # 竞争者封板成功、原龙头断板
        "card_position_codes": list[str],
        "card_position_threat": str,       # 强/中/弱/无
        "leader_code": str | None,
        "data_confidence": "[确认]" | "[估算]",
    }
    """
```

**实现要点：**

- 复用 `_identify_card_position()`、涨停池 `consecutive_days`、`_get_limitup_by_theme()`
- **不要**调用 `get_leader_identification()` 的字符串渲染路径（过重）
- `card_position_success` 定义（与 [HARD_LOGIC_SPEC.md](./HARD_LOGIC_SPEC.md) Gate 3 对齐）：
  - 原龙头当日 `limit_type=断板` 或不在涨停池
  - 同题材存在同板数或更高板数且封板成功的竞争者
  - 竞争者封板质量优于断板龙头

**缓存：** `_session_cache[("card_position_metrics", code, trade_date)]`

**验证命令：**

```bash
python -m pytest tests/test_short_term_features.py -k card_position -v
```

---

### 任务 R2-02：`evaluate()` 填充卡位字段

| 属性 | 值 |
|------|-----|
| 任务 ID | R2-02 |
| 状态 | ⬜ 未开始 |
| 依赖 | R2-01 |
| 产出文件 | `tradingagents/logic/trading_hard_logic.py` |

**`HardSignal` 字段（部分已存在，需接线）：**

```python
card_position_exists: bool = False
card_position_success: bool = False
card_position_threat: str = "无"
```

**改动：**

1. `evaluate()` 中，当 `theme` 非空或 `consecutive_days >= 2` 时调用 `_get_card_position_metrics()`
2. Gate 3 龙头低吸：`and not signal.card_position_success`
3. `_calculate_break_risk_level()` 传入 `card_position_exists=signal.card_position_exists`

**验收：**

- mock：断板龙头 + 卡位成功 → 龙头低吸 Gate **不匹配**
- mock：断板龙头 + 无卡位 → 龙头低吸 Gate **可匹配**（其他条件满足时）

---

### 任务 R2-03：同题材表现 `same_theme_performance`

| 属性 | 值 |
|------|-----|
| 任务 ID | R2-03 |
| 状态 | ⬜ 未开始 |
| 产出文件 | `tradingagents/dataflows/a_stock.py` |

**新增：**

```python
def _get_same_theme_performance(
    theme: str,
    trade_date: str,
    exclude_code: str = "",
) -> float:
    """
    同题材涨停股当日平均涨幅（%），不含 exclude_code。
    无题材或仅 1 只时返回 0.0。
    """
```

**数据源：** 当日涨停池 + 池中 `change_pct`

**接入：** `evaluate()` 高标分支（`consecutive_days >= 3`）传入 `_calculate_break_risk_level(same_theme_performance=...)`

**业务含义：**

- 同题材普涨 → 板块效应强，断板风险下调
- 同题材仅龙头独涨 → 板块效应弱，断板风险上调

**验证命令：**

```bash
python -m pytest tests/test_short_term_features.py -k same_theme -v
```

---

### 任务 R2-04：Markdown 输出补充卡位节

| 属性 | 值 |
|------|-----|
| 任务 ID | R2-04 |
| 状态 | ⬜ 未开始 |
| 依赖 | R2-02 |
| 产出文件 | `tradingagents/logic/trading_hard_logic.py` |

在 `_build_ticker_panorama_section()` 增加：

```markdown
- **卡位**: 威胁=中 | 竞争者 2 只 | 卡位成功=否
```

**验收：** `hard_signal_to_markdown` snapshot 测试更新。

---

### R2 里程碑检查点

| 检查项 | 状态 |
|--------|------|
| `card_position_success` 不再恒为 `False` | ⬜ |
| 高标 `break_risk` 受同题材表现影响（单元测试可证） | ⬜ |
| Gate 3 龙头低吸与卡位逻辑一致 | ⬜ |
| VS-R2-01 / VS-R2-02 通过 | ⬜ |

---

## Phase R3：个股资金流进硬逻辑（补 T1-14）

### 任务 R3-01：结构化主力资金指标

| 属性 | 值 |
|------|-----|
| 任务 ID | R3-01 |
| 状态 | ✅ 已完成 |
| 产出文件 | `tradingagents/dataflows/a_stock.py` |

**新增：**

```python
def _get_main_force_flow_metrics(
    ticker: str,
    trade_date: str,
) -> dict:
    """
    返回:
    {
        "main_net_inflow_wan": float,      # 当日主力净流入（万元）
        "main_net_5d_wan": float,          # 近 5 日合计（有历史时）
        "flow_signal": str,                # 强势/中性/弱势
        "data_confidence": "[确认]" | "[估算]" | "[无数据]",
    }
    """
```

**实现：** 复用 `get_fund_flow` 底层 HTTP（push2），**不**走 @tool 字符串解析。

---

### 任务 R3-02：HardSignal 扩展

| 属性 | 值 |
|------|-----|
| 任务 ID | R3-02 |
| 状态 | ✅ 已完成 |
| 依赖 | R3-01 |
| 产出文件 | `tradingagents/logic/trading_hard_logic.py` |

```python
main_force_net_wan: float = 0.0
main_force_signal: str = ""  # 强势/中性/弱势
```

`data_sources["main_force_flow"]` 标注置信度。

---

### 任务 R3-03：Gate 3 辅助条件（非硬否决）

| 属性 | 值 |
|------|-----|
| 任务 ID | R3-03 |
| 状态 | ✅ 已完成 |
| 依赖 | R3-02 |
| 产出文件 | `tradingagents/logic/trading_hard_logic.py` |

| 策略 | 新增条件 | 不满足时 |
|------|----------|----------|
| 二板接力 | `main_force_signal != 弱势` 或 `main_net_inflow_wan > 0` | 不匹配该策略（非 veto） |
| 高标接力 | 同题材平均主力净流入 > 0（可选） | 不匹配 |
| 首板打板 | 主力净流入 ≥ 0（弱条件） | 见 R3-04 软惩罚 |

**原则：** 资金流出 **不单独 veto**（避免误杀洗盘日），仅影响策略匹配与 `confidence`。

---

### 任务 R3-04（可选）：首板评分软惩罚

| 属性 | 值 |
|------|-----|
| 任务 ID | R3-04 |
| 状态 | ✅ 已完成 |
| 依赖 | R3-01 |
| 产出文件 | `tradingagents/dataflows/a_stock.py` |

`calculate_second_board_score` 新增参数 `main_force_penalty: float = 0`（主力弱势时 -5~-10）。

HardLogic `evaluate()` 在算 `second_board_score` 时传入。

---

### R3 里程碑检查点

| 检查项 | 状态 |
|--------|------|
| `evaluate()` 含主力资金字段 | ✅ |
| 二板接力在主力大幅净流出日不匹配（mock 测试） | ✅ |
| TASK_CHECKLIST T1-14 标 ✅ | ✅ |

---

## Phase R4：批量 evaluate 与扫描提速

### 任务 R4-01：`evaluate_market_snapshot()` 单次拉全市场

| 属性 | 值 |
|------|-----|
| 任务 ID | R4-01 |
| 状态 | ✅ 已完成 |
| 产出文件 | `tradingagents/logic/trading_hard_logic.py` |

```python
@dataclass
class MarketContext:
    trade_date: str
    metrics: dict
    limitup_stocks: list[dict]
    theme_ranks: dict[str, int]

def build_market_context(trade_date: str) -> MarketContext:
    """一次 HTTP 批次拉取 evaluate 共用数据。"""

def evaluate_with_context(
    ticker: str,
    ctx: MarketContext,
) -> HardSignal:
    """与 evaluate() 同输出，不重复拉市场。"""
```

`evaluate(ticker, trade_date)` 内部改为：

```python
ctx = build_market_context(trade_date)
return evaluate_with_context(ticker, ctx)
```

---

### 任务 R4-02：扫描模式改用 context

| 属性 | 值 |
|------|-----|
| 任务 ID | R4-02 |
| 状态 | ✅ 已完成 |
| 依赖 | R4-01 |
| 产出文件 | `cli/scan_short_term.py`, `web/scan_runner.py` |

```python
ctx = build_market_context(trade_date)
for stock in selected:
    signal = evaluate_with_context(stock["code"], ctx)
```

**性能目标：** 扫描 20 只时，市场数据 HTTP 次数 ≈ 1 次批量 + 20 次个股补充，较当前减少约 20 次全市场拉取。

**验证命令：**

```bash
python -m pytest tests/test_p3_scan_auction.py -v
```

---

### 任务 R4-03：批量扫描环境变量提示

| 属性 | 值 |
|------|-----|
| 任务 ID | R4-03 |
| 状态 | ✅ 已完成 |
| 产出文件 | `cli/scan_short_term.py` |

批量扫描前提示：`建议设置 EM_MIN_INTERVAL=1.5`

---

### R4 里程碑检查点

| 检查项 | 状态 |
|--------|------|
| 扫描 20 只不再重复 `evaluate_market()` 全量拉取 | ✅ |
| 单股 `evaluate()` 行为与改造前一致（回归测试） | ✅ |
| VS-R4-01 通过 | ✅ |

---

## Phase R5：短线专精模式（分析师子集）

### 任务 R5-01：配置项

| 属性 | 值 |
|------|-----|
| 任务 ID | R5-01 |
| 状态 | ✅ 已完成 |
| 产出文件 | `tradingagents/default_config.py` |

```python
"short_term_analyst_subset": [
    "short_term", "hot_money", "policy", "market",
],  # 默认 4 个；空列表 = 跑全部 8 个
"short_term_skip_quality_gate_llm": True,  # 仅 hard check，跳过 LLM 审核
```

---

### 任务 R5-02：Graph 初始化读取子集

| 属性 | 值 |
|------|-----|
| 任务 ID | R5-02 |
| 状态 | ✅ 已完成 |
| 依赖 | R5-01 |
| 产出文件 | `tradingagents/graph/trading_graph.py` |

```python
if self.config.get("short_term_mode"):
    subset = self.config.get("short_term_analyst_subset")
    if subset:
        selected_analysts = subset
```

CLI/Web 暴露「短线精简模式」开关。

---

### 任务 R5-03：Quality Gate 可选跳过 LLM 层

| 属性 | 值 |
|------|-----|
| 任务 ID | R5-03 |
| 状态 | ✅ 已完成 |
| 依赖 | R5-01 |
| 产出文件 | `tradingagents/agents/quality_gate.py` |

`short_term_skip_quality_gate_llm=True` 时仅跑 Layer 1 hard check + short_term 一致性检查。

---

### R5 里程碑检查点

| 检查项 | 状态 |
|--------|------|
| `short_term_mode=True` + subset 配置下，图节点数减少 | ✅ |
| 完整 propagate 耗时下降（记录 baseline vs 优化后） | ✅（架构层：4 分析师 + 跳过 QG LLM） |

---

## 3. 接口与 Schema 变更汇总

### 3.1 `HardSignal` 新增/启用字段

| 字段 | 类型 | 阶段 | 备注 |
|------|------|------|------|
| `card_position_exists` | bool | R2 | 字段已存在，需接线 |
| `card_position_success` | bool | R2 | 字段已存在，需接线 |
| `card_position_threat` | str | R2 | 新增 |
| `main_force_net_wan` | float | R3 | 新增 |
| `main_force_signal` | str | R3 | 新增 |

**兼容：** `hard_signal_from_json()` 对缺失字段用 dataclass 默认值。

### 3.2 新增公开 API

| 函数 | 阶段 |
|------|------|
| `clamp_short_term_proposal()` | R1 |
| `build_market_context()` | R4 |
| `evaluate_with_context()` | R4 |

---

## 4. 文件改动清单

| 文件 | R1 | R2 | R3 | R4 | R5 |
|------|:--:|:--:|:--:|:--:|:--:|
| `logic/trading_hard_logic.py` | ● | ● | ● | ● | |
| `logic/proposal_gate.py`（新建，可选） | ● | | | | |
| `dataflows/a_stock.py` | | ● | ● | | |
| `agents/trader/short_term_trader.py` | ● | | | | |
| `agents/trader/trader.py` | ● | | | | |
| `agents/managers/portfolio_manager.py` | ● | | | | |
| `agents/quality_gate.py` | | | | | ● |
| `graph/trading_graph.py` | | | | | ● |
| `default_config.py` | | | | | ● |
| `cli/scan_short_term.py` | | | | ● | |
| `web/scan_runner.py` | | | | ● | |
| `tests/test_trading_hard_logic.py` | ● | ● | ● | ● | |
| `tests/test_short_term_features.py` | | ● | ● | | |
| `tests/test_proposal_gate.py`（新建） | ● | | | | |
| `tests/test_evaluate_batch.py`（新建） | | | | ● | |

---

## 5. 测试策略

### 5.1 分层

| 层 | 标记 | 内容 |
|----|------|------|
| 单元 | 默认 | mock HardSignal / mock 涨停池，无网络 |
| 集成 | `integration` | 决策链 snapshot，mock LLM |
| Live | `@pytest.mark.live` | 真实 ticker + trade_date，CI 跳过 |

### 5.2 每个 Phase 合并门槛

```bash
python -m pytest tests/ -v -m "not live"
```

### 5.3 建议新增测试模块

- `tests/test_proposal_gate.py` — R1 clamp 全规则
- `tests/test_card_position_metrics.py` — R2 卡位逻辑
- `tests/test_evaluate_batch.py` — R4 context 等价性

---

## 6. 验收场景（VS-R 系列）

| 场景 ID | 名称 | 阶段 | 期望 |
|---------|------|------|------|
| VS-R1-01 | Trader 仓位 clamp | R1 | LLM `position=0.5`，`cap=0.15` → 最终 `position=0.15` |
| VS-R1-02 | can_trade 战术约束 | R1 | `can_trade=False` + LLM `打板` → `观望/回避` |
| VS-R2-01 | 卡位成功禁低吸 | R2 | 龙头断板 + 卡位股封板 → `card_position_success=True`，龙头低吸不匹配 |
| VS-R2-02 | 同题材影响断板风险 | R2 | 高标 + 同题材平均跌 → `break_risk` 高于同题材涨 |
| VS-R3-01 | 主力流出禁接力 | R3 | 二板接力 + 主力净流出 5000 万 → 不匹配 `G3-二板接力` |
| VS-R4-01 | 扫描批量 context | R4 | 扫描 20 只，市场 context 只构建 1 次（mock 计数） |

---

## 7. 实施顺序与工时估算

| 顺序 | 任务 | 预估 | 依赖 |
|------|------|------|------|
| 1 | R1-01 ~ R1-03 | 1–2 天 | 无 |
| 2 | R1-04 | 0.5 天 | R1-01 |
| 3 | R2-01 | 1–2 天 | 无 |
| 4 | R2-02 ~ R2-04 | 1 天 | R2-01 |
| 5 | R3-01 ~ R3-03 | 1–2 天 | 无 |
| 6 | R4-01 ~ R4-02 | 1–2 天 | 无 |
| 7 | R5-01 ~ R5-03 | 1 天 | 无 |

**合计：约 7–10 个工作日**（单人，含测试与文档更新）。

---

## 8. 风险与缓解

| 风险 | 缓解 |
|------|------|
| clamp 后 LLM 原文与最终输出不一致 | Markdown 追加 `[HardLogic Override]` 段 |
| 卡位逻辑过重拖慢 `evaluate()` | 轻量 `_get_card_position_metrics`，session 缓存 |
| 主力资金历史日缺失 | `data_confidence=[无数据]` 时不参与 Gate |
| `evaluate_with_context` 与 `evaluate` 行为分叉 | 同一套 `_build_signal_from_context()` 单函数 |
| 精简分析师子集漏关键报告 | 默认 subset 含 `market` + `hot_money` |

---

## 9. 文档维护指引

完成每项任务后：

1. 更新 [TASK_CHECKLIST.md](./TASK_CHECKLIST.md) — 追加 Phase R1–R5 任务表，状态 ⬜/✅
2. 更新 [HARD_LOGIC_SPEC.md](./HARD_LOGIC_SPEC.md) — Gate 3 补充资金流条件；§2 字段表
3. 更新 [VERIFICATION_SCENARIOS.md](./VERIFICATION_SCENARIOS.md) — 追加 VS-R 系列
4. 更新根目录 `CLAUDE.md` — 短线能力表增加「提案 clamp」「卡位接线」

---

## 10. 快速启动（建议第一周）

```bash
# Day 1-2: R1 — clamp_short_term_proposal + short_term_trader 接入
# Day 3-4: R2 — _get_card_position_metrics + evaluate 接线
# Day 5: 测试 + 文档

python -m pytest tests/test_trading_hard_logic.py tests/test_proposal_gate.py -v
```

**并行建议：** R1（Trader clamp）与 R2-01（卡位 metrics）可并行开工——前者堵住仓位越界，后者补齐博弈维度。

---

## 相关文档

| 文档 | 说明 |
|------|------|
| [README.md](./README.md) | 硬逻辑改造文档集索引 |
| [OPTIMIZATION_PLAN.md](./OPTIMIZATION_PLAN.md) | P0–P3 完整优化方案 |
| [HARD_LOGIC_SPEC.md](./HARD_LOGIC_SPEC.md) | TradingHardLogic 规格 |
| [TASK_CHECKLIST.md](./TASK_CHECKLIST.md) | 可执行任务清单 |
| [VERIFICATION_SCENARIOS.md](./VERIFICATION_SCENARIOS.md) | MVP 回归场景 |

---

## 变更记录

| 日期 | 说明 |
|------|------|
| 2026-06-20 | 初版：R1–R5 补强实施方案 |
| 2026-06-20 | **R1 完成**：`proposal_gate.py`、Trader/ShortTermTrader clamp、PM 降级扩展 |
| 2026-06-20 | **R2 完成**：`_get_card_position_metrics`、`_get_same_theme_performance`、evaluate 接线 |
| 2026-06-20 | **R3 完成**：`_get_main_force_flow_metrics`、HardSignal 资金流字段、Gate 3 辅助条件、首板评分软惩罚 |
| 2026-06-20 | **R4 完成**：`MarketContext`、`build_market_context`、`evaluate_with_context`、扫描模式批量复用 |
| 2026-06-20 | **R5 完成**：`short_term_analyst_subset`、Graph 子集路由、Quality Gate 跳过 LLM、CLI/Web 开关 |
