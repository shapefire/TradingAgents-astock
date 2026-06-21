# 交易硬逻辑优化方案（2026-06-18）

> 从「研报生成器」升级为「可执行交易硬逻辑」体系的改造文档集。

## 背景

TradingAgents-Astock 在数据层（`a_stock.py`）已具备 A 股短线评分框架（情绪周期、首板筛选、龙头识别等），但决策层仍以 LLM 软判断为主，且 `short_term_report` 未进入 Bull/Bear → Trader → PM 决策链。本方案旨在打通断链、强化数据真实性、引入程序化 Gate 否决。

## 文档索引

| 文档 | 说明 |
|------|------|
| [OPTIMIZATION_PLAN.md](./OPTIMIZATION_PLAN.md) | 完整优化方案：现状诊断、架构目标、分阶段路线 |
| [HARD_LOGIC_SPEC.md](./HARD_LOGIC_SPEC.md) | `TradingHardLogic` 硬逻辑层规格：数据结构、Gate 规则、策略匹配 |
| [TASK_CHECKLIST.md](./TASK_CHECKLIST.md) | **可实施任务清单**（含验收标准与验证命令） |
| [VERIFICATION_SCENARIOS.md](./VERIFICATION_SCENARIOS.md) | MVP 回归场景与期望输出 |
| [REINFORCEMENT_PLAN.md](./REINFORCEMENT_PLAN.md) | **补强实施方案**（R1–R5：Trader clamp、卡位接线、资金流、批量扫描） |

## 阶段概览

```
P0 打通断链（1-2 周）
  ├── Bug 修复（leader 参数、冰点确认、硬编码）
  ├── 决策链接入 short_term_report + HardSignal JSON
  └── TradingHardLogic MVP

P1 数据强化（2-4 周）
  ├── 东财真实字段替换代理指标
  ├── 炸板池 / 冰点确认接线
  └── 跨源信号融合（龙虎榜、解禁、资金流）

P2 决策改造（4-6 周）
  ├── 短线交易官节点
  ├── Gate 否决 + 评级校验
  └── Quality Gate / 辩论权重扩展

P3 场景扩展（按需）
  ├── 游资席位库 + 竞价强度
  └── 扫描模式 CLI / Web
```

## 进度追踪

任务状态在 [TASK_CHECKLIST.md](./TASK_CHECKLIST.md) 中维护：

- ⬜ 未开始
- 🔄 进行中
- ✅ 已完成
- ❌ 失败 / 阻塞

## 相关代码路径

| 模块 | 路径 |
|------|------|
| 短线评分引擎 | `tradingagents/dataflows/a_stock.py` |
| 工具包装层 | `tradingagents/agents/utils/signal_data_tools.py` |
| 短线分析师 | `tradingagents/agents/analysts/short_term_analyst.py` |
| 决策链 | `tradingagents/agents/trader/trader.py`, `researchers/`, `managers/` |
| 质量门控 | `tradingagents/agents/quality_gate.py` |
| 硬逻辑层（待建） | `tradingagents/logic/trading_hard_logic.py` |

## 变更记录

| 日期 | 说明 |
|------|------|
| 2026-06-18 | 初版方案与任务清单 |
| 2026-06-18 | P1 启动：T1-01 东财真实封单比接入 `_get_stock_seal_info` |
| 2026-06-18 | P1：T1-02 高标 open_count 改用东财 open_times |
| 2026-06-18 | P1：T1-03 炸板池接入 `_calculate_seal_quality` |
| 2026-06-18 | P1：T1-04 连板统计输出展示炸板率/炸板家数 |
| 2026-06-18 | P1：T1-16~T1-20 trade_date 锚定 + evaluate 个股全景 + tool 参数暴露 |
| 2026-06-18 | P1：T1-10~T1-11 解禁压力接入 evaluate + G2-05 否决 |
| 2026-06-18 | P1：T1-06~T1-09 多日情绪状态机 + G1-05 高潮减仓 Gate |
| 2026-06-18 | P2：T2-01~T2-05 Gate 2/3 完整实现 + 20cm 折算 + 全量单元测试 |
| 2026-06-18 | P3：T3-01~T3-07 竞价强度 + 扫描模式 CLI/Web + 监管异动 |
| 2026-06-18 | P2：T2-06~T2-11 短线交易官 ShortTermProposal + graph 路由 |
| 2026-06-20 | R3：T1-14 主力资金接入 HardSignal + Gate 3 辅助条件 |
| 2026-06-20 | R4：MarketContext 批量 evaluate，扫描模式提速 |
| 2026-06-20 | R5：短线精简模式（4 分析师子集 + 跳过 QG LLM） |
