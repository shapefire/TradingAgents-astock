# TradingHardLogic 硬逻辑层规格

> 版本：v0.1 | 日期：2026-06-18

## 1. 模块定位

| 属性 | 值 |
|------|-----|
| 路径 | `tradingagents/logic/trading_hard_logic.py` |
| 依赖 | `a_stock.py` 现有评分函数（不重复拉数） |
| 输出 | `HardSignal` dataclass + `to_markdown()` / `to_dict()` |
| 调用方 | `trading_graph.py` prefetch 后、`short_term_analyst` 补充、`trader`/`PM` Gate 校验 |

---

## 2. HardSignal 数据结构

```python
@dataclass
class HardSignal:
    ticker: str
    trade_date: str

    # --- 市场环境 ---
    emotion_phase: str          # 冰点/冰点(已确认)/退潮/修复/升温/高潮/低迷
    emotion_score: int          # 0-100
    breadth_signal: str         # 强势/正常/弱势
    yesterday_limitup_avg_return: float
    can_trade: bool             # 总开关
    market_gate_passed: bool

    # --- 个股定位 ---
    in_limitup_pool: bool
    consecutive_days: int
    role: str                   # 总龙头/题材龙头/首板候选/高标/跟风/无关/断板龙头
    theme: str
    theme_rank: int             # 题材热度排名，0=未上榜
    second_board_score: int     # 首板二板预期分，非首板为 -1
    leader_score: int           # 龙头评分，非龙头候选为 -1
    divergence_score: int       # 高标分歧度，非高标为 -1
    break_risk: str             # 高/中/低/不适用
    seal_ratio: float           # 封单比 (%)，-1=未知
    is_yizi_unbuyable: bool

    # --- 风险因子 ---
    unlock_pressure_pct: float  # 30日内解禁占比，0=无数据
    has_regulatory_alert: bool  # 监管异动，默认 False
    st_flag: bool

    # --- 硬规则结论 ---
    action: str                 # 打板/接力/低吸/观望/回避
    position_cap: float         # 最大仓位 0.0~1.0
    strategy: str               # 与 action 对应的策略标签
    veto_reasons: list[str]
    gates_passed: list[str]
    confidence: str             # high/medium/low（基于数据完整度）

    # --- 元数据 ---
    data_sources: dict          # 各字段数据来源与置信度标注
```

---

## 3. 主入口 API

```python
def evaluate(ticker: str, trade_date: str = "") -> HardSignal:
    """对单只股票聚合短线硬逻辑结论。"""

def evaluate_market(trade_date: str = "") -> MarketSnapshot:
    """仅市场环境，不绑定 ticker（用于扫描模式）。"""

def apply_gates(signal: HardSignal) -> HardSignal:
    """执行 Gate 1-4，填充 can_trade / action / veto_reasons。"""

def gate_check_portfolio_rating(
    rating: str, signal: HardSignal
) -> tuple[str, list[str]]:
    """PM 评级与 HardSignal 冲突时返回降级后评级 + 原因。"""
```

---

## 4. Gate 规则定义

### 4.1 Gate 1：市场环境

| 规则 ID | 条件 | 结果 |
|---------|------|------|
| G1-01 | `emotion_phase ∈ {冰点, 冰点(已确认)}` | `can_trade=False`, `action=观望` |
| G1-02 | `emotion_score < 30` | 禁止打板/接力；仅允许低吸且 `position_cap≤0.10` |
| G1-03 | `breadth_signal=弱势` 且涨跌比 < 0.8 | 禁止接力 |
| G1-04 | `yesterday_limitup_avg_return < -3%` | 禁止高位接力 |
| G1-05 | `emotion_phase=高潮` 且 `emotion_score>70` | `position_cap≤0.20`（次日接力减仓） |

### 4.2 Gate 2：个股可交易性

| 规则 ID | 条件 | 结果 |
|---------|------|------|
| G2-01 | ST / *ST | `veto: ST股` |
| G2-02 | 一字板 + 换手 < 0.5% | `veto: 一字不可买`, `is_yizi_unbuyable=True` |
| G2-03 | 创业板/科创板 20cm | 封单阈值 ×0.8，仓位 ×0.5 |
| G2-04 | 流通市值 > 300亿 | 禁止打板 |
| G2-05 | 30日内解禁占比 > 10% | `veto: 解禁重压` |
| G2-06 | `has_regulatory_alert=True` | `veto: 监管异动` |

### 4.3 Gate 3：策略匹配

