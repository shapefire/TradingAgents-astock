# 交易硬逻辑优化方案

> 版本：v0.1 | 日期：2026-06-18 | 状态：方案阶段

## 1. 现状诊断

### 1.1 架构分层

| 层级 | 现状 | 核心问题 |
|------|------|----------|
| 数据层 (`a_stock.py`) | 5 个短线接口，含权重、阈值、情绪阶段 | 部分指标为代理；已写逻辑未接线 |
| Agent 层 | 8 分析师产出 Markdown 报告 | `short_term_report` 未进决策链 |
| 决策层 | Bull/Bear → RM → Trader → 风险辩论 → PM | **100% LLM 软判断**，无程序化否决 |
| 输出层 | 5 档/3 档评级 + 正则解析 | 无仓位上限、无策略类型、无硬止损 |

### 1.2 核心矛盾

底层已有 A 股短线框架（情绪周期、首板评分、龙头卡位），决策层完全感知不到这些硬信号。

### 1.3 已知缺陷（P0 优先修复）

| ID | 缺陷 | 影响 |
|----|------|------|
| D-01 | `short_term_report` 未接入 Bull/Bear / Trader / PM / Quality Gate | 短线结论不影响最终评级 |
| D-02 | `get_leader_identification` tool 参数顺序与 `a_stock` 不一致 | Agent 调用时 `trade_date` 被当作 `ticker` |
| D-03 | 冰点确认 `recent_2day_data` 从未传入 | 「冰点（已确认）」逻辑失效 |
| D-04 | `market_emotion="修复"` 多处硬编码 | 卡位/补涨龙判断失真 |
| D-05 | `historical_broken_count=0` 硬编码 | 炸板历史未计入龙头评分 |
| D-06 | 炸板池 `_get_broken_board_stocks_em` 已获取未使用 | 封板质量为代理指标 |
| D-07 | 东财 `open_times` / `seal_amount` 未用于高标/封单评分 | 开板次数、封单强度靠估算 |
| D-08 | `get_first_board_screen` 情绪参数传错 | 首板二板预期分偏差 |
| D-09 | `_get_theme_history` 锚定 `now` 而非 `trade_date` | 历史回测题材趋势错误 |
| D-10 | 短线工具偏全市场扫描，非 ticker 锚定 | 分析指定个股需 LLM 自行关联 |

---

## 2. 目标架构

### 2.1 改造前后对比

**改造前（断链）：**

```
短线分析师 → short_term_report → [仅 Web/日志]
                                      ↓
Bull/Bear(无短线) → RM → Trader(无短线) → PM → 最终评级
```

**改造后（贯通）：**

```
a_stock 评分函数
    ↓
TradingHardLogic.evaluate(ticker, trade_date)  →  HardSignal JSON
    ↓                              ↓
short_term_report (Markdown)   Gate 否决层
    ↓                              ↓
Bull/Bear / Trader / PM / Quality Gate
    ↓
最终评级（可被 Gate 降级）
```

### 2.2 设计原则

1. **硬逻辑优先，LLM 解读为辅** — 数字与 Gate 由代码计算，LLM 写「为什么」
2. **可否决不可覆盖** — Gate 否决不能被 prompt 绕过
3. **策略与情绪绑定** — 同一 ticker 在不同情绪阶段策略不同
4. **诚实标注置信度** — 代理数据标 `[估算]`，真实数据标 `[确认]`
5. **T+1 内置** — 短线策略 horizon ≤ 3 日，止损规则写死在 Schema

---

## 3. 核心交付物

### 3.1 TradingHardLogic 硬逻辑层

新模块：`tradingagents/logic/trading_hard_logic.py`

职责：聚合现有 5 个短线接口的评分结果，对目标 ticker 输出结构化 `HardSignal`（详见 [HARD_LOGIC_SPEC.md](./HARD_LOGIC_SPEC.md)）。

### 3.2 Gate 规则库

四层 Gate：

| Gate | 职责 |
|------|------|
| Gate 1 市场环境 | 冰点/退潮总开关、广度、昨日连板溢价 |
| Gate 2 个股可交易性 | ST、一字不可买、20cm、市值、解禁 |
| Gate 3 策略匹配 | 打板/接力/低吸/回避的入场硬条件 |
| Gate 4 风险否决 | 不可被 LLM 覆盖的硬否决 |

### 3.3 决策链改造

- Bull/Bear、Trader、PM 注入 `short_term_report` + `HardSignal` 摘要
- Quality Gate 覆盖 `short_term` 分析师
- Portfolio Manager 输出前执行 Gate 校验，冲突时降级

### 3.4 数据层强化

