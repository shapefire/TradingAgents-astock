# 功能1：连板梯队统计 + 情绪量化

## 1. 功能说明

### 1.1 核心价值

短线交易者的**第一决策依据**：今天市场情绪好不好？连板梯队健不健康？有没有赚钱效应？

### 1.2 解决的问题

| 现状 | 目标 |
|------|------|
| `get_hot_stocks` 只给当日涨停列表 | 给出连板梯队结构 |
| 没有情绪量化指标 | 封板率、赚钱效应、情绪周期 |
| 无法判断市场阶段 | 明确当前是冰点/高潮/分歧/一致 |

### 1.3 使用场景

```
场景1：盘前决策
  交易者查看连板梯队 → 判断今天情绪预期 → 决定仓位

场景2：盘后复盘
  交易者查看今日情绪数据 → 判断情绪拐点 → 制定明日计划

场景3：周期定位
  交易者追踪情绪变化 → 识别冰点/高潮 → 选择策略
```

---

## 2. 技术方案

### 2.0 ⚠️ 前置验证任务（Phase 0，必须先完成）

> **问题**：文档假设东财 `RPT_LIMITUP_STOCK` 接口有 `CONTINUOUS_LIMIT_NUM`（连板天数）字段，
> 但实际字段命名和可用性未经验证。如果关键字段不可用，整个方案需要调整数据源。

**验证步骤：**

```python
# 1. 实测东财涨停列表接口
import requests

# 东财 datacenter 涨停列表接口
url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
params = {
    "reportName": "RPT_LIMITUP_STOCK",
    "columns": "ALL",  # 先拿所有字段看看有什么
    "filter": f'(TRADE_DATE=\'2026-06-13\')',
    "pageSize": 50,
    "sortColumns": "CONTINUOUS_LIMIT_NUM",
    "sortTypes": -1,
}

# 通过 _em_get() 发送请求
# 记录返回的字段列表

# 2. 验证关键字段是否存在
REQUIRED_FIELDS = [
    "SECURITY_CODE",        # 股票代码
    "SECURITY_NAME_ABBR",   # 股票简称
    "CONTINUOUS_LIMIT_NUM", # 连板天数
    "LIMIT_UP_REASON",      # 涨停原因
    "FIRST_LIMIT_TIME",     # 首次涨停时间
    "LAST_LIMIT_TIME",      # 最后涨停时间
    "OPEN_TIMES",           # 开板次数
    "LIMIT_UP_TYPE",        # 涨停类型（一字/T字/换手）
    "TURNOVERRATE",         # 换手率
    "DEAL_AMOUNT",          # 成交额
    "FREE_CAP",             # 流通市值
]

# 3. 如果字段名不同，做映射表
# 4. 如果接口不可用，准备备选方案：
#    - 同花顺涨停接口
#    - 用 mootdx K线数据自己判断涨停
```

**如果验证失败的备选方案：**

```python
# 备选：通过 mootdx K线数据判断涨停
def _detect_limitup_from_kline(code: str, trade_date: str) -> dict:
    """
    从 K 线数据判断涨停状态

    逻辑：
    1. 获取当日 K 线（OHLCV）
    2. 计算涨停价 = 前收盘 * 1.1（四舍五入到分）
    3. 如果收盘价 == 涨停价 → 涨停
    4. 如果开盘价 == 涨停价 且 收盘价 == 涨停价 → 一字板
    5. 连板天数 = 往前追溯连续涨停的天数
    """
    pass
```

### 2.1 数据源分析

| 数据 | 来源 | 接口 | 说明 |
|------|------|------|------|
| 涨停股票列表 | 东财 datacenter | `RPT_LIMITUP_STOCK` | 连板天数、涨停原因、开板次数、涨停类型 |
| 跌停股票列表 | 东财 datacenter | `RPT_LIMITDOWN_STOCK` | 跌停家数统计 |
| 昨日涨停今日表现 | 东财 push2 | 个股行情 | 计算昨日涨停股今日涨幅 |
| 北向资金流向 | 同花顺 hsgtApi | `get_northbound_flow()` | 纳入情绪综合评分 |
| 市场涨跌家数 | 东财 push2 | 全市场行情统计 | AD 比（涨跌家数比） |

### 2.2 核心指标计算（实战版）

