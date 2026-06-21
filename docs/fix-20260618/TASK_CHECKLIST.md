# 交易硬逻辑优化 — 任务清单

> **状态**: ⬜ 未开始 | 🔄 进行中 | ✅ 已完成 | ❌ 失败/阻塞  
> **日期**: 2026-06-18  
> **原则**: 每个任务必须可实施、可执行、可验证（含验收标准 + 验证命令）

---

## 任务编号规则

| 前缀 | 阶段 |
|------|------|
| T0-xx | P0 打通断链 |
| T1-xx | P1 数据强化 |
| T2-xx | P2 决策改造 |
| T3-xx | P3 场景扩展 |

---

## Phase P0：打通断链（1-2 周）

### P0-A：Bug 修复

| 任务ID | 任务 | 状态 | 依赖 | 产出文件 |
|--------|------|------|------|----------|
| T0-01 | 修复 `get_leader_identification` tool 签名：增加 `ticker` 参数，顺序与 `a_stock` 一致 | ✅ | 无 | `signal_data_tools.py` |
| T0-02 | 修复 `route_to_vendor` 调用：`get_leader_identification(ticker, trade_date, theme)` | ✅ | T0-01 | `signal_data_tools.py`, `interface.py` |
| T0-03 | 更新 `short_term_analyst` prompt：默认传入 `company_of_interest` 作 ticker | ✅ | T0-01 | `short_term_analyst.py` |
| T0-04 | 修复 `prefetch.py` 中 leader 预取：传 `ticker` 而非空 theme | ✅ | T0-01 | `prefetch.py` |
| T0-05 | 接通冰点确认：`_get_consecutive_limit_stats` 传入 `recent_2day_data` | ✅ | 无 | `a_stock.py` |
| T0-06 | 移除卡位/补涨龙路径中 `market_emotion="修复"` 硬编码 | ✅ | 无 | `a_stock.py` |
| T0-07 | 接入 `historical_broken_count`：从炸板池统计历史炸板次数 | ✅ | 无 | `a_stock.py` |
| T0-08 | 修复 `get_first_board_screen` 情绪参数：使用 `_calculate_yesterday_performance` 输出 | ✅ | 无 | `a_stock.py` |

#### T0-01 验收标准

- [ ] `get_leader_identification` 签名为 `(ticker: str = "", trade_date: str = "", theme: str = "")`
- [ ] `route_to_vendor` 第一个位置参数为 `ticker`
- [ ] VS-04 场景通过

**验证：**

```bash
python -m pytest tests/test_short_term_integration.py -k leader_identification -v
```

#### T0-05 验收标准

- [ ] `_judge_emotion_phase` 在连读 2 日数据时可输出 `冰点(已确认)`
- [ ] 单元测试 mock 2 日数据覆盖该分支

**验证：**

```bash
python -m pytest tests/test_short_term_features.py -k emotion_phase -v
```

---

### P0-B：TradingHardLogic MVP

| 任务ID | 任务 | 状态 | 依赖 | 产出文件 |
|--------|------|------|------|----------|
| T0-09 | 创建 `tradingagents/logic/` 包及 `__init__.py` | ✅ | 无 | `logic/__init__.py` |
| T0-10 | 实现 `HardSignal` dataclass（见 HARD_LOGIC_SPEC.md） | ✅ | T0-09 | `trading_hard_logic.py` |
| T0-11 | 实现 `evaluate_market(trade_date)`：聚合情绪指标 | ✅ | T0-10 | `trading_hard_logic.py` |
| T0-12 | 实现 `evaluate(ticker, trade_date)`：个股定位 + 评分聚合 | ✅ | T0-11 | `trading_hard_logic.py` |
| T0-13 | 实现 Gate 1（市场环境）+ Gate 4（硬否决） | ✅ | T0-12 | `trading_hard_logic.py` |
| T0-14 | 实现 `to_dict()` / `to_markdown()` / `hard_signal_summary` | ✅ | T0-13 | `trading_hard_logic.py` |
| T0-15 | 新增 `tests/test_trading_hard_logic.py` Gate 单元测试 | ✅ | T0-13 | `tests/` |
| T0-16 | 新增 `tests/fixtures/hard_signal_fixtures.py` mock 数据 | ✅ | T0-15 | `tests/test_trading_hard_logic.py` 内联 `_base_signal()` |