- 东财真实字段替换代理指标
- 炸板率纳入封板质量
- 龙虎榜 / 解禁 / 资金流融入评分
- 情绪周期升级为多日状态机

---

## 4. 分阶段路线图

### Phase P0：打通断链（1-2 周）

**目标：** 分析指定 ticker 时，短线硬信号能影响最终评级。

| 交付 | 说明 |
|------|------|
| Bug 修复包 | D-02 ~ D-05, D-08 |
| `HardSignal` dataclass + `evaluate()` MVP | 聚合情绪 + 个股定位 |
| 决策链接入 | Bull/Bear / Trader / PM / Quality Gate |
| 基础 Gate 1 + Gate 4 | 冰点禁止交易、高标分歧回避 |
| 单元测试 + 场景回归 | 见 [VERIFICATION_SCENARIOS.md](./VERIFICATION_SCENARIOS.md) |

### Phase P1：数据强化（2-4 周）

**目标：** 评分与实盘盘口逻辑对齐度显著提升。

| 交付 | 说明 |
|------|------|
| 东财 `seal_amount` / `open_times` 接入 | 封单强度、开板次数 |
| 炸板池接入封板质量 | 炸板率、回封率 |
| 冰点确认 + 情绪状态机 | 多日 regime |
| 跨源融合 | 龙虎榜、解禁、资金流 |
| ticker 锚定 `evaluate()` | 一次调用输出个股全景 |
| `trade_date` 锚定修复 | 题材历史、涨跌停日期 |

### Phase P2：决策改造（4-6 周）

**目标：** LLM 无法「冰点满仓打板」。

| 交付 | 说明 |
|------|------|
| 短线交易官节点 | `ShortTermProposal` Schema |
| Gate 2 + Gate 3 完整实现 | 策略匹配 + 仓位上限 |
| PM 评级 Gate 校验 | 程序化降级 |
| 辩论轮次 / 权重调整 | 短线模式 2 轮辩论 |
| Quality Gate 硬逻辑一致性检查 | 报告分数与 JSON 一致 |

### Phase P3：场景扩展（按需）

| 交付 | 说明 |
|------|------|
| 游资席位库 | 龙虎榜席位加分/减分 |
| 竞价强度接口 | `get_auction_strength()` |
| 扫描模式 | CLI/Web TOP20 清单，跳过完整 8 Agent |

---

## 5. 优先级矩阵

按「贴近实盘 × 实现成本」排序：

| 优先级 | 项 | 阶段 |
|--------|-----|------|
| P0-1 | 决策链打通 + HardSignal | P0 |
| P0-2 | 市场环境 Gate | P0 |
| P0-3 | leader 参数 Bug 修复 | P0 |
| P1-1 | 东财真实字段替换 | P1 |
| P1-2 | 个股锚定 evaluate | P1 |
| P1-3 | 炸板池 + 冰点确认 | P1 |
| P1-4 | 龙虎榜/解禁融合 | P1 |
| P2-1 | 短线交易官 + 完整 Gate | P2 |
| P3-1 | 竞价 / 席位库 / 扫描模式 | P3 |

---

## 6. 风险与约束

| 风险 | 缓解 |
|------|------|
| 东财限流 (`EM_MIN_INTERVAL`) | 批量扫描设 `EM_MIN_INTERVAL=1.5~2`；HardLogic 复用 session cache |
| LLM 忽略 HardSignal | 结构化 JSON 强制注入 + Gate 程序化降级 |
| 历史 `trade_date` 数据缺失 | EM 涨停池约 2 周；回测需标注数据可用区间 |
| 改动面大导致回归 | 每任务独立测试；`pytest tests/ -v` 为合并门槛 |
| mootdx 依赖冲突 | 不新增重量级依赖；席位库用本地 JSON |

---

## 7. 成功标准（P0 MVP）

完成 P0 后应满足：

1. `TradingHardLogic.evaluate("000001", date)` 返回完整 `HardSignal`
2. 冰点日 `can_trade=False`，PM 输出不得为 Buy（或被 Gate 降级）
3. `get_leader_identification` 经 tool 路径传入 ticker 结果正确
4. Bull/Bear prompt 含 `short_term_report` 片段
5. `pytest tests/test_trading_hard_logic.py` 全绿（新建）

详细场景见 [VERIFICATION_SCENARIOS.md](./VERIFICATION_SCENARIOS.md)。

---

## 8. 参考

- 现有短线实施清单：`docs/feat/IMPLEMENTATION_TASKS.md`
- 数据层入口：`tradingagents/dataflows/a_stock.py`
- 项目架构：`CLAUDE.md`