```python
# 情绪量化指标（资深交易者视角）

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #1：拆分一字板和换手板统计
# 原问题：一字板不应简单计入"早盘封板"
# 修正：一字板、换手板分开统计，含义完全不同
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 连板梯队分布
   - 最高连板数（高度标）
   - 各板数股票数量（N板：X只）
   - 梯队健康度评分
   - 梯队结构：5-4-3-2-1 完整梯队 vs 断层梯队

2. 封板质量指标（精细化，拆分一字/换手）
   - 一字板数量 / 换手板数量
     * 一字板：开盘即封死，筹码锁定好，但换手不充分，开板风险高
     * 换手板：盘中封板，经过充分换手，质量更稳定
   - 有效封板率 = (换手板中早盘封板数(10:30前)) / 换手板总数
     * 排除一字板（一字板的封板率没有参考意义）
     * 尾盘偷袭板(14:50后)质量差，不应计入
   - 封板成功率 = (涨停数 - 回封数) / (涨停数 + 炸板数)
     * 回封的票质量低，应该扣除
   - 炸板回封率 = 回封数 / 炸板数
     * 回封率高说明市场承接力强
   - 封单强度中位数 = 所有换手涨停股封单/流通盘比的中位数
     * 比平均值更能反映真实情况

3. 赚钱效应指标（精细化）
   - 连板股溢价率 = 昨日连板股今日平均涨幅
     * 这是情绪的核心指标
   - 首板股溢价率 = 昨日首板股今日平均涨幅
     * 反映首板战法的赚钱效应
   - 高开率 = 高开个股数 / 昨日涨停总数
     * 高开=市场认可，低开=市场不认可
   - 收盘涨幅中位数 = 所有昨日涨停股今日涨幅的中位数
     * 比平均值更能反映真实情况

   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #4：调整闷杀率阈值
   # 原问题：>5%跌幅算闷杀偏保守，A股日内振幅经常8-10%
   # 修正：分级闷杀率
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   - 轻度闷杀率 = 今日跌幅>3%的个股数 / 昨日涨停总数
     * 吃面但没大亏，市场还有承接
   - 重度闷杀率 = 今日跌幅>7%的个股数 / 昨日涨停总数
     * 大幅亏钱，亏钱效应强
   - 闷杀率 = 今日跌幅>5%的个股数 / 昨日涨停总数
     * 综合闷杀指标

4. 晋级率指标
   - 昨日2板→今日3板的比例
   - 昨日3板→今日4板的比例
   - 晋级率高=情绪好，晋级率低=情绪差

5. 涨停封单集中度
   - 封单金额前10名占总封单的比例
   - 集中度高=资金聚焦，分散=资金分散

6. 市场宽度指标（新增）
   - 涨跌家数比 = 上涨家数 / 下跌家数
     * >3:1 → 强势
     * 1:1 ~ 3:1 → 正常
     * <1:1 → 弱势
   - 涨停家数（绝对值）
   - 跌停家数（绝对值）
   - 涨停家数/跌停家数比

   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #3：纳入北向资金
   # 原问题：短线情绪和北向资金高度相关，尤其在转折点
   # 修正：将北向资金纳入情绪综合评分
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
7. 北向资金信号（新增）
   - 当日北向净流入（亿元）
   - 北向资金方向：大幅流入(>30亿) / 小幅流入(0-30亿) / 小幅流出(-30-0亿) / 大幅流出(<-30亿)
   - 北向资金对情绪的影响：
     * 大幅流入 + 高标封板 → 确认强势
     * 大幅流出 + 高标分歧 → 确认退潮

8. 情绪周期判断（实战版）
   - 核心逻辑：
     * 高标股状态是第一判断依据
       高标封板 → 强势
       高标断板 → 情绪拐点
     * 连板梯队健康度
       梯队完整（5-4-3-2-1）→ 健康
       只有高位没有低位 → 不健康
     * 赚钱效应 + 亏钱效应
       昨日涨停今日平均涨幅 >3% → 赚钱
       昨日涨停今日重度闷杀率 >20% → 亏钱
     * 北向资金方向（新增验证维度）

   - 周期划分：
     冰点：高标断板 + 连板梯队崩塌 + 重度闷杀率>30%
     修复：高标断板后有新龙接力 + 闷杀率下降
     升温：连板梯队恢复 + 赚钱效应回升
     高潮：高标持续封板 + 连板梯队完整 + 赚钱效应强
     退潮：高标开始分歧 + 低位晋级率下降
     分歧：高标炸板但有回封 + 赚钱效应分化

   - 注意：A股情绪周期是非对称的
     高潮到冰点很快（1-2天）
     冰点到高潮很慢（3-5天）

   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #6：增加冰点确认机制
   # 原问题：冰点不是一天就能确认的，需要连续验证
   # 修正：增加冰点确认窗口
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   - 冰点确认机制（新增）：
     * 单日冰点信号：高标断板 + 梯队崩塌 + 闷杀率>30%
     * 确认冰点（需要连续2天满足以下任意2条）：
       - 高标断板或降级
       - 闷杀率>25%
       - 晋级率<20%
       - 北向资金连续流出
     * 确认冰点后 → 等待新题材/新龙出现

9. 超龙头视角简化（核心改进）
   - 超龙头选手不预测周期，只跟随高标
   - 只判断3件事：
     1. 高标还在不在？
     2. 高标还在封板吗？
     3. 有没有新高标接力？
   - 不需要复杂的周期划分

10. 高标闷杀率（精细化）
    - 高标闷杀率 = 昨日连板>=3的股票今日跌幅>5%的比例
      * 这才是情绪崩塌的核心指标
    - 首板闷杀率 = 昨日首板今日跌幅>5%的比例
      * 这个指标参考价值不大
    - 高标炸板率 = 昨日连板>=3的股票今日炸板的比例
      * 比闷杀率更敏感
```

