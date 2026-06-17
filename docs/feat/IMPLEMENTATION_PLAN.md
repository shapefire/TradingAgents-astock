# 短线交易能力扩展 - 实施计划总览

> **📋 详细任务清单**: [IMPLEMENTATION_TASKS.md](./IMPLEMENTATION_TASKS.md)
> 包含每个具体实施步骤的任务ID、状态、依赖关系和输出文件。

## 一、项目概览

### 1.1 目标

补齐现有 A 股接口在**短线/超短线交易决策支撑**层面的能力缺口，从"信息获取"升级到"决策支撑"。

### 1.2 功能清单

| 序号 | 功能 | 优先级 | 文档 | 预估工时 | 评审修正 |
|------|------|--------|------|----------|----------|
| 0 | 接口验证（Phase 0） | P0 | 本文档 §2.2 | 1-2天 | ✅ 新增 |
| 1 | 连板梯队统计 + 情绪量化 | P0 | [01_consecutive_limit_stats.md](./01_consecutive_limit_stats.md) | 3-5天 | 6项修正 |
| 2 | 题材热度追踪 | P0 | [02_theme_heat_tracking.md](./02_theme_heat_tracking.md) | 3-5天 | 4项修正 |
| 3 | 首板筛选 + 二板预期 | P1 | [03_first_board_screen.md](./03_first_board_screen.md) | 3-5天 | 5项修正 |
| 4 | 高标股状态监控 | P1 | [04_high_board_status.md](./04_high_board_status.md) | 2-3天 | 4项修正 |
| 5 | 龙头识别 + 卡位分析 | P2 | [05_leader_identification.md](./05_leader_identification.md) | 5-7天 | 5项修正 |

**总计预估工时：17-27天**（含 Phase 0 验证 1-2天）

---

## 二、分层实施策略

### 2.1 三层架构

```
┌─────────────────────────────────────────────────────────┐
│                    决策层（Agent）                        │
│   short_term_analyst（短线博弈分析师）🆕                   │
├─────────────────────────────────────────────────────────┤
│                    信号层（Tools）                        │
│   连板梯队 / 题材热度 / 首板筛选 / 高标状态 / 龙头识别   │
├─────────────────────────────────────────────────────────┤
│                    数据层（Vendor）                       │
│   东财 datacenter / push2 / mootdx / 同花顺 hsgtApi     │
└─────────────────────────────────────────────────────────┘
```

### 2.2 实施顺序（含 Phase 0）

```
Phase 0：接口验证（⚠️ 必须先完成）
  Step 0a: 实测东财 RPT_LIMITUP_STOCK 接口字段结构
  Step 0b: 验证涨停原因字段质量 + 构建归一化映射表
  Step 0c: 验证封单/撤单数据可用性
  输出：接口字段映射表 + 数据源可用性报告

Phase 1：情绪量化基础（P0）
  Step 1: 连板梯队统计（含市场涨跌家数比、北向资金信号）
  Step 2: 题材热度追踪（含涨停原因归一化、辨识度评分）

Phase 2：选股筛选能力（P1）
  Step 3: 首板筛选 + 二板预期（简化版，移除不可获取指标）
  Step 4: 高标股状态监控（简化版，2因子分歧度模型）

Phase 3：博弈分析能力（P2）
  Step 5: 龙头识别 + 卡位分析（含补涨龙vs新龙头区分）

Phase 4：Agent 集成
  Step 6: 创建 short_term_analyst Agent
  Step 7: 接入 AgentState（新增 short_term_report 字段）
  Step 8: 更新 prefetch 层
  Step 9: 集成测试
```

---

## 三、Phase 0 接口验证（⚠️ 新增，必须先完成）

> **背景**：评审发现多份文档假设的接口字段未经实测验证。如果关键字段不可用，
> 后续实现会遇到阻塞。Phase 0 的目的是在写代码前确认数据可用性。

### 3.1 验证清单

| 接口 | 验证内容 | 验证方法 | 输出 |
|------|----------|----------|------|
| RPT_LIMITUP_STOCK | 字段名 + 数据质量 | 实际请求 + 字段映射 | 字段映射表 |
| 涨停原因字段 | 归因精度 + 多值问题 | 采样分析 | 归一化映射表 |
| 封单金额/峰值 | 是否可获取 | 实际请求 | 可用性报告 |
| 撤单次数 | 是否可获取 | 实际请求 | 可用性报告 |
| 分时K线封单 | 是否有封单数据 | 实际请求 | 可用性报告 |
| 市场涨跌家数 | 接口地址 + 字段 | 实际请求 | 接口文档 |

### 3.2 验证脚本模板