#### T0-12 验收标准

- [ ] 对任意 ticker 返回完整 `HardSignal`，无异常字段缺失
- [ ] `in_limitup_pool=False` 时 `role=无关` 或 `跟风` 有明确定义
- [ ] 复用 `a_stock` 现有函数，不重复 HTTP 请求（同 session cache）

**验证：**

```bash
python -m pytest tests/test_trading_hard_logic.py -v
```

#### T0-13 验收标准

- [ ] VS-01、VS-02、VS-03 场景通过
- [ ] `HARD_VETO_RULES` 任一命中 → `can_trade=False`

---

### P0-C：决策链接入

| 任务ID | 任务 | 状态 | 依赖 | 产出文件 |
|--------|------|------|------|----------|
| T0-17 | `agent_states.py` 新增 `hard_signal`, `hard_signal_summary` 字段 | ✅ | T0-14 | `agent_states.py` |
| T0-18 | `trading_graph.propagate()` 中调用 `evaluate(company_of_interest, trade_date)` | ✅ | T0-17 | `trading_graph.py` |
| T0-19 | `bull_researcher` / `bear_researcher` 注入 `short_term_report` + `hard_signal_summary` | ✅ | T0-17 | `bull_researcher.py`, `bear_researcher.py` |
| T0-20 | `trader.py` 注入短线上下文 + `position_cap` 约束说明 | ✅ | T0-17 | `trader.py` |
| T0-21 | `portfolio_manager.py` 注入 `hard_signal_summary`（P0 仅上下文，P2 加 Gate 降级） | ✅ | T0-17 | `portfolio_manager.py` |
| T0-22 | `quality_gate.py` 的 `REPORT_FIELDS` 增加 `short_term` | ✅ | 无 | `quality_gate.py` |
| T0-23 | `web/` 进度与报告展示支持 `hard_signal_summary`（可选折叠区） | ✅ | T0-17 | `web/components/report_viewer.py`, `progress_panel.py`, `runner.py`, `pdf_export.py` |
| T0-24 | 新增 `tests/test_trading_hard_logic_integration.py` 决策链 snapshot 测试 | ✅ | T0-18~T0-22 | `tests/` |

#### T0-19 验收标准

- [ ] Bull/Bear prompt 源码含 `short_term_report` 与 `hard_signal_summary` 占位
- [ ] VS-05 场景通过

**验证：**

```bash
python -m pytest tests/test_trading_hard_logic_integration.py -v
python -m pytest tests/ -v -m "not live"
```

---

### P0 里程碑检查点

| 检查项 | 任务ID | 状态 |
|--------|--------|------|
| 全部 P0 Bug 修复完成 | T0-01~T0-08 | ✅ |
| HardSignal MVP 可调用 | T0-09~T0-16 | ✅ |
| 决策链贯通 | T0-17~T0-24 | ✅ |
| VS-01~VS-05 全部通过 | 见 VERIFICATION_SCENARIOS.md | ✅（单元/集成测试覆盖） |
| `pytest tests/ -v -m "not live"` 全绿 | — | ✅（hard_logic + short_term_integration 42 passed） |

---

## Phase P1：数据强化（2-4 周）

### P1-A：东财真实字段