| 策略 | 全部满足条件 | position_cap |
|------|-------------|--------------|
| 首板打板 | 情绪≥修复；`second_board_score≥70`；封单比>3%；首板时间<10:30；题材 TOP3 | 0.15 |
| 二板接力 | 情绪∈{修复,升温}；龙头封板；晋级率>40%；分歧度<50 | 0.20 |
| 高标接力 | 情绪=高潮；分歧度<70；break_risk=低；板块效应强 | 0.10 |
| 龙头低吸 | 龙头断板首日；跌幅 -5%~-9%；题材仍 TOP5；无卡位成功 | 0.10 |
| 回避 | break_risk=高 或 分歧度≥70 或 龙头断板+题材退潮 | 0.00 |

**优先级：** 回避 > 策略匹配 > 观望。多个策略满足时取 `position_cap` 最高者。

### 4.4 Gate 4：硬否决（不可覆盖）

```python
HARD_VETO_RULES = [
    ("冰点确认", lambda s: s.emotion_phase == "冰点(已确认)"),
    ("高标重度分歧", lambda s: s.divergence_score >= 70),
    ("断板龙头+退潮", lambda s: s.role == "断板龙头" and s.emotion_phase in ("退潮", "冰点")),
    ("解禁重压", lambda s: s.unlock_pressure_pct > 10),
    ("一字不可买", lambda s: s.is_yizi_unbuyable),
    ("监管异动", lambda s: s.has_regulatory_alert),
]
```

任一命中 → `can_trade=False`, `action=回避`, 追加 `veto_reasons`。

---

## 5. 情绪状态机（P1 升级）

在现有 `_judge_emotion_phase()` 基础上扩展：

```
冰点(确认) = 连续2日: 最高板≤2 AND 闷杀率>30% AND 涨停<15
退潮(确认) = 前日高潮/升温 AND 今日最高板断板 AND 晋级率<30%
修复(可操作) = 冰点/退潮后: 首板数回升 AND 昨日涨停均收益>0 AND 核按钮占比<20%
高潮(减仓)  = 最高板≥5 AND 情绪分>70 AND 涨停>50
```

P0 先接通现有 `_judge_emotion_phase()` + `recent_2day_data`；P1 实现完整状态机。

---

## 6. 与决策链集成

### 6.1 State 新增字段

```python
# agent_states.py
hard_signal: Annotated[str, "JSON-serialized HardSignal for target ticker"]
hard_signal_summary: Annotated[str, "Markdown summary for LLM context"]
```

### 6.2 注入点

| 节点 | 注入内容 |
|------|----------|
| `trading_graph.propagate()` | prefetch 后调用 `evaluate(company_of_interest, trade_date)` |
| `bull_researcher` / `bear_researcher` | `short_term_report` + `hard_signal_summary` |
| `trader` | 同上 + `position_cap` 约束写入 prompt |
| `portfolio_manager` | `gate_check_portfolio_rating()` 后输出 |
| `quality_gate` | 校验报告与 HardSignal 一致性 |

### 6.3 PM 降级逻辑

```python
if rating in ("Buy", "Overweight") and not signal.can_trade:
    rating = "Hold"
    reasons.append(f"HardGate否决: {', '.join(signal.veto_reasons)}")
```

---

## 7. 数据置信度标注

| 字段 | 高置信 | 中置信 | 低置信 |
|------|--------|--------|--------|
| 封单比 | EM `seal_amount` 有值 | 成交额/流通市值 | 换手率代理 |
| 首板时间 | EM `fbt` 有值 | K线估算 | 默认 10:00 |
| 开板次数 | EM `open_times` | — | 换手档位估算 |
| 炸板历史 | 炸板池有记录 | — | 默认 0 |
| 解禁压力 | `get_lockup_expiry` 有数据 | — | 默认 0 |

`confidence` 字段规则：≥3 个核心字段为低置信 → `low`；全部高置信 → `high`；其余 `medium`。

---

## 8. 输出示例

```markdown
## 硬逻辑信号 — 000001 (2026-06-16)

| 维度 | 值 |
|------|-----|
| 情绪阶段 | 修复 (score=58) |
| 个股角色 | 首板候选 |
| 二板预期分 | 72 |
| 建议策略 | 打板 |
| 仓位上限 | 15% |
| 总开关 | ✅ 可交易 |

**通过 Gate:** G1-市场修复, G3-首板打板
**否决:** 无
**置信度:** medium（首板时间[估算]）
```

---

## 9. 测试要求

- `tests/test_trading_hard_logic.py`：Gate 规则单元测试（mock HardSignal，不依赖网络）
- `tests/test_trading_hard_logic_integration.py`：可选 live smoke（标记 `@pytest.mark.live`）
- 场景回归：见 [VERIFICATION_SCENARIOS.md](./VERIFICATION_SCENARIOS.md)
