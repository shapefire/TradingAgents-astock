
# 功能4：高标股状态监控

## 1. 功能说明

### 1.1 核心价值

短线交易者的**情绪风向标**：市场最高板的票现在什么状态？分歧还是一致？明天还能不能买？

### 1.2 解决的问题

| 现状 | 目标 |
|------|------|
| 没有高标股状态追踪 | 实时监控最高板票状态 |
| 没有分歧/一致判断 | 量化分歧程度 |
| 没有断板风险评估 | 提前预警断板风险 |

### 1.3 使用场景

```
场景1：情绪判断
  高标封死 → 情绪一致 → 可以做高位接力
  高标炸板 → 情绪分歧 → 回避高位，只做低位

场景2：风险预警
  高标连续一字后首次放量 → 断板风险高 → 提前回避

场景3：接力决策
  高标断板 → 新龙头可能诞生 → 关注低位补涨龙
```

---

## 2. 技术方案

### 2.0 ⚠️ 数据限制说明

> **问题**：分时封单变化趋势的量化方法需要明确
> 实战中需要获取盘中封单金额的变化趋势，但免费接口只返回当前快照，
> 不返回历史封单数据。

**应对方案：**
- 用分时 K 线的成交量/价格变化间接估算封单变化
- 如果无法获取分时数据，简化为"封板状态"（封死/分歧/断板）的二元判断

### 2.1 数据源分析

| 数据 | 来源 | 接口 | 说明 |
|------|------|------|------|
| 涨停股票列表 | 东财 datacenter | `RPT_LIMITUP_STOCK` | 连板天数，筛选最高板 |
| 个股行情 | 东财 push2 | 实时行情 | 当前封单量、成交额、换手率 |
| 分时数据 | 东财 push2his | 分时K线 | 判断封单变化（可选） |
| 概念板块 | 东财 push2 | 板块接口 | 高标股所属板块行情 |

### 2.2 核心指标计算（实战版）

```python
# 高标股状态指标（资深交易者视角）

1. 基础信息
   - 最高连板数
   - 最高板股票列表（可能多只同板）
   - 所属题材

2. 封单状态（简化版，适配可用数据）
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #1：简化分歧度模型
   # 原问题：5因子模型过于复杂，盘中实时获取困难
   # 修正：简化为2核心因子
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   - 当前封单金额
   - 封单/流通盘比
   - 封板状态（封死/分歧/断板）→ 二元判断

3. 分歧程度（简化版）
   核心因子（只保留2个最关键的）：
   - 封单稳定性（权重50%）
     * 封单是否还在（是/否）→ 1秒判断
     * 封单/流通盘比 >3% → 封单充足
     * 封单/流通盘比 1-3% → 封单一般
     * 封单/流通盘比 <1% → 封单不足

   - 开板次数（权重50%）
     * 0次：一致（无分歧）
     * 1-2次：轻度分歧
     * 3-5次：中度分歧
     * >5次：重度分歧（随时可能炸）

   综合判断：
   - 一致：分歧度<30 → 可以做高位接力
   - 轻度分歧：30-50 → 可以做，但要谨慎
   - 中度分歧：50-70 → 不建议参与
   - 重度分歧：>70 → 绝对不参与

   注意：
   - 换手率、量比、分时形态在盘中实时获取困难
   - 且对决策的边际贡献不大
   - 核心就是看2件事：封单还在不在 + 开了几次板

4. 断板风险评估（实战版）
   高风险信号（命中任意一个→高风险）：
   - 连续一字板>=3天，今日开板
     * 一字板积累的获利盘太多，开板必砸

   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #2：细化一字板风险评估
   # 原问题：一字板需要区分缩量/放量
   # 修正：增加"一字板期间累计换手率"因子
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   - 连续一字板>=3天，今日开板
     * 如果一字板期间累计换手率<5%（缩量一字）→ 中风险
     * 如果一字板期间累计换手率>10%（放量一字）→ 高风险
     * 放量一字的获利盘更多，开板必砸

   - 封单持续减少（连续2天减少>30%）
     * 主力在撤退

   - 分歧度>70 + 同题材走弱
     * 内外双重压力

   - 市场情绪转差 + 高标开始分歧
     * 系统性风险

   中风险信号：
   - 封单小幅减少（10-30%）
   - 分歧度50-70
   - 同题材开始分化

   低风险信号：
   - 封单稳定或增加
   - 分歧度<50
   - 同题材强势
   - 市场情绪好

5. 板块效应
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #4：明确板块效应获取方式
   # 原问题：文档提到"板块效应"但没给出具体实现
   # 修正：用 get_concept_blocks() 获取概念板块行情
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   - 高标股所属概念板块
   - 板块整体涨跌幅
   - 板块内其他股票表现
   - 板块资金流向

   实现方式：
   1. 通过 get_concept_blocks(code) 获取高标股的概念板块
   2. 通过 push2 板块接口获取板块行情
   3. 计算板块涨跌幅

6. 市场地位
   - 是否为市场总龙头（跨题材）
   - 是否有卡位竞争者
   - 是否为情绪标（市场情绪的风向标）

7. 超龙头视角简化（核心改进）
   - 分歧评估简化为：
     1. 封单是否还在
     2. 开板次数
   - 不需要复杂的多因子模型
   - 3秒判断：封单稳定+未开板=一致，否则=分歧

8. 断板风险卡位维度（新增）
   - 有卡位股存在时，高标断板风险更高
   - 超龙头选手会同时监控高标和卡位
   - 卡位股封板 + 高标分歧 = 高风险
```