### 2.3 接口设计

```python
def get_consecutive_limit_stats(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
) -> str:
    """
    连板梯队统计 + 情绪量化

    返回内容：
    1. 连板梯队分布（高度标、各板数股票数量）
    2. 赚钱效应指标（昨日涨停今日表现）
    3. 封板强度指标（成功率、炸板数，拆分一字板/换手板）
    4. 情绪周期判断（冰点/低迷/修复/升温/高潮/退潮）
    5. 梯队健康度评分
    6. 市场宽度（涨跌家数比）
    7. 北向资金信号

    数据源：东财 datacenter RPT_LIMITUP_STOCK + push2 + 同花顺 hsgtApi
    限流：统一走 _em_get()
    """
```

---

## 3. 实现步骤

### Step 0：接口验证（Phase 0，必须先完成）

```python
# 验证东财涨停列表接口字段
def _verify_limitup_api_fields() -> dict:
    """
    验证 RPT_LIMITUP_STOCK 接口的可用字段

    返回：
    {
        "available": True/False,
        "fields": ["SECURITY_CODE", ...],  # 可用字段列表
        "field_mapping": {...},             # 字段名映射（如果需要）
    }
    """
    pass
```

### Step 1：数据获取层（a_stock.py）

```python
def _get_limitup_stocks(trade_date: str) -> list[dict]:
    """
    获取当日涨停股票列表（含连板天数）

    返回：
    [
        {
            "code": "000001",
            "name": "股票A",
            "continuous_limit_num": 3,  # 连板天数
            "limit_type": "换手",       # 一字/T字/换手
            "first_limit_time": "09:35", # 首次涨停时间
            "open_times": 1,            # 开板次数
            "seal_amount": 50000000,    # 封单金额
            "circulation_mv": 5000000000,  # 流通市值
            "turnover_rate": 0.08,      # 换手率
            "amount": 200000000,        # 成交额
        },
    ]

    数据源：东财 datacenter RPT_LIMITUP_STOCK
    限流：_em_get()
    """
    pass

def _get_limitdown_stocks(trade_date: str) -> list[dict]:
    """
    获取当日跌停股票列表

    数据源：东财 datacenter RPT_LIMITDOWN_STOCK
    """
    pass

def _get_yesterday_limitup_performance(trade_date: str) -> dict:
    """
    获取昨日涨停股票今日表现

    返回：
    {
        "stocks": [
            {
                "code": "000001",
                "name": "股票A",
                "yesterday_board_num": 3,   # 昨日连板数
                "today_return": 5.2,        # 今日涨幅
                "today_board_num": 4,       # 今日连板数（0=未涨停）
                "is_muffled": False,        # 是否闷杀
                "is_heavy_muffled": False,  # 是否重度闷杀
            },
        ],
        "avg_return": float,            # 整体平均涨幅
        "continuous_premium": float,    # 连板股溢价率
        "first_board_premium": float,   # 首板股溢价率
        "high_open_rate": float,        # 高开率
        "median_return": float,         # 收盘涨幅中位数
        "muffled_rate": float,          # 闷杀率（>5%）
        "light_muffled_rate": float,    # 轻度闷杀率（>3%）
        "heavy_muffled_rate": float,    # 重度闷杀率（>7%）
        "promotion_rates": dict,        # 各板数晋级率
    }
    """
    # 1. 获取昨日涨停列表
    # 2. 批量获取今日行情（通过 _tencent_quote）
    # 3. 计算各项指标
    pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #3：新增北向资金获取
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _get_northbound_emotion_signal(trade_date: str) -> dict:
    """
    获取北向资金情绪信号

    返回：
    {
        "net_inflow": float,           # 净流入（亿元）
        "direction": str,              # 大幅流入/小幅流入/小幅流出/大幅流出
        "is_confirming_strength": bool, # 是否确认强势
        "is_confirming_weakness": bool, # 是否确认弱势
    }

    数据源：同花顺 hsgtApi（已有 get_northbound_flow）
    """
    # 复用现有 get_northbound_flow() 接口
    pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #6：新增市场涨跌家数获取
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _get_market_breadth(trade_date: str) -> dict:
    """
    获取市场涨跌家数比

    返回：
    {
        "up_count": int,        # 上涨家数
        "down_count": int,      # 下跌家数
        "flat_count": int,      # 平盘家数
        "ad_ratio": float,      # 涨跌家数比
        "breadth_signal": str,  # 强势/正常/弱势
    }

    数据源：东财 push2 全市场行情统计
    """
    pass
```

