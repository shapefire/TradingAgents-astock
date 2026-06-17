# 短线交易能力扩展 - 实施步骤任务清单

> **状态说明**: ⬜ 未开始 | 🔄 进行中 | ✅ 已完成 | ❌ 失败

---

## Phase 0: 接口验证（✅ 已完成）

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P0-01 | 验证东财 RPT_LIMITUP_STOCK 接口 | ✅ | 无 | 接口已失效 |
| P0-02 | 验证东财选股接口 (dataapi/xuangu/list) | ✅ | 无 | 接口可用，字段: SECURITY_CODE, CHANGE_RATE, FREE_CAP 等 |
| P0-03 | 验证同花顺 getharden 接口 | ✅ | 无 | 接口可用，返回 code, name, reason, date |
| P0-04 | 验证 mootdx K线接口 | ✅ | 无 | 接口可用，可判断涨停和计算连板天数 |
| P0-05 | 生成 Phase 0 验证报告 | ✅ | P0-01~04 | docs/feat/PHASE0_VERIFICATION_REPORT.md |

---

## Phase 1: 数据基础设施（P0）

### 1.1 涨停数据获取层

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P1-01 | 实现 `_get_limitup_stocks_ths()` 同花顺涨停获取 | ✅ | P0-03 | a_stock.py: 返回涨停股列表+涨停原因 |
| P1-02 | 实现 `_detect_limitup_from_kline()` mootdx涨停判断 | ✅ | P0-04 | a_stock.py: 判断个股是否涨停 |
| P1-03 | 实现 `_calculate_consecutive_days()` 连板天数计算 | ✅ | P1-02 | a_stock.py: 计算连板天数 |
| P1-04 | 实现 `_get_limitup_stocks()` 统一涨停获取接口 | ✅ | P1-01, P1-03 | a_stock.py: 整合同花顺+mootdx数据 |
| P1-05 | 实现 `_get_limitdown_stocks()` 跌停获取 | ✅ | P0-02 | a_stock.py: 获取跌停股列表 |

### 1.2 行情数据获取层

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P1-06 | 实现 `_get_stock_realtime_quote()` 个股行情获取 | ✅ | P0-02 | a_stock.py: 获取个股实时行情 |
| P1-07 | 实现 `_get_market_breadth()` 市场涨跌家数 | ✅ | P0-02 | a_stock.py: 获取涨跌家数比 |
| P1-08 | 实现 `_get_northbound_flow_signal()` 北向资金信号 | ✅ | 无 | a_stock.py: 复用现有 get_northbound_flow |

### 1.3 涨停原因归一化

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P1-09 | 定义 `REASON_NORMALIZATION_MAP` 归一化映射表 | ✅ | P1-01 | a_stock.py: 初始映射表 |
| P1-10 | 实现 `_normalize_theme_name()` 涨停原因归一化 | ✅ | P1-09 | a_stock.py: 归一化函数 |
| P1-11 | 实现 `_auto_expand_normalization_map()` 自动扩展映射 | ⬜ | P1-10 | a_stock.py: 可选，后续优化 |

---

## Phase 2: 功能1 - 连板梯队统计 + 情绪量化（P0）

### 2.1 数据获取函数

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P2-01 | 实现 `_get_yesterday_limitup_performance()` 昨日涨停今日表现 | ✅ | P1-04, P1-06 | a_stock.py |
| P2-02 | 实现 `_get_board_distribution()` 连板梯队分布统计 | ✅ | P1-04 | a_stock.py |

### 2.2 指标计算函数

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P2-03 | 实现 `_calculate_seal_quality()` 封板质量评估 | ✅ | P1-04 | a_stock.py: 含一字板/换手板拆分 |
| P2-04 | 实现 `_calculate_yesterday_performance()` 昨日涨停表现计算 | ✅ | P2-01 | a_stock.py: 含闷杀率分级 |
| P2-05 | 实现 `_calculate_board_health()` 梯队健康度评分 | ✅ | P2-02 | a_stock.py |
| P2-06 | 实现 `_judge_emotion_phase()` 情绪周期判断 | ✅ | P2-03~05, P1-07, P1-08 | a_stock.py: 含冰点确认机制 |
| P2-07 | 实现 `_calculate_emotion_metrics()` 情绪指标汇总 | ✅ | P2-01~06 | a_stock.py |