### 2.3 接口设计

```python
def get_high_board_status(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
) -> str:
    """
    高标股状态监控

    返回内容：
    1. 市场最高板股票信息
    2. 封单状态（封死/分歧/断板）
    3. 分歧程度评估（简化版：封单稳定性+开板次数）
    4. 断板风险等级（高/中/低）
    5. 板块效应
    6. 明日操作建议

    数据源：东财 datacenter + push2
    限流：统一走 _em_get()
    """
```

---

## 3. 实现步骤

### Step 1：数据获取层（a_stock.py）

```python
def _get_high_board_stocks(trade_date: str) -> list[dict]:
    """
    获取市场最高板股票

    逻辑：
    1. 获取所有涨停股票
    2. 找出最大连板天数
    3. 返回该板数的所有股票
    """
    pass

def _get_high_board_detail(code: str) -> dict:
    """
    获取高标股详细信息

    返回：
    {
        "code": "000001",
        "name": "股票A",
        "board_num": 5,              # 连板天数
        "theme": "人工智能",
        "seal_amount": 100000000,    # 当前封单金额
        "circulation_mv": 5000000000,  # 流通市值
        "seal_ratio": 0.02,          # 封单/流通盘比
        "turnover_rate": 0.05,       # 换手率
        "amount": 500000000,         # 成交额
        "open_count": 0,             # 开板次数
        "is_yizi": False,            # 是否一字板
        "seal_status": "封板",       # 封板/分歧/断板
    }

    注意：不返回 seal_amount_peak（不可获取）
    """
    pass

def _get_seal_trend(code: str) -> dict:
    """
    获取封单变化趋势（简化版）

    返回：
    {
        "seal_stable": True,         # 封单是否稳定
        "trend": "stable",           # increasing/stable/decreasing
    }

    注意：
    - 如果无法获取分时数据，返回默认值
    - 用分时K线的成交量变化间接估算
    """
    pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #4：新增板块效应获取函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _get_theme_effect_for_high_board(code: str) -> dict:
    """
    获取高标股所属板块的效应

    逻辑：
    1. 通过 get_concept_blocks(code) 获取概念板块
    2. 获取板块整体涨跌幅
    3. 判断板块是否强势

    返回：
    {
        "themes": ["AI", "算力"],       # 所属概念板块
        "theme_performance": 2.5,       # 板块平均涨跌幅
        "is_theme_strong": True,        # 板块是否强势
        "other_stocks_in_theme": 8,     # 板块内其他涨停股数
    }
    """
    pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #2：新增一字板累计换手率计算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _get_yizi_cumulative_turnover(code: str, yizi_days: int) -> float:
    """
    计算一字板期间累计换手率

    逻辑：
    1. 获取近N天（一字板天数）的K线数据
    2. 累加每天的换手率

    返回：
    - float: 累计换手率（%）

    用途：
    - 缩量一字（累计<5%）→ 开板风险中等
    - 放量一字（累计>10%）→ 开板风险高
    """
    pass
```