### Step 2：指标计算层（a_stock.py）

```python
def _calculate_seal_quality(
    limitup_stocks: list[dict],
    limitdown_stocks: list[dict],
    back_seal_stocks: list[dict],
) -> dict:
    """
    封板质量综合评估（拆分一字板/换手板）

    返回：
    {
        "yizi_count": int,               # 一字板数量
        "huan_shou_count": int,          # 换手板数量
        "total_limitup": int,            # 涨停总数
        "effective_seal_rate": float,    # 有效封板率（换手板中早盘封板占比）
        "seal_success_rate": float,      # 封板成功率（扣除回封）
        "seal_back_rate": float,         # 炸板回封率
        "seal_strength_median": float,   # 封单强度中位数（换手板）
        "early_seal_count": int,         # 换手板中早盘封板数量(10:30前)
        "late_seal_count": int,          # 尾盘偷袭板数量(14:50后)
    }
    """
    pass

def _calculate_yesterday_performance(
    today_data: list[dict],
) -> dict:
    """
    昨日涨停今日表现（精细化）

    返回：
    {
        "avg_return": float,             # 整体平均涨幅（排除一字开板）
        "continuous_premium": float,     # 连板股溢价率
        "first_board_premium": float,    # 首板股溢价率
        "high_open_rate": float,         # 高开率
        "median_return": float,          # 收盘涨幅中位数
        "muffled_rate": float,           # 闷杀率（>5%）
        "light_muffled_rate": float,     # 轻度闷杀率（>3%）
        "heavy_muffled_rate": float,     # 重度闷杀率（>7%）
        "promotion_rates": dict,         # 各板数晋级率 {2: 0.5, 3: 0.3}
    }
    """
    pass

def _calculate_board_health(
    board_distribution: dict,
) -> float:
    """
    梯队健康度评分

    逻辑：
    - 完整梯队（5-4-3-2-1都有）：100分
    - 有断层（缺少某个板数）：扣分
    - 只有高位没有低位：低分
    """
    pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #5：调整强看好阈值
# 原问题：昨日连板股平均溢价>5%在正常市场几乎达不到
# 修正：降低到实战常用值
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def judge_strong_bullish_emotion(
    highest_board: int,
    board_distribution: dict,
    seal_rate: float,
    yesterday_avg_return: float,
    muffled_rate: float,
    leader_seal_status: str,
    northbound_direction: str,      # 新增：北向资金方向
) -> dict:
    """
    强看好情绪判断（超龙头硬核逻辑）

    核心逻辑：所有条件必须同时满足

    条件1：高标还在封板
      - 最高板 >=5
      - 高标封死（未开板或开板1次内回封）
      - 封单稳定（>80%峰值）

    条件2：连板梯队完整
      - 5板以上 >=1只
      - 3-4板 >=2只
      - 2板 >=3只
      - 首板 >=10只
      - 梯队无断层

    条件3：赚钱效应强
      - 昨日涨停今日平均涨幅 >2%（⚠️ 从3%下调）
      - 昨日连板股平均溢价 >3%（⚠️ 从5%下调）
      - 高开率 >60%（⚠️ 从70%下调）
      - 重度闷杀率 <15%（⚠️ 从10%上调）

    条件4：晋级率高
      - 昨日2板→今日3板 晋级率 >40%（⚠️ 从50%下调）
      - 昨日3板→今日4板 晋级率 >30%（⚠️ 从40%下调）

    条件5：北向资金不流出（新增）
      - 北向资金方向为"小幅流入"或"大幅流入"
      - 如果北向大幅流出，即使其他条件满足，也降级为"偏多"

    强看好信号：全部满足 → 重仓参与
    """
    signals = []

    # 条件1：高标封板
    if highest_board >= 5 and leader_seal_status == "封板":
        signals.append("高标封板")
    else:
        return {"strong_bullish": False, "reason": "高标未封板"}

    # 条件2：梯队完整
    has_5plus = board_distribution.get(5, 0) + board_distribution.get(6, 0) + board_distribution.get(7, 0) >= 1
    has_3_4 = board_distribution.get(3, 0) + board_distribution.get(4, 0) >= 2
    has_2 = board_distribution.get(2, 0) >= 3

    if has_5plus and has_3_4 and has_2:
        signals.append("梯队完整")
    else:
        return {"strong_bullish": False, "reason": "梯队断层"}

    # 条件3：赚钱效应（⚠️ 阈值已下调）
    if yesterday_avg_return > 2 and muffled_rate < 15:
        signals.append("赚钱效应强")
    else:
        return {"strong_bullish": False, "reason": "赚钱效应不足"}

    # 条件4：封板率
    if seal_rate > 80:
        signals.append("封板率高")
    else:
        return {"strong_bullish": False, "reason": "封板率不足"}

    # 条件5：北向资金（新增）
    if northbound_direction in ["大幅流出"]:
        return {"strong_bullish": False, "reason": "北向资金大幅流出"}
    signals.append("北向资金支持")

    return {
        "strong_bullish": True,
        "reason": " + ".join(signals),
        "action": "重仓参与高位接力",
        "target": f"最高板{highest_board}板",
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #6：增加冰点确认机制
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _judge_emotion_phase(
    seal_quality: dict,
    yesterday_performance: dict,
    board_distribution: dict,
    highest_board: int,
    market_breadth: dict,
    northbound_signal: dict,
    recent_2day_data: list[dict] | None = None,  # 新增：近2天数据
) -> str:
    """
    情绪周期判断（含冰点确认机制）

    核心逻辑：
    1. 高标股状态是第一判断依据
    2. 连板梯队健康度
    3. 赚钱效应 + 亏钱效应
    4. 北向资金方向
    5. 市场宽度（涨跌家数比）

    冰点确认机制：
    - 单日冰点信号：高标断板 + 梯队崩塌 + 重度闷杀率>30%
    - 确认冰点：需要连续2天满足以下任意2条
      * 高标断板或降级
      * 闷杀率>25%
      * 晋级率<20%
      * 北向资金连续流出
    """
    # 如果有近2天数据，做冰点确认
    if recent_2day_data and len(recent_2day_data) >= 2:
        confirm_count = 0
        for day_data in recent_2day_data:
            conditions_met = 0
            if day_data.get("highest_board_dropped"):
                conditions_met += 1
            if day_data.get("heavy_muffled_rate", 0) > 25:
                conditions_met += 1
            if day_data.get("avg_promotion_rate", 1) < 0.2:
                conditions_met += 1
            if day_data.get("northbound_direction") in ["小幅流出", "大幅流出"]:
                conditions_met += 1
            if conditions_met >= 2:
                confirm_count += 1

        if confirm_count >= 2:
            return "冰点（已确认）"

    # 单日判断
    pass

def _calculate_emotion_metrics(
    limitup_stocks: list[dict],
    limitdown_stocks: list[dict],
    yesterday_performance: dict,
    market_breadth: dict,
    northbound_signal: dict,
) -> dict:
    """计算情绪量化指标"""
    return {
        "highest_board": int,           # 最高连板数
        "board_distribution": dict,     # {板数: 股票数量}
        "limitup_count": int,           # 涨停家数
        "limitdown_count": int,         # 跌停家数
        "yizi_count": int,              # 一字板数量（新增）
        "huan_shou_count": int,         # 换手板数量（新增）
        "seal_quality": dict,           # 封板质量指标
        "yesterday_performance": dict,  # 昨日涨停今日表现
        "board_health_score": float,    # 梯队健康度评分
        "emotion_phase": str,           # 情绪周期
        "emotion_score": float,         # 情绪综合评分 0-100
        "market_breadth": dict,         # 市场宽度（新增）
        "northbound_signal": dict,      # 北向资金信号（新增）
    }
```

