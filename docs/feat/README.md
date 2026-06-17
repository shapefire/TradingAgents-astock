# 短线交易能力扩展实施方案

## 项目目标

补齐现有 A 股接口在**短线/超短线交易决策支撑**层面的能力缺口，从"信息获取"升级到"决策支撑"。

## 能力分层

```
┌─────────────────────────────────────────────────────────┐
│                    决策层（Agent）                        │
│   short_term_analyst 🆕（短线博弈分析师）                 │
├─────────────────────────────────────────────────────────┤
│                    信号层（Tools）                        │
│   连板梯队 / 题材热度 / 首板筛选 / 高标状态 / 龙头识别   │
├─────────────────────────────────────────────────────────┤
│                    数据层（Vendor）                       │
│   东财 datacenter / push2 / mootdx / 同花顺 hsgtApi     │
└─────────────────────────────────────────────────────────┘
```

## 实施计划

### Phase 0：接口验证（⚠️ 必须先完成）

| 序号 | 功能 | 说明 | 优先级 |
|------|------|------|--------|
| 0 | 接口字段验证 | 实测东财涨停列表接口字段 | P0 |
| 0 | 涨停原因归一化 | 构建原因映射表 | P0 |
| 0 | 数据可用性确认 | 封单/撤单/涨跌家数接口 | P0 |

### Phase 1：情绪量化基础（P0）

| 序号 | 功能 | 文档 | 优先级 | 评审修正 |
|------|------|------|--------|----------|
| 1 | 连板梯队统计 + 情绪量化 | [01_consecutive_limit_stats.md](./01_consecutive_limit_stats.md) | P0 | 6项 |
| 2 | 题材热度追踪 | [02_theme_heat_tracking.md](./02_theme_heat_tracking.md) | P0 | 4项 |

### Phase 2：选股筛选能力（P1）

| 序号 | 功能 | 文档 | 优先级 | 评审修正 |
|------|------|------|--------|----------|
| 3 | 首板筛选 + 二板预期 | [03_first_board_screen.md](./03_first_board_screen.md) | P1 | 5项 |
| 4 | 高标股状态监控 | [04_high_board_status.md](./04_high_board_status.md) | P1 | 4项 |

### Phase 3：博弈分析能力（P2）

| 序号 | 功能 | 文档 | 优先级 | 评审修正 |
|------|------|------|--------|----------|
| 5 | 龙头识别 + 卡位分析 | [05_leader_identification.md](./05_leader_identification.md) | P2 | 5项 |

## 技术架构

### 新增文件结构

```
tradingagents/
├── dataflows/
│   └── a_stock.py                    # 新增数据接口
├── agents/
│   ├── utils/
│   │   ├── signal_data_tools.py      # 新增 @tool 包装
│   │   └── agent_utils.py            # 导出新工具
│   └── analysts/
│       ├── short_term_analyst.py     # 🆕 短线博弈分析师
│       ├── market_analyst.py         # 不变
│       └── hot_money_tracker.py      # 不变
└── tests/
    ├── test_phase0_api_verification.py  # 🆕 Phase 0 验证
    ├── test_short_term_features.py   # 单元测试
    └── test_short_term_integration.py # 集成测试
```

### 接口注册流程

```
1. Phase 0       → 验证接口字段可用性
2. a_stock.py    → 实现数据获取逻辑
3. interface.py  → 注册到 VENDOR_METHODS
4. signal_data_tools.py → 添加 @tool 包装
5. agent_utils.py    → 导出工具
6. short_term_analyst.py → 🆕 接入新工具
7. agent_states.py  → 🆕 新增 short_term_report 字段
8. tests/        → 编写单元测试
```

## 评审修正总结

本方案经过多视角（资深交易者、超龙头实战交易者、系统架构师）评审，
共发现并修正了 **24 项**问题。关键修正包括：

### 数据可行性修正（5项）
- 移除封单峰值指标（不可获取），改用封单/流通盘比
- 移除撤单次数指标（不可获取），改用封板稳定性
- 新增 Phase 0 接口验证，确保字段可用
- 补充备选数据源方案

### 实战阈值修正（6项）
- 强看好情绪阈值下调（连板溢价>5%→>3%）
- 闷杀率分级（轻度>3%/标准>5%/重度>7%）
- 流通市值阈值调整（首板50亿/200亿，龙头200亿）
- 补涨龙条件放宽（>=5板→>=4板）
- 卡位阈值修正（龙头分歧时>1.5→>1.2）

### 模型简化修正（4项）
- 分歧度模型从5因子简化为2因子（封单稳定性+开板次数）
- 龙头评分首板时间权重下调（20%→15%），仅同板数内比较
- 热度评分龙头状态权重上调（10%→25%）
- 市场情绪权重在二板评分中上调（15%→20%）

### 新增功能（5项）
- 市场涨跌家数比（AD比）
- 北向资金信号纳入情绪评分
- 涨停原因归一化处理
- 题材辨识度量化评分
- 补涨龙 vs 新龙头区分方法

### 架构优化（4项）
- 新增 `short_term_analyst` 独立 Agent
- 新增 `short_term_report` State 字段
- 新增冰点确认机制（连续2天验证）
- 新增非交易日测试用例

## 测试策略

每个功能必须包含：

1. **单元测试** - 验证数据接口正确性
2. **集成测试** - 验证 Agent 工具调用链路
3. **边界测试** - 验证异常情况处理
4. **Phase 0 验证** - 验证接口字段可用性

```bash
# Phase 0 验证（最先执行）
python -m pytest tests/test_phase0_api_verification.py -v

# 运行所有测试
python -m pytest tests/test_short_term_features.py -v

# 运行单个功能测试
python -m pytest tests/test_short_term_features.py::TestConsecutiveLimitStats -v
```

## 依赖说明

所有新接口基于现有数据源，无新增第三方依赖：

| 数据源 | 用途 | 限流 |
|--------|------|------|
| 东财 datacenter | 涨停数据、连板统计 | _em_get() 统一限流 |
| 东财 push2 | 实时行情、封单数据 | _em_get() 统一限流 |
| 东财 push2his | 分时K线（可选） | _em_get() 统一限流 |
| 同花顺 hsgtApi | 北向资金 | 无限制 |
| mootdx | K线历史数据 | TCP 直连 |

## 验收标准

每个功能完成后需满足：

- [ ] Phase 0 接口验证通过
- [ ] 单元测试通过（100%）
- [ ] 异常情况处理完善（网络超时、数据为空、非交易日）
- [ ] Agent 工具调用正常
- [ ] 文档完整（接口说明 + 使用示例 + 数据限制说明）
- [ ] 评审修正已落实

## 相关文档

- [实施计划总览](./IMPLEMENTATION_PLAN.md)
- [功能1：连板梯队统计 + 情绪量化](./01_consecutive_limit_stats.md)
- [功能2：题材热度追踪](./02_theme_heat_tracking.md)
- [功能3：首板筛选 + 二板预期](./03_first_board_screen.md)
- [功能4：高标股状态监控](./04_high_board_status.md)
- [功能5：龙头识别 + 卡位分析](./05_leader_identification.md)