```python
# tests/test_phase0_api_verification.py

import pytest
from tradingagents.dataflows.a_stock import _em_get

class TestPhase0ApiVerification:
    """Phase 0 接口验证测试"""

    def test_limitup_stock_fields(self):
        """验证 RPT_LIMITUP_STOCK 接口字段"""
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_LIMITUP_STOCK",
            "columns": "ALL",
            "filter": "(TRADE_DATE='2026-06-13')",
            "pageSize": 10,
        }
        resp = _em_get(url, params=params)
        # 记录返回的字段列表
        # 验证关键字段是否存在
        assert resp is not None

    def test_limitup_reason_quality(self):
        """验证涨停原因字段质量"""
        # 采样分析涨停原因
        # 统计不同原因的数量
        # 识别需要归一化的相似原因
        pass

    def test_seal_amount_availability(self):
        """验证封单金额数据可用性"""
        # 检查 push2 接口是否返回封单数据
        pass

    def test_market_breadth_api(self):
        """验证市场涨跌家数接口"""
        # 寻找可用的涨跌家数接口
        pass
```

### 3.3 验证失败的备选方案

| 验证项 | 如果失败 | 备选方案 |
|--------|----------|----------|
| RPT_LIMITUP_STOCK 字段缺失 | 用 mootdx K线自己判断涨停 | `_detect_limitup_from_kline()` |
| 涨停原因质量差 | 用同花顺 `get_hot_stocks()` 的原因标签 | 复用现有接口 |
| 封单峰值不可获取 | 改用当前封单/流通盘比 | 已在文档中说明 |
| 撤单次数不可获取 | 移除，用封单稳定性替代 | 已在文档中说明 |
| 市场涨跌家数无接口 | 从 push2 全市场行情统计计算 | 新增聚合函数 |

---

## 四、测试策略

### 4.1 测试分层

| 测试类型 | 目标覆盖率 | 说明 |
|----------|------------|------|
| 单元测试 | 100% | 每个函数、每个分支 |
| 集成测试 | 80% | Agent 工具调用链路 |
| 边界测试 | 100% | 异常情况处理 |
| Phase 0 验证 | 100% | 接口字段可用性 |

### 4.2 测试文件结构

```
tests/
├── test_phase0_api_verification.py   # 🆕 Phase 0 接口验证
├── test_short_term_features.py       # 主测试文件
│   ├── TestConsecutiveLimitStats     # 连板梯队统计
│   ├── TestThemeHeatTracking         # 题材热度追踪
│   ├── TestFirstBoardScreen          # 首板筛选
│   ├── TestHighBoardStatus           # 高标股状态
│   └── TestLeaderIdentification      # 龙头识别
└── test_short_term_integration.py    # 集成测试
    └── TestAgentToolIntegration      # Agent 工具调用
```

### 4.3 测试执行

```bash
# Phase 0 验证（最先执行）
python -m pytest tests/test_phase0_api_verification.py -v

# 运行所有短线功能测试
python -m pytest tests/test_short_term_features.py -v

# 运行单个功能测试
python -m pytest tests/test_short_term_features.py::TestConsecutiveLimitStats -v

# 运行集成测试
python -m pytest tests/test_short_term_integration.py -v

# 生成覆盖率报告
python -m pytest tests/test_short_term_features.py --cov=tradingagents/dataflows/a_stock --cov-report=html
```

### 4.4 测试用例设计原则

每个功能必须包含以下测试用例：

1. **正常流程测试** - 验证核心功能
2. **边界条件测试** - 空数据、异常数据
3. **异常处理测试** - 网络超时、接口错误
4. **参数验证测试** - 无效参数处理
5. **非交易日测试** - ⚠️ 新增：周末/节假日查询

---

## 五、代码结构规范

### 5.1 新增文件清单

```
tradingagents/
├── dataflows/
│   └── a_stock.py                    # 新增数据接口（约+600行）
├── agents/
│   ├── utils/
│   │   ├── signal_data_tools.py      # 新增 @tool 包装（约+200行）
│   │   └── agent_utils.py            # 导出新工具（约+10行）
│   └── analysts/
│       ├── short_term_analyst.py     # 🆕 短线博弈分析师（约+200行）
│       ├── market_analyst.py         # 不变
│       └── hot_money_tracker.py      # 不变
├── tests/
│   ├── test_phase0_api_verification.py  # 🆕 Phase 0 验证（约+100行）
│   ├── test_short_term_features.py   # 单元测试（约+500行）
│   └── test_short_term_integration.py # 集成测试（约+100行）
└── docs/
    └── feat/                         # 实施文档
```

### 5.2 代码规范

```python
# 1. 函数命名规范
def get_xxx()          # 对外接口
def _get_xxx()         # 内部数据获取
def _calculate_xxx()   # 内部指标计算

# 2. 类型注解
def get_xxx(
    ticker: Annotated[str, "A-stock code (e.g. 000001)"],
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
) -> str:

# 3. 文档字符串
def get_xxx() -> str:
    """
    功能说明

    返回内容：
    1. xxx
    2. xxx

    数据源：xxx
    限流：xxx

    数据限制说明：
    - xxx 字段不可获取，改用 xxx 替代
    """

# 4. 异常处理
try:
    # 业务逻辑
except Exception as e:
    return f"Error: {str(e)}"

# 5. 评审修正标记（新增）
# 📌 评审修正 #N：简要说明修正内容
# 原问题：xxx
# 修正：xxx
```