### Step 2：指标计算层（a_stock.py）

```python
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #1：简化分歧度模型
# 原问题：5因子模型过于复杂
# 修正：简化为2核心因子（封单稳定性+开板次数）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _calculate_divergence_score(
    seal_stable: bool,
    open_count: int,
    seal_ratio: float,
) -> dict:
    """
    分歧程度评估（简化版）

    核心因子（只保留2个）：
    1. 封单稳定性（权重50%）
       - 封单是否还在（是/否）
       - 封单/流通盘比

    2. 开板次数（权重50%）
       - 0次：一致
       - 1-2次：轻度分歧
       - 3-5次：中度分歧
       - >5次：重度分歧

    返回：
    {
        "divergence_score": float,    # 0-100
        "level": str,                 # 一致/轻度分歧/中度分歧/重度分歧
        "can_do_high_board": bool,    # 是否可以做高位接力
    }

    优势：
    - 简单直接，3秒判断
    - 不需要复杂的分时数据
    - 实战中够用
    """
    score = 0

    # 因子1：封单稳定性（50%权重）
    if not seal_stable:
        score += 50  # 封单不在，高分歧
    elif seal_ratio < 1:
        score += 30  # 封单不足
    elif seal_ratio < 3:
        score += 15  # 封单一般
    # 封单充足（>3%）→ +0

    # 因子2：开板次数（50%权重）
    if open_count == 0:
        score += 0   # 无开板
    elif open_count <= 2:
        score += 15  # 轻度
    elif open_count <= 5:
        score += 30  # 中度
    else:
        score += 50  # 重度

    # 判断级别
    if score < 30:
        level = "一致"
        can_do = True
    elif score < 50:
        level = "轻度分歧"
        can_do = True
    elif score < 70:
        level = "中度分歧"
        can_do = False
    else:
        level = "重度分歧"
        can_do = False

    return {
        "divergence_score": score,
        "level": level,
        "can_do_high_board": can_do,
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #2：细化一字板风险评估
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _calculate_break_risk_level(
    board_num: int,
    seal_status: str,
    open_count: int,
    divergence_score: float,
    same_theme_performance: float,
    market_emotion: str,
    consecutive_yizi_days: int,
    yizi_cumulative_turnover: float,  # 新增：一字板累计换手率
    card_position_exists: bool,
) -> dict:
    """
    断板风险评估（细化版）

    高风险信号（命中任意一个→高风险）：
    1. 连续一字板>=3天，今日开板
       - 缩量一字（累计换手率<5%）→ 中风险
       - 放量一字（累计换手率>10%）→ 高风险

    2. 封单持续减少（连续2天减少>30%）

    3. 分歧度>70 + 同题材走弱

    4. 市场情绪转差 + 高标开始分歧

    中风险信号：
    1. 封单小幅减少（10-30%）
    2. 分歧度50-70
    3. 同题材开始分化

    低风险信号：
    1. 封单稳定或增加
    2. 分歧度<50
    3. 同题材强势
    4. 市场情绪好
    """
    risk_signals = []

    # 信号1：一字板后开板
    if consecutive_yizi_days >= 3 and open_count > 0:
        if yizi_cumulative_turnover > 10:
            risk_signals.append("放量一字后开板（高风险）")
        elif yizi_cumulative_turnover > 5:
            risk_signals.append("一字后开板（中风险）")
        else:
            risk_signals.append("缩量一字后开板（中低风险）")

    # 信号2：封单不足
    if seal_status != "封板":
        risk_signals.append("封板状态异常")

    # 信号3：分歧严重
    if divergence_score > 70:
        risk_signals.append("分歧度>70")

    # 信号4：题材走弱
    if same_theme_performance < -1:
        risk_signals.append("同题材走弱")

    # 信号5：情绪转差
    if market_emotion in ["冰点", "退潮"]:
        risk_signals.append("市场情绪转差")

    # 信号6：卡位威胁
    if card_position_exists:
        risk_signals.append("有卡位威胁")

    # 判断风险等级
    high_risk_keywords = ["放量一字后开板", "封板状态异常", "分歧度>70"]
    has_high_risk = any(kw in signal for kw in high_risk_keywords for signal in risk_signals)

    if has_high_risk:
        risk_level = "高"
    elif len(risk_signals) >= 2:
        risk_level = "中"
    elif len(risk_signals) == 1:
        risk_level = "中低"
    else:
        risk_level = "低"

    return {
        "risk_level": risk_level,
        "risk_signals": risk_signals,
        "consecutive_yizi_days": consecutive_yizi_days,
        "yizi_cumulative_turnover": yizi_cumulative_turnover,
    }

def judge_strong_bullish_high_board(
    board_num: int,
    seal_status: str,
    seal_amount: float,
    seal_ratio: float,
    open_count: int,
    same_theme_performance: float,
    market_emotion: str,
) -> dict:
    """
    强看好高标判断（超龙头硬核逻辑）

    核心逻辑：高标必须"一致封板"

    条件1：高标足够高（>=5板）
    条件2：封板一致（封死+封单充足）
    条件3：题材支撑（板块强势）
    条件4：市场情绪支持（升温或高潮）

    强看好信号：全部满足 → 可以高位接力
    """
    if board_num < 5:
        return {"strong_bullish": False, "reason": "高度不够"}

    if seal_status != "封板":
        return {"strong_bullish": False, "reason": "未封板"}

    if seal_ratio < 0.03 or open_count > 0:
        return {"strong_bullish": False, "reason": "封板不一致"}

    if same_theme_performance < 0:
        return {"strong_bullish": False, "reason": "题材走弱"}

    if market_emotion not in ["升温", "高潮"]:
        return {"strong_bullish": False, "reason": "市场情绪不支持"}

    return {
        "strong_bullish": True,
        "reason": f"高标{board_num}板一致封板 + 题材支撑",
        "action": "可以高位接力",
        "target": f"{board_num + 1}板",
    }

def judge_strong_bearish_high_board(
    board_num: int,
    seal_status: str,
    open_count: int,
    consecutive_yizi_days: int,
    yizi_cumulative_turnover: float,
    card_position_exists: bool,
) -> dict:
    """
    强看空高标判断（超龙头硬核逻辑）

    核心逻辑：高标出现"危险信号"

    看空信号1：高标断板
    看空信号2：封板分歧严重（开板>3次）
    看空信号3：一字后开板（放量一字风险更高）
    看空信号4：有卡位威胁

    强看空信号：任一条件满足 → 不参与高位接力
    """
    reasons = []

    if seal_status == "断板":
        reasons.append("高标断板（最强看空信号）")

    if open_count > 3:
        reasons.append("封板分歧严重")

    if consecutive_yizi_days >= 3 and open_count > 0:
        if yizi_cumulative_turnover > 10:
            reasons.append("放量一字后开板（高风险）")
        else:
            reasons.append("一字后开板")

    if card_position_exists:
        reasons.append("有卡位威胁")

    if reasons:
        return {
            "strong_bearish": True,
            "reason": " + ".join(reasons),
            "action": "不参与高位接力，等待新龙头",
        }

    return {"strong_bearish": False, "reason": "无明显看空信号"}
```