### 2.3 对外接口

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P2-08 | 实现 `get_consecutive_limit_stats()` 主接口 | ✅ | P2-07 | a_stock.py: 返回完整报告 |

---

## Phase 3: 功能2 - 题材热度追踪（P0）

### 3.1 数据获取函数

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P3-01 | 实现 `_get_limitup_by_theme()` 涨停按题材聚合 | ✅ | P1-04, P1-10 | a_stock.py |
| P3-02 | 实现 `_get_theme_history()` 题材历史热度 | ✅ | P1-04 | a_stock.py: 近N日涨停数据 |
| P3-03 | 实现 `_get_theme_leader_status()` 题材龙头状态 | ✅ | P1-04 | a_stock.py |

### 3.2 指标计算函数

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P3-04 | 实现 `_get_theme_active_days()` 活跃天数计算 | ✅ | P3-02 | a_stock.py |
| P3-05 | 实现 `_get_theme_phase()` 题材阶段判断 | ✅ | P3-02, P3-03 | a_stock.py |
| P3-06 | 实现 `_calculate_theme_trend()` 题材趋势判断 | ✅ | P3-02, P3-03 | a_stock.py |
| P3-07 | 实现 `_calculate_theme_recognition_score()` 辨识度评分 | ✅ | P3-01, P3-03 | a_stock.py: 五维度评分 |
| P3-08 | 实现 `_calculate_heat_score()` 热度评分 | ✅ | P3-01~07 | a_stock.py: 权重已调整 |

### 3.3 对外接口

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P3-09 | 实现 `get_theme_heat()` 主接口 | ✅ | P3-01~08 | a_stock.py: 返回题材热度报告 |

---

## Phase 4: 功能3 - 首板筛选 + 二板预期（P1）

### 4.1 数据获取函数

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P4-01 | 实现 `_get_first_board_stocks()` 首板股票获取 | ✅ | P1-04 | a_stock.py: 筛选连板天数=1 |
| P4-02 | 实现 `_get_stock_seal_info()` 封单信息获取 | ✅ | P1-06 | a_stock.py: 含封单/流通盘比 |
| P4-03 | 实现 `_get_historical_activity()` 历史股性评分 | ✅ | P1-04 | a_stock.py |

### 4.2 指标计算函数

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P4-04 | 实现 `_calculate_theme_purity()` 题材纯正度评分 | ✅ | P1-04, P3-01 | a_stock.py: 四维度评分 |
| P4-05 | 实现 `_calculate_volume_match_score()` 量价配合评分 | ✅ | P1-06 | a_stock.py |
| P4-06 | 实现 `calculate_second_board_score()` 二板预期评分 | ✅ | P4-01~05 | a_stock.py: 七因子模型 |

### 4.3 对外接口

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P4-07 | 实现 `get_first_board_screen()` 主接口 | ✅ | P4-01~06 | a_stock.py: 返回首板筛选报告 |

---

## Phase 5: 功能4 - 高标股状态监控（P1）

### 5.1 数据获取函数

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P5-01 | 实现 `_get_high_board_stocks()` 最高板股票获取 | ✅ | P1-04 | a_stock.py |
| P5-02 | 实现 `_get_high_board_detail()` 高标股详情 | ✅ | P1-06 | a_stock.py: 含封单状态 |
| P5-03 | 实现 `_get_yizi_cumulative_turnover()` 一字板累计换手率 | ✅ | P1-02 | a_stock.py |

### 5.2 指标计算函数

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P5-04 | 实现 `_calculate_divergence_score()` 分歧度评估（简化2因子） | ✅ | P5-02 | a_stock.py |
| P5-05 | 实现 `_calculate_break_risk_level()` 断板风险评估 | ✅ | P5-01~04 | a_stock.py: 含一字板风险细化 |
| P5-06 | 实现 `_get_theme_effect_for_high_board()` 板块效应 | ✅ | P5-01, P1-04 | a_stock.py |