### Step 3：对外接口（a_stock.py）

```python
def get_consecutive_limit_stats(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
) -> str:
    """连板梯队统计 + 情绪量化"""
    pass
```

### Step 4：工具注册

```python
# signal_data_tools.py
@tool
def get_consecutive_limit_stats(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
) -> str:
    """连板梯队统计 + 情绪量化"""
    return route_to_vendor("get_consecutive_limit_stats", trade_date)

# interface.py
VENDOR_METHODS["get_consecutive_limit_stats"] = {
    "a_stock": get_astock_consecutive_limit_stats,
}
```

### Step 5：Agent 接入

```python
# short_term_analyst.py（新建的短线博弈分析师）
tools = [
    get_consecutive_limit_stats,  # 连板梯队统计
    get_theme_heat,              # 题材热度追踪
    get_first_board_screen,      # 首板筛选
    get_high_board_status,       # 高标股状态
    get_leader_identification,   # 龙头识别
]
```

---

## 4. 单元测试

### 4.1 测试文件

```python
# tests/test_short_term_features.py

import pytest
from tradingagents.dataflows.a_stock import (
    get_consecutive_limit_stats,
    _get_limitup_stocks,
    _get_limitdown_stocks,
    _calculate_emotion_metrics,
    _get_market_breadth,
    _get_northbound_emotion_signal,
)

class TestConsecutiveLimitStats:
    """连板梯队统计测试"""

    def test_get_limitup_stocks_returns_data(self):
        """测试获取涨停股票列表"""
        result = _get_limitup_stocks("2026-06-13")
        assert isinstance(result, list)
        if result:
            assert "SECURITY_CODE" in result[0]
            # 验证一字板/换手板分类字段存在
            assert "limit_type" in result[0] or "LIMIT_UP_TYPE" in result[0]

    def test_get_limitup_stocks_empty_date(self):
        """测试空日期处理"""
        result = _get_limitup_stocks("")
        assert isinstance(result, list)

    def test_calculate_emotion_metrics(self):
        """测试情绪指标计算"""
        limitup = [
            {"SECURITY_CODE": "000001", "CONTINUOUS_LIMIT_NUM": 3, "LIMIT_UP_TYPE": "换手"},
            {"SECURITY_CODE": "000002", "CONTINUOUS_LIMIT_NUM": 1, "LIMIT_UP_TYPE": "一字"},
        ]
        limitdown = [{"SECURITY_CODE": "000003"}]
        yesterday_perf = {"avg_return": 2.5, "promotion_rate": 0.3}

        metrics = _calculate_emotion_metrics(limitup, limitdown, yesterday_perf)

        assert metrics["highest_board"] == 3
        assert metrics["board_distribution"] == {3: 1, 1: 1}
        assert metrics["limitup_count"] == 2
        assert metrics["limitdown_count"] == 1
        assert metrics["emotion_phase"] in ["冰点", "冰点（已确认）", "低迷", "修复", "升温", "高潮", "退潮"]

    def test_emotion_phase_boundaries(self):
        """测试情绪周期边界"""
        # 冰点
        metrics = _calculate_emotion_metrics([], [], {"avg_return": -2, "promotion_rate": 0})
        assert metrics["emotion_phase"] == "冰点"

        # 高潮
        metrics = _calculate_emotion_metrics(
            [{"CONTINUOUS_LIMIT_NUM": i, "LIMIT_UP_TYPE": "换手"} for i in range(20)],
            [],
            {"avg_return": 8, "promotion_rate": 0.6}
        )
        assert metrics["emotion_phase"] == "高潮"

    def test_market_breadth(self):
        """测试市场涨跌家数比"""
        result = _get_market_breadth("2026-06-13")
        assert isinstance(result, dict)
        assert "ad_ratio" in result
        assert "breadth_signal" in result
        assert result["breadth_signal"] in ["强势", "正常", "弱势"]

    def test_northbound_signal(self):
        """测试北向资金信号"""
        result = _get_northbound_emotion_signal("2026-06-13")
        assert isinstance(result, dict)
        assert "direction" in result
        assert result["direction"] in ["大幅流入", "小幅流入", "小幅流出", "大幅流出"]

    def test_muffled_rate分级(self):
        """测试闷杀率分级"""
        # 验证轻度/重度闷杀率的区分
        yesterday_perf = {
            "light_muffled_rate": 0.15,
            "heavy_muffled_rate": 0.05,
            "muffled_rate": 0.10,
        }
        # 轻度闷杀率应该 >= 重度闷杀率
        assert yesterday_perf["light_muffled_rate"] >= yesterday_perf["heavy_muffled_rate"]

    def test_get_consecutive_limit_stats_returns_string(self):
        """测试主接口返回格式"""
        result = get_consecutive_limit_stats("2026-06-13")
        assert isinstance(result, str)
        assert "连板梯队" in result or "涨停" in result

    def test_get_consecutive_limit_stats_error_handling(self):
        """测试异常处理"""
        result = get_consecutive_limit_stats("invalid_date")
        assert isinstance(result, str)
        # 不应该抛出异常

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 📌 评审修正 #6：新增冰点确认测试
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    def test_freezing_point_confirmation(self):
        """测试冰点确认机制"""
        # 模拟连续2天冰点信号
        recent_data = [
            {"highest_board_dropped": True, "heavy_muffled_rate": 0.35, "avg_promotion_rate": 0.1},
            {"highest_board_dropped": True, "heavy_muffled_rate": 0.30, "avg_promotion_rate": 0.15},
        ]
        # 应该确认冰点
        # ... 测试逻辑
```