### Step 3：对外接口（a_stock.py）

```python
def get_high_board_status(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
) -> str:
    """高标股状态监控"""
    pass
```

### Step 4：工具注册

```python
# signal_data_tools.py
@tool
def get_high_board_status(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
) -> str:
    """高标股状态监控"""
    return route_to_vendor("get_high_board_status", trade_date)

# interface.py
VENDOR_METHODS["get_high_board_status"] = {
    "a_stock": get_astock_high_board_status,
}
```

### Step 5：Agent 接入

```python
# short_term_analyst.py（新建的短线博弈分析师）
tools = [
    ...,
    get_high_board_status,  # 新增
]
```

---

## 4. 单元测试

### 4.1 测试文件

```python
# tests/test_short_term_features.py

class TestHighBoardStatus:
    """高标股状态监控测试"""

    def test_get_high_board_stocks(self):
        """测试获取最高板股票"""
        result = _get_high_board_stocks("2026-06-13")
        assert isinstance(result, list)
        if result:
            assert "board_num" in result[0]

    def test_calculate_divergence_score_consistent(self):
        """测试分歧评分 - 一致"""
        result = _calculate_divergence_score(
            seal_stable=True, open_count=0, seal_ratio=5.0
        )
        assert result["divergence_score"] < 30
        assert result["level"] == "一致"
        assert result["can_do_high_board"] == True

    def test_calculate_divergence_score_moderate(self):
        """测试分歧评分 - 中度分歧"""
        result = _calculate_divergence_score(
            seal_stable=True, open_count=4, seal_ratio=2.0
        )
        assert 50 <= result["divergence_score"] < 70
        assert result["level"] == "中度分歧"
        assert result["can_do_high_board"] == False

    def test_calculate_divergence_score_severe(self):
        """测试分歧评分 - 重度分歧"""
        result = _calculate_divergence_score(
            seal_stable=False, open_count=6, seal_ratio=0.5
        )
        assert result["divergence_score"] >= 70
        assert result["level"] == "重度分歧"
        assert result["can_do_high_board"] == False

    def test_calculate_break_risk_high(self):
        """测试断板风险 - 高风险"""
        risk = _calculate_break_risk_level(
            board_num=5,
            seal_status="封板",
            open_count=1,
            divergence_score=20,
            same_theme_performance=1.0,
            market_emotion="升温",
            consecutive_yizi_days=4,
            yizi_cumulative_turnover=15,  # 放量一字
            card_position_exists=False,
        )
        assert risk["risk_level"] == "高"
        assert "放量一字后开板" in str(risk["risk_signals"])

    def test_calculate_break_risk_low(self):
        """测试断板风险 - 低风险"""
        risk = _calculate_break_risk_level(
            board_num=3,
            seal_status="封板",
            open_count=0,
            divergence_score=10,
            same_theme_performance=2.0,
            market_emotion="升温",
            consecutive_yizi_days=2,
            yizi_cumulative_turnover=3,
            card_position_exists=False,
        )
        assert risk["risk_level"] == "低"

    def test_get_high_board_status_returns_string(self):
        """测试主接口返回格式"""
        result = get_high_board_status("2026-06-13")
        assert isinstance(result, str)
        assert "高标" in result or "连板" in result

    def test_get_high_board_status_no_data(self):
        """测试无数据情况"""
        result = get_high_board_status("2020-01-01")
        assert isinstance(result, str)

    def test_theme_effect(self):
        """测试板块效应获取"""
        result = _get_theme_effect_for_high_board("000001")
        assert isinstance(result, dict)
        assert "is_theme_strong" in result
```