### 5.3 对外接口

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P5-07 | 实现 `get_high_board_status()` 主接口 | ✅ | P5-01~06 | a_stock.py: 返回高标状态报告 |

---

## Phase 6: 功能5 - 龙头识别 + 卡位分析（P2）

### 6.1 数据获取函数

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P6-01 | 实现 `_get_same_theme_stocks()` 同题材股票获取 | ✅ | P1-04, P1-10 | a_stock.py |
| P6-02 | 实现 `_get_leader_candidates()` 龙头候选获取 | ✅ | P1-04 | a_stock.py |

### 6.2 指标计算函数

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P6-03 | 实现 `_calculate_leader_score()` 龙头评分 | ✅ | P6-01, P6-02 | a_stock.py: 权重已调整 |
| P6-04 | 实现 `_calculate_time_score()` 涨停时间评分 | ✅ | 无 | a_stock.py |
| P6-05 | 实现 `_identify_card_position()` 卡位识别 | ✅ | P6-01, P6-02 | a_stock.py: 含阈值动态调整 |
| P6-06 | 实现 `_identify_deputy_leader()` 补涨龙识别 | ✅ | P6-01, P6-02 | a_stock.py: 条件已放宽 |
| P6-07 | 实现 `_distinguish_deputy_vs_new_leader()` 补涨龙vs新龙头区分 | ✅ | P6-06 | a_stock.py |

### 6.3 对外接口

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P6-08 | 实现 `get_leader_identification()` 主接口 | ✅ | P6-01~07 | a_stock.py: 返回龙头识别报告 |

---

## Phase 7: 工具注册与 Agent 集成

### 7.1 工具注册

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P7-01 | 在 signal_data_tools.py 添加 `get_consecutive_limit_stats` 工具 | ✅ | P2-08 | signal_data_tools.py |
| P7-02 | 在 signal_data_tools.py 添加 `get_theme_heat` 工具 | ✅ | P3-09 | signal_data_tools.py |
| P7-03 | 在 signal_data_tools.py 添加 `get_first_board_screen` 工具 | ✅ | P4-07 | signal_data_tools.py |
| P7-04 | 在 signal_data_tools.py 添加 `get_high_board_status` 工具 | ✅ | P5-07 | signal_data_tools.py |
| P7-05 | 在 signal_data_tools.py 添加 `get_leader_identification` 工具 | ✅ | P6-08 | signal_data_tools.py |
| P7-06 | 在 interface.py 注册所有新接口到 VENDOR_METHODS | ✅ | P7-01~05 | interface.py |

### 7.2 Agent 创建

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P7-07 | 创建 `short_term_analyst.py` 短线博弈分析师 Agent | ✅ | P7-06 | agents/analysts/short_term_analyst.py |
| P7-08 | 在 agent_states.py 新增 `short_term_report` 字段 | ✅ | P7-07 | agent_states.py |
| P7-09 | 更新 prefetch 层支持新工具 | ✅ | P7-06 | prefetch 相关文件 |

---

## Phase 8: 单元测试

### 8.1 Phase 0 验证测试

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P8-01 | 创建 test_phase0_api_verification.py | ✅ | P0-01~05 | tests/test_phase0_api_verification.py |

### 8.2 功能1测试

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P8-02 | TestConsecutiveLimitStats - 测试涨停获取 | ✅ | P1-04 | tests/test_short_term_features.py |
| P8-03 | TestConsecutiveLimitStats - 测试情绪指标计算 | ✅ | P2-07 | tests/test_short_term_features.py |
| P8-04 | TestConsecutiveLimitStats - 测试情绪周期判断 | ✅ | P2-06 | tests/test_short_term_features.py |
| P8-05 | TestConsecutiveLimitStats - 测试冰点确认机制 | ✅ | P2-06 | tests/test_short_term_features.py |
| P8-06 | TestConsecutiveLimitStats - 测试市场涨跌家数 | ✅ | P1-07 | tests/test_short_term_features.py |
| P8-07 | TestConsecutiveLimitStats - 测试北向资金信号 | ✅ | P1-08 | tests/test_short_term_features.py |
| P8-08 | TestConsecutiveLimitStats - 测试主接口返回 | ✅ | P2-08 | tests/test_short_term_features.py |