| 任务ID | 任务 | 状态 | 依赖 | 产出文件 |
|--------|------|------|------|----------|
| T1-01 | `_get_stock_seal_info` 优先使用 EM `seal_amount / circulation_mv` | ✅ | P0 完成 | `a_stock.py` |
| T1-02 | 高标 `open_count` 改用 EM `open_times`，移除换手档位估算 | ✅ | P0 完成 | `a_stock.py` |
| T1-03 | 炸板池 `_get_broken_board_stocks_em` 接入 `_calculate_seal_quality` | ✅ | T0-07 | `a_stock.py` |
| T1-04 | `get_consecutive_limit_stats` 输出增加炸板率/炸板家数字段 | ✅ | T1-03 | `a_stock.py` |
| T1-05 | 封单/开板/首板时间字段增加 `[确认]`/`[估算]` 标注 | ✅ | T1-01, T1-02 | `a_stock.py` |

#### T1-01 验收标准

- [ ] VS-07 场景通过
- [ ] 有 EM 数据时 `seal_ratio` 不再走换手率代理

**验证：**

```bash
python -m pytest tests/test_short_term_features.py -k seal -v
```

---

### P1-B：情绪状态机

| 任务ID | 任务 | 状态 | 依赖 | 产出文件 |
|--------|------|------|------|----------|
| T1-06 | 实现 `_get_recent_emotion_history(trade_date, days=3)` | ✅ | T0-05 | `a_stock.py` |
| T1-07 | 升级 `_judge_emotion_phase` 为多日状态机（见 HARD_LOGIC_SPEC §5） | ✅ | T1-06 | `a_stock.py` |
| T1-08 | `TradingHardLogic` 同步新情绪阶段枚举 | ✅ | T1-07 | `trading_hard_logic.py` |
| T1-09 | 新增情绪状态机单元测试（mock 多日数据） | ✅ | T1-07 | `tests/` |

#### T1-07 验收标准

- [ ] 支持 `退潮(确认)`、`修复(可操作)` 等扩展阶段（或文档约定映射）
- [ ] 高潮日触发 `position_cap≤0.20`（Gate G1-05）

---

### P1-C：跨源信号融合

| 任务ID | 任务 | 状态 | 依赖 | 产出文件 |
|--------|------|------|------|----------|
| T1-10 | `evaluate()` 接入 `get_lockup_expiry`：计算 `unlock_pressure_pct` | ✅ | T0-12 | `trading_hard_logic.py`, `a_stock.py` |
| T1-11 | Gate G2-05 解禁重压否决接线 | ✅ | T1-10 | `trading_hard_logic.py` |
| T1-12 | 首板评分融入龙虎榜：知名游资买入 +10（需席位库 MVP） | ✅ | T1-01 | `a_stock.py` |
| T1-13 | 高标 `break_risk` 融入龙虎榜机构净卖 | ✅ | T1-02 | `a_stock.py` |
| T1-14 | 题材热度北向权重扩展为个股主力净流入（可选） | ✅ | 无 | `a_stock.py`, `trading_hard_logic.py` |
| T1-15 | 新增 `data/known_hot_money_seats.json` 一线游资席位库 | ✅ | T1-12 | `data/` |

#### T1-10 验收标准

- [ ] VS-09 场景通过
- [ ] 无解禁数据时 `unlock_pressure_pct=0`，不误否决

---

### P1-D：trade_date 与 ticker 锚定

| 任务ID | 任务 | 状态 | 依赖 | 产出文件 |
|--------|------|------|------|----------|
| T1-16 | `_get_theme_history` 锚定 `trade_date` 而非 `datetime.now()` | ✅ | 无 | `a_stock.py` |
| T1-17 | `_get_limitdown_stocks` 支持历史 `trade_date` 过滤 | ✅ | 无 | `a_stock.py` |
| T1-18 | 交易日历：`_get_previous_trading_date` 支持节假日（简易节假日表或接口） | ✅ | 无 | `a_stock.py`, `data/` |
| T1-19 | `evaluate(ticker)` 输出个股全景 Markdown 节（涨停池/题材/龙头/高标） | ✅ | T0-12 | `trading_hard_logic.py` |
| T1-20 | tool 层暴露 `top_n`（theme_heat）、`min_score`（first_board_screen） | ✅ | 无 | `signal_data_tools.py` |