---

## 六、验收清单

### 6.1 Phase 0 验收（⚠️ 新增）

- [ ] 东财 RPT_LIMITUP_STOCK 接口字段验证完成
- [ ] 涨停原因归一化映射表构建完成
- [ ] 封单/撤单数据可用性确认
- [ ] 市场涨跌家数接口确认
- [ ] 接口字段映射表文档化
- [ ] 验证失败项有备选方案

### 6.2 功能验收

每个功能完成后需通过以下验收：

- [ ] 单元测试通过（100%）
- [ ] 异常情况处理完善（网络超时、数据为空、非交易日）
- [ ] Agent 工具调用正常
- [ ] 文档完整（接口说明 + 使用示例 + 数据限制说明）
- [ ] 代码审查通过

### 6.3 整体验收

- [ ] 所有 P0 功能完成
- [ ] 所有 P1 功能完成
- [ ] 所有 P2 功能完成（可选）
- [ ] short_term_analyst Agent 创建完成
- [ ] AgentState 新增 short_term_report 字段
- [ ] prefetch 层更新完成
- [ ] 集成测试通过
- [ ] 性能测试通过（单次请求 <5s）
- [ ] 文档更新完成

---

## 七、风险与依赖

### 7.1 技术风险

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| 东财接口字段变更 | 数据获取失败 | Phase 0 提前验证，准备备选数据源 |
| 涨停原因归因精度差 | 题材聚合不准 | 归一化映射表 + 人工维护 |
| 封单峰值/撤单不可获取 | 封板质量评估受限 | 已在文档中说明替代方案 |
| 限流触发 | 批量分析失败 | 优化限流策略，增加缓存 |
| 数据延迟 | 实时性不足 | 明确数据时效性说明 |
| 非交易日查询 | 返回空数据 | 测试用例覆盖边界情况 |

### 7.2 依赖说明

所有新接口基于现有数据源，**无新增第三方依赖**：

| 数据源 | 用途 | 限流 |
|--------|------|------|
| 东财 datacenter | 涨停数据、连板统计 | _em_get() 统一限流 |
| 东财 push2 | 实时行情、封单数据 | _em_get() 统一限流 |
| 东财 push2his | 分时K线（可选） | _em_get() 统一限流 |
| 同花顺 hsgtApi | 北向资金 | 无限制 |
| mootdx | K线历史数据 | TCP 直连 |

---

## 八、后续扩展方向

完成上述 5 个核心功能后，可继续扩展：

1. **盘中实时监控** - 实时情绪监控、炸板预警
2. **游资席位画像** - 游资风格分析、胜率统计
3. **量化因子计算** - 动量因子、波动率因子
4. **风险预警系统** - 退市风险、财务造假预警
5. **竞价数据分析** - 集合竞价表现（需要盘中实时采集）
6. **市场情绪指数** - 综合情绪量化指数（类 VIX）

---

## 九、评审修正汇总

### 9.1 修正统计

| 文档 | 修正数 | 关键修正 |
|------|--------|----------|
| 01 连板梯队 | 6项 | 一字板/换手板拆分、北向资金纳入、冰点确认机制 |
| 02 题材热度 | 4项 | 涨停原因归一化、活跃天数定义、龙头权重上调 |
| 03 首板筛选 | 5项 | 移除不可获取指标、题材纯正度量化、市值阈值调整 |
| 04 高标状态 | 4项 | 简化分歧度模型、一字板风险细化、板块效应获取 |
| 05 龙头识别 | 5项 | 市值扣分调整、卡位阈值修正、补涨龙条件放宽 |
| **总计** | **24项** | |

### 9.2 关键修正原则

1. **数据可行性优先**：移除不可获取的指标（封单峰值、撤单次数），用可用数据替代
2. **实战阈值调整**：将理想化的阈值下调到实战常用值
3. **简化复杂模型**：将多因子模型简化为2-3个核心因子
4. **补充量化方法**：为定性描述（辨识度、纯正度）补充具体评分逻辑
5. **新增验证维度**：北向资金、市场宽度等辅助判断指标

### 9.3 相关文档

- [功能1：连板梯队统计 + 情绪量化](./01_consecutive_limit_stats.md)
- [功能2：题材热度追踪](./02_theme_heat_tracking.md)
- [功能3：首板筛选 + 二板预期](./03_first_board_screen.md)
- [功能4：高标股状态监控](./04_high_board_status.md)
- [功能5：龙头识别 + 卡位分析](./05_leader_identification.md)