### 8.3 功能2测试

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P8-09 | TestThemeHeatTracking - 测试涨停原因归一化 | ✅ | P1-10 | tests/test_short_term_features.py |
| P8-10 | TestThemeHeatTracking - 测试题材聚合 | ✅ | P3-01 | tests/test_short_term_features.py |
| P8-11 | TestThemeHeatTracking - 测试活跃天数计算 | ✅ | P3-04 | tests/test_short_term_features.py |
| P8-12 | TestThemeHeatTracking - 测试辨识度评分 | ✅ | P3-07 | tests/test_short_term_features.py |
| P8-13 | TestThemeHeatTracking - 测试热度评分权重 | ✅ | P3-08 | tests/test_short_term_features.py |
| P8-14 | TestThemeHeatTracking - 测试主接口返回 | ✅ | P3-09 | tests/test_short_term_features.py |

### 8.4 功能3测试

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P8-15 | TestFirstBoardScreen - 测试首板筛选 | ✅ | P4-01 | tests/test_short_term_features.py |
| P8-16 | TestFirstBoardScreen - 测试题材纯正度 | ✅ | P4-04 | tests/test_short_term_features.py |
| P8-17 | TestFirstBoardScreen - 测试二板预期评分 | ✅ | P4-06 | tests/test_short_term_features.py |
| P8-18 | TestFirstBoardScreen - 测试流通市值阈值 | ✅ | P4-06 | tests/test_short_term_features.py |
| P8-19 | TestFirstBoardScreen - 测试主接口返回 | ✅ | P4-07 | tests/test_short_term_features.py |

### 8.5 功能4测试

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P8-20 | TestHighBoardStatus - 测试最高板获取 | ✅ | P5-01 | tests/test_short_term_features.py |
| P8-21 | TestHighBoardStatus - 测试分歧度评估 | ✅ | P5-04 | tests/test_short_term_features.py |
| P8-22 | TestHighBoardStatus - 测试断板风险评估 | ✅ | P5-05 | tests/test_short_term_features.py |
| P8-23 | TestHighBoardStatus - 测试板块效应 | ✅ | P5-06 | tests/test_short_term_features.py |
| P8-24 | TestHighBoardStatus - 测试主接口返回 | ✅ | P5-07 | tests/test_short_term_features.py |

### 8.6 功能5测试

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P8-25 | TestLeaderIdentification - 测试同题材获取 | ✅ | P6-01 | tests/test_short_term_features.py |
| P8-26 | TestLeaderIdentification - 测试龙头评分 | ✅ | P6-03 | tests/test_short_term_features.py |
| P8-27 | TestLeaderIdentification - 测试卡位识别 | ✅ | P6-05 | tests/test_short_term_features.py |
| P8-28 | TestLeaderIdentification - 测试补涨龙识别 | ✅ | P6-06 | tests/test_short_term_features.py |
| P8-29 | TestLeaderIdentification - 测试补涨龙vs新龙头区分 | ✅ | P6-07 | tests/test_short_term_features.py |
| P8-30 | TestLeaderIdentification - 测试主接口返回 | ✅ | P6-08 | tests/test_short_term_features.py |

### 8.7 集成测试

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P8-31 | 创建 test_short_term_integration.py | ✅ | P7-06 | tests/test_short_term_integration.py |
| P8-32 | TestAgentToolIntegration - 测试 Agent 工具调用 | ✅ | P8-31 | tests/test_short_term_integration.py |

---

## Phase 9: 文档更新

| 任务ID | 任务 | 状态 | 依赖 | 输出 |
|--------|------|------|------|------|
| P9-01 | 更新 README.md 添加新功能说明 | ⬜ | P7-06 | README.md |
| P9-02 | 更新 CLAUDE.md 添加新接口说明 | ✅ | P7-06 | CLAUDE.md |
| P9-03 | 创建接口使用文档 | ⬜ | P7-06 | docs/api/ |