### 4.2 运行测试

```bash
python -m pytest tests/test_short_term_features.py::TestHighBoardStatus -v
```

---

## 5. 验收标准

- [ ] `_get_high_board_stocks()` 正确获取最高板股票
- [ ] `_calculate_divergence_score()` 简化版评分合理（2因子）
- [ ] `_calculate_break_risk_level()` 风险等级准确（含一字板累计换手率）
- [ ] `_get_theme_effect_for_high_board()` 板块效应获取正确
- [ ] `get_high_board_status()` 返回完整报告
- [ ] 封板状态判断正确（封死/分歧/断板）
- [ ] 断板风险预警准确
- [ ] 异常情况处理完善
- [ ] 单元测试覆盖率 100%
- [ ] 限流走 `_em_get()`

## 6. 评审修正记录

| # | 原问题 | 修正方案 | 影响范围 |
|---|--------|----------|----------|
| 1 | 分歧度5因子模型过于复杂 | 简化为2因子（封单稳定性+开板次数） | 分歧度评估 |
| 2 | 一字板风险未区分缩量/放量 | 增加"一字板累计换手率"因子 | 断板风险评估 |
| 3 | 封单变化趋势难以量化 | 简化为封单状态二元判断 | 封单状态 |
| 4 | 板块效应获取方式不明确 | 用 get_concept_blocks() 获取概念板块行情 | 板块效应 |