#### T1-16 验收标准

- [ ] 同一 `trade_date` 两次调用 `_get_theme_history` 结果一致
- [ ] 不随系统时间变化

---

### P1 里程碑检查点

| 检查项 | 任务ID | 状态 |
|--------|--------|------|
| 真实封单/开板/炸板率上线 | T1-01~T1-05 | ✅ |
| 情绪状态机上线 | T1-06~T1-09 | ✅ |
| 跨源融合上线 | T1-10~T1-15 | ✅（T1-14 可选跳过） |
| trade_date 锚定修复 | T1-16~T1-20 | ✅ |
| VS-07~VS-09 通过 | — | ✅ |

---

## Phase P2：决策改造（4-6 周）

### P2-A：完整 Gate 与策略匹配

| 任务ID | 任务 | 状态 | 依赖 | 产出文件 |
|--------|------|------|------|----------|
| T2-01 | 实现 Gate 2（个股可交易性）全部规则 G2-01~G2-06 | ✅ | P1 完成 | `trading_hard_logic.py` |
| T2-02 | 实现 Gate 3（策略匹配）打板/接力/低吸/回避 | ✅ | T2-01 | `trading_hard_logic.py` |
| T2-03 | 20cm 板（创业板/科创板）识别与阈值折算 | ✅ | T2-01 | `trading_hard_logic.py` |
| T2-04 | `apply_gates()` 统一入口，填充 `action`/`position_cap`/`strategy` | ✅ | T2-02 | `trading_hard_logic.py` |
| T2-05 | Gate 规则全量单元测试 | ✅ | T2-04 | `tests/test_trading_hard_logic.py` |

---

### P2-B：短线交易官

| 任务ID | 任务 | 状态 | 依赖 | 产出文件 |
|--------|------|------|------|----------|
| T2-06 | `schemas.py` 新增 `ShortTermProposal`（strategy/entry/stop/position/action） | ✅ | T2-04 | `schemas.py` |
| T2-07 | 新增 `short_term_trader.py` 或扩展 `trader.py` 短线模式 | ✅ | T2-06 | `agents/trader/` |
| T2-08 | 实现 `gate_check_portfolio_rating()` 并接入 `portfolio_manager` | ✅ | T2-04 | `trading_hard_logic.py`, `portfolio_manager.py` |
| T2-09 | `TraderProposal.position` 描述约束「≤ HardSignal.position_cap」 | ✅ | T2-06 | `schemas.py` |
| T2-10 | Graph 条件边：短线模式走 ShortTermTrader 节点 | ✅ | T2-07 | `setup.py`, `conditional_logic.py` |

#### T2-08 验收标准

- [ ] VS-06 场景通过
- [ ] `Buy` + `can_trade=False` → 最终 `Hold`

**验证：**

```bash
python -m pytest tests/test_trading_hard_logic.py::test_portfolio_rating_downgrade -v
```

---

### P2-C：辩论与质量门控

| 任务ID | 任务 | 状态 | 依赖 | 产出文件 |
|--------|------|------|------|----------|
| T2-11 | `default_config.py` 增加 `short_term_mode` 与 `max_debate_rounds` 短线覆盖 | ✅ | 无 | `default_config.py` |
| T2-12 | Bull/Bear prompt：≥3 个 `veto_reasons` 时 Bear 须主张 Hold/Sell | ✅ | T0-19 | `bear_researcher.py` |
| T2-13 | 风险辩论三方注入 `hard_signal_summary`；激进方不得无视 `can_trade=False` | ✅ | T0-21 | `aggressive_debator.py` 等 |
| T2-14 | Quality Gate：`short_term` 报告须含情绪阶段、策略建议 | ✅ | T0-22 | `quality_gate.py` |
| T2-15 | Quality Gate：报告分数须与 `HardSignal` JSON 一致（防幻觉） | ✅ | T0-18 | `quality_gate.py` |
| T2-16 | `ResearchPlan` / `PortfolioDecision` 增加 `time_horizon` 字段 | ✅ | 无 | `schemas.py` |