---

## 执行顺序建议

### 第一阶段：数据基础（必须先完成）
```
P1-01 → P1-02 → P1-03 → P1-04 → P1-05
                  ↓
P1-09 → P1-10
```

### 第二阶段：核心功能（可并行）
```
P2-01~P2-08 (功能1)
P3-01~P3-09 (功能2)
P4-01~P4-07 (功能3)
P5-01~P5-07 (功能4)
P6-01~P6-08 (功能5)
```

### 第三阶段：集成与测试
```
P7-01~P7-09 (工具注册)
P8-01~P8-32 (单元测试)
P9-01~P9-03 (文档更新)
```

---

## 验收检查清单

### Phase 0 验收
- [x] 东财 RPT_LIMITUP_STOCK 接口验证完成（已失效）
- [x] 替代方案确认：同花顺 getharden + mootdx K线
- [x] 接口字段映射表文档化

### Phase 1 验收
- [x] `_get_limitup_stocks()` 返回涨停股票列表
- [x] `_get_limitdown_stocks()` 返回跌停股票列表
- [x] `_get_market_breadth()` 返回市场涨跌家数比
- [x] `_get_northbound_flow_signal()` 返回北向资金信号
- [x] `_normalize_theme_name()` 正确归一化涨停原因

### Phase 2 验收
- [x] `_calculate_emotion_metrics()` 正确计算情绪指标
- [x] 情绪周期判断准确（含冰点确认机制）
- [x] `get_consecutive_limit_stats()` 返回完整报告

### Phase 3 验收
- [x] `_calculate_heat_score()` 热度评分权重正确
- [x] `_calculate_theme_recognition_score()` 辨识度评分合理
- [x] `get_theme_heat()` 返回完整报告

### Phase 4 验收
- [x] `calculate_second_board_score()` 综合评分正确
- [x] 流通市值阈值已调整（50亿/200亿）
- [x] `get_first_board_screen()` 返回完整报告

### Phase 5 验收
- [x] `_calculate_divergence_score()` 简化版评分合理
- [x] `_calculate_break_risk_level()` 风险等级准确
- [x] `get_high_board_status()` 返回完整报告

### Phase 6 验收
- [x] `_identify_card_position()` 卡位识别准确
- [x] `_identify_deputy_leader()` 补涨龙识别准确
- [x] `get_leader_identification()` 返回完整报告

### Phase 7 验收
- [x] 所有工具注册完成
- [x] short_term_analyst Agent 创建完成
- [x] AgentState 新增 short_term_report 字段

### Phase 8 验收
- [x] test_phase0_api_verification.py 创建完成（7 个测试类）
- [x] test_short_term_integration.py 创建完成（22 个测试，全部通过）
- [ ] 单元测试覆盖率 >= 80%
- [ ] 所有测试通过

### Phase 9 验收
- [ ] README.md 更新完成
- [ ] CLAUDE.md 更新完成
- [ ] 接口使用文档完成

---

## 风险与备选方案

| 风险 | 影响 | 备选方案 |
|------|------|----------|
| 同花顺 getharden 接口变更 | 无法获取涨停原因 | 使用东财选股接口筛选涨停股，原因字段留空 |
| mootdx 连接不稳定 | 无法判断涨停 | 使用东财选股接口的 CHANGE_RATE>=9.9% 筛选 |
| 涨停原因归一化不准 | 题材聚合偏差 | 手工维护映射表，定期更新 |
| 分时数据不可获取 | 封单稳定性无法计算 | 简化为封板状态二元判断 |
| 非交易日查询 | 返回空数据 | 测试用例覆盖，返回友好提示 |

---

## 最后更新

- 创建时间: 2026-06-15
- 最后更新: 2026-06-17
- 当前进度: Phase 0 ~ Phase 8 (集成测试) + Phase 9 (CLAUDE.md) 已完成，剩余 P9-01 README + P9-03 API 文档