### 4.2 运行测试

```bash
# 运行所有短线功能测试
python -m pytest tests/test_short_term_features.py -v

# 运行单个测试类
python -m pytest tests/test_short_term_features.py::TestConsecutiveLimitStats -v

# 运行单个测试
python -m pytest tests/test_short_term_features.py::TestConsecutiveLimitStats::test_calculate_emotion_metrics -v
```

---

## 5. 验收标准

- [ ] Phase 0：东财 RPT_LIMITUP_STOCK 接口字段验证完成
- [ ] `_get_limitup_stocks()` 返回涨停股票列表（含一字板/换手板分类）
- [ ] `_get_limitdown_stocks()` 返回跌停股票列表
- [ ] `_get_market_breadth()` 返回市场涨跌家数比
- [ ] `_get_northbound_emotion_signal()` 返回北向资金信号
- [ ] `_calculate_emotion_metrics()` 正确计算情绪指标（含闷杀率分级）
- [ ] `get_consecutive_limit_stats()` 返回完整报告
- [ ] 情绪周期判断准确（含冰点确认机制）
- [ ] 强看好判断阈值符合实战（已下调）
- [ ] 异常情况处理完善（网络超时、数据为空、非交易日）
- [ ] 单元测试覆盖率 100%
- [ ] 限流走 `_em_get()`

## 6. 评审修正记录

| # | 原问题 | 修正方案 | 影响范围 |
|---|--------|----------|----------|
| 1 | 一字板不应计入早盘封板 | 拆分一字板/换手板统计 | 封板质量指标 |
| 2 | 数据源字段假设需验证 | 新增 Phase 0 接口验证 | 方案最前端 |
| 3 | 缺少北向资金信号 | 新增 `_get_northbound_emotion_signal()` | 情绪综合评分 |
| 4 | 闷杀率阈值偏保守 | 分级：轻度(>3%)/标准(>5%)/重度(>7%) | 赚钱效应指标 |
| 5 | 强看好阈值过于理想化 | 下调各指标阈值至实战常用值 | 强看好判断 |
| 6 | 缺少冰点确认机制 | 新增连续2天确认窗口 | 情绪周期判断 |