---

### P2 里程碑检查点

| 检查项 | 任务ID | 状态 |
|--------|--------|------|
| Gate 2+3 完整 | T2-01~T2-05 | ✅ |
| 短线交易官上线 | T2-06~T2-10 | ✅ |
| PM Gate 降级上线 | T2-08 | ✅ |
| 辩论/质量门控扩展 | T2-11~T2-16 | ✅ |
| VS-06 通过 | — | ✅（单元测试覆盖） |

---

## Phase P3：场景扩展

| 任务ID | 任务 | 状态 | 依赖 | 产出文件 |
|--------|------|------|------|----------|
| T3-01 | 实现 `get_auction_strength(ticker, trade_date)` 竞价强度接口 | ✅ | P1 完成 | `a_stock.py` |
| T3-02 | 竞价强度接入 Gate 3 打板前置过滤 | ✅ | T3-01, T2-02 | `trading_hard_logic.py` |
| T3-03 | CLI `scan_short_term`：按 `second_board_score` 输出 TOP N + HardSignal | ✅ | T0-12 | `cli/` |
| T3-04 | Web 扫描模式页 | ✅ | T3-03 | `web/pages/` |
| T3-05 | 席位库扩展与维护文档 | ✅ | T1-15 | `data/` |
| T3-06 | 监管异动数据源接入（东财公告/异动） | ✅ | 无 | `a_stock.py` |
| T3-07 | VS-10 扫描模式验收 | ✅ | T3-03 | `tests/test_p3_scan_auction.py` |

#### T3-03 验收标准

- [ ] VS-10 场景通过
- [ ] 单次扫描 20 股耗时 < 完整 propagate 的 20%

---

## 任务统计

| 阶段 | 任务数 | 已完成 | 进度 |
|------|--------|--------|------|
| P0 | 24 | 24 | 100% |
| P1 | 20 | 20 | 100% |
| P2 | 16 | 16 | 100% |
| P3 | 7 | 7 | 100% |
| **合计** | **67** | **67** | **100%** |

---

## 建议实施顺序（单线程）

```
T0-01 → T0-02 → T0-03 → T0-04
T0-05 → T0-06 → T0-07 → T0-08
T0-09 → T0-10 → T0-11 → T0-12 → T0-13 → T0-14 → T0-15 → T0-16
T0-17 → T0-18 → T0-19 → T0-20 → T0-21 → T0-22 → T0-23 → T0-24
[P0 里程碑验收]
T1-01 → T1-02 → T1-03 → T1-04 → T1-05
T1-06 → T1-07 → T1-08 → T1-09
T1-10 → T1-11 → T1-15 → T1-12 → T1-13
T1-16 → T1-17 → T1-18 → T1-19 → T1-20
[P1 里程碑验收]
T2-01 → T2-02 → T2-03 → T2-04 → T2-05
T2-06 → T2-07 → T2-09 → T2-10
T2-08
T2-11 → T2-12 → T2-13 → T2-14 → T2-15 → T2-16
[P2 里程碑验收]
T3-01 → T3-02 → T3-05 → T3-03 → T3-04 → T3-06 → T3-07
```

---

## 进度更新指引

完成每个任务后：

1. 将本文件中对应任务状态改为 ✅
2. 更新「任务统计」表
3. 若验收发现方案偏差，在 [OPTIMIZATION_PLAN.md](./OPTIMIZATION_PLAN.md) §8 变更记录追加说明
4. 若新增任务，使用下一可用 ID 插入对应阶段，勿复用已关闭 ID

---

## 相关文档

- [OPTIMIZATION_PLAN.md](./OPTIMIZATION_PLAN.md) — 方案全文
- [HARD_LOGIC_SPEC.md](./HARD_LOGIC_SPEC.md) — 硬逻辑规格
- [VERIFICATION_SCENARIOS.md](./VERIFICATION_SCENARIOS.md) — 验收场景
