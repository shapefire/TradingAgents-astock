# 功能3：首板筛选 + 二板预期

## 1. 功能说明

### 1.1 核心价值

短线交易者的**核心战法支撑**：今天首板的票，明天有没有二板预期？

### 1.2 解决的问题

| 现状 | 目标 |
|------|------|
| `get_hot_stocks` 给了涨停列表但不区分首板/连板 | 明确筛选首板票 |
| 没有封单强度分析 | 量化封板强度 |
| 没有二板预期评估 | 给出二板概率评分 |

### 1.3 使用场景

```
场景1：盘后复盘
  交易者筛选今日首板票 → 评估二板预期 → 制定明日打板计划

场景2：战法执行
  交易者专注于首板战法 → 需要高质量的首板筛选

场景3：风险管理
  交易者评估二板预期 → 决定仓位大小
```

---

## 2. 技术方案

### 2.0 ⚠️ 数据限制说明

> **问题 1**：封单峰值数据（`seal_amount_peak`）不可获取
> 东财 push2 的实时行情接口只返回当前封单金额，不返回日内峰值。
> 要获取峰值需要盘中实时采集（分时监控），免费接口无法做到。

> **问题 2**：撤单次数数据不可获取
> 东财没有公开的撤单次数 API。撤单次数只能从 Level 2 逐笔委托中获取，
> 普通免费接口无法拿到。

**应对方案：**
- 封单峰值 → 改用"当前封单/流通盘比"作为封单强度指标
- 封单稳定性 → 用分时 K 线的封单金额标准差/均值估算
- 撤单次数 → 移除该指标，改用"封单稳定性"替代

### 2.1 数据源分析

| 数据 | 来源 | 接口 | 说明 |
|------|------|------|------|
| 涨停股票列表 | 东财 datacenter | `RPT_LIMITUP_STOCK` | 连板天数=1为首次涨停 |
| 个股行情 | 东财 push2 | 实时行情 | 当前封单量、成交额、换手率、流通市值 |
| 概念板块 | 东财 push2 | 板块接口 | 所属题材热度 |
| 分时K线 | 东财 push2his | 分时数据 | 封单稳定性估算（可选） |

### 2.2 核心指标计算（实战版）

```python
# 首板筛选指标（资深交易者视角）

1. 封单强度（修正后，适配可用数据）
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #1 #2：移除不可获取的指标
   # 原问题：封单峰值和撤单次数无法通过免费接口获取
   # 修正：改用可用指标
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   - 封单/流通盘比（核心指标）
     * >5%：极强
     * 2-5%：强
     * <2%：弱

   - 封单稳定性（替代撤单次数）
     * 计算方法：最近30分钟封单金额的标准差/均值
     * <20%：稳定（封单波动小）
     * 20-40%：一般
     * >40%：不稳定（封单波动大，可能炸板）
     * 数据来源：分时K线（如果无法获取则跳过此指标）

   - 板型判断（一字/T字/换手）
     * 一字板：开盘即封死，筹码锁定好，但换手不充分，开板风险高
     * 换手板：盘中封板，经过充分换手，质量更稳定
     * T字板：一字开盘，盘中开板后回封

2. 量价配合（精细化）
   - 换手率（<5% 缩量板，5-15% 适度放量，>15% 放量板）
   - 成交额（绝对值，流动性考量）
   - 相对前日量比
   - 首板时间
     * 早盘首板（9:30-10:00）→ 二板概率高
     * 午盘首板（10:00-13:00）→ 二板概率中
     * 尾盘首板（13:00-15:00）→ 二板概率低

3. 题材热度
   - 所属题材今日涨停家数
   - 所属题材热度评分
   - 是否为题材龙头
   - 题材纯正度

   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #3：明确题材纯正度量化方法
   # 原问题：文档提到"题材纯正度"但没给出具体实现
   # 修正：用简单实用的量化方法
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   题材纯正度量化方法：
   - 是否为题材内连板最高的票（是=+30分，否=+0分）
   - 涨停原因是否直接匹配公司主营业务关键词（是=+30分，否=+0分）
   - 题材涨停家数>=10（是=+20分，否=+0分）
   - 有梯队支撑（同题材有2板以上）（是=+20分，否=+0分）
   - 总分 0-100

4. 历史股性
   - 活跃股（近1年涨停>=5次）→ 二板概率高（80-100分）
   - 一般股（近1年涨停2-4次）→ 二板概率中（40-70分）
   - 僵尸股（近1年涨停0-1次）→ 二板概率低（0-30分）

5. 板块位置
   - 板块内首只涨停 → 二板概率高
   - 板块内跟风涨停 → 二板概率低

6. 市场环境
   - 情绪好（高潮/升温）→ 二板概率高
   - 情绪差（冰点/低迷）→ 二板概率低

7. 二板预期评分

8. 超龙头视角说明（核心改进）
   - 超龙头选手不做首板，只做高位接力
   - 首板是游资的工作，不是龙头选手的工作
   - 龙头选手只在龙头断板后寻找新龙头
   - 本功能更适合"首板选手"，不适合"超龙头选手"
   - 超龙头选手需要的是：
     1. 高位接力筛选（2板以上）
     2. 新龙头识别（从2-3板中筛选）

9. 二板预期简化评分（超龙头版）
   - 只看3个因子：
     1. 题材热度：50%
     2. 封单强度：30%
     3. 市场情绪：20%
   - 简单直接，实战好用
```

### 2.3 二板预期评分模型（修正版）

```python
def calculate_second_board_score(
    seal_strength: float,         # 封单/流通盘比（%），0-100
    volume_match: float,          # 量价配合 0-100
    theme_heat: float,            # 题材热度 0-100
    board_type: str,              # 一字/T字/换手
    market_emotion: str,          # 市场情绪
    circulation_mv: float,        # 流通市值（元）
    first_limit_time: str,        # 首板时间
    theme_purity: float,          # 题材纯正度 0-100
    historical_activity: float,   # 历史股性评分 0-100
) -> float:
    """
    二板预期评分（修正版）

    核心因子及权重：
    1. 封单强度：25%（封板质量）
    2. 量价配合：15%（筹码交换）
    3. 题材热度：20%（题材支撑）
    4. 市场情绪：20%（⚠️ 从15%上调）★关键修正★
    5. 首板时间：10%
    6. 题材纯正度：5%（从10%下调）
    7. 历史股性：5%

    特殊调整：
    - 一字板：-10分（开板风险高）
    - T字板：+0分
    - 换手板：+5分（换手充分）

    市场情绪调整：
    - 情绪好（高潮/升温）：+10分
    - 情绪一般（修复/分歧）：+0分
    - 情绪差（冰点/低迷）：-10分

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 📌 评审修正 #5：调整流通市值阈值
    # 原问题：20亿/50亿阈值不适合短线活跃票
    # 修正：调整为50亿/200亿
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    流通市值调整：
    - <50亿：+5分（小盘股弹性大，但注意流动性）
    - 50-200亿：+0分（最佳区间）
    - >200亿：-5分（大盘股难封）

    首板时间调整：
    - 9:30-10:00：+5分（早盘优势）
    - 10:00-13:00：+0分
    - 13:00-15:00：-5分（尾盘偷袭）
    """
    score = (
        seal_strength * 0.25 +
        volume_match * 0.15 +
        theme_heat * 0.20 +
        _market_emotion_score(market_emotion) * 0.20 +  # 权重从15%上调到20%
        _first_limit_time_score(first_limit_time) * 0.10 +
        theme_purity * 0.05 +  # 权重从10%下调到5%
        historical_activity * 0.05
    )

    # 板型调整
    if board_type == "一字":
        score -= 10
    elif board_type == "换手":
        score += 5

    # 市场情绪调整
    if market_emotion in ["高潮", "升温"]:
        score += 10
    elif market_emotion in ["冰点", "低迷"]:
        score -= 10

    # 流通市值调整（⚠️ 阈值已调整）
    if circulation_mv < 5e9:
        score += 5
    elif circulation_mv > 2e10:
        score -= 5

    # 首板时间调整
    if first_limit_time < "10:00":
        score += 5
    elif first_limit_time > "13:00":
        score -= 5

    return round(max(0, min(100, score)), 1)
```

### 2.4 接口设计

```python
def get_first_board_screen(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
    min_score: Annotated[int, "最低二板预期评分, 默认60"] = 60,
) -> str:
    """
    首板筛选 + 二板预期评估

    返回内容：
    1. 今日首板票列表（按二板预期评分排序）
    2. 每只票的封单强度、量价配合、题材热度
    3. 二板预期评分（0-100）
    4. 标注高评分标的

    数据源：东财 datacenter + push2
    限流：统一走 _em_get()

    数据限制说明：
    - 封单峰值不可获取，改用当前封单/流通盘比
    - 撤单次数不可获取，改用封单稳定性（分时K线估算）
    """
```

---

## 3. 实现步骤

### Step 1：数据获取层（a_stock.py）

```python
def _get_first_board_stocks(trade_date: str) -> list[dict]:
    """
    获取今日首板股票（连板天数=1）

    返回：
    [
        {
            "code": "000001",
            "name": "股票A",
            "seal_amount": 50000000,           # 当前封单金额
            "seal_ratio": 0.01,                # 封单/流通盘比
            "circulation_mv": 5000000000,      # 流通市值
            "turnover_rate": 0.08,             # 换手率
            "amount": 200000000,               # 成交额
            "theme": "AI",                     # 题材（归一化后）
            "first_limit_time": "09:35",       # 涨停时间
            "board_type": "换手",              # 一字/T字/换手
            "theme_purity": 85,                # 题材纯正度
        },
    ]

    注意：
    - 不包含 seal_amount_peak（不可获取）
    - 不包含 withdraw_count（不可获取）
    """
    # 1. 获取涨停列表
    # 2. 筛选连板天数=1
    # 3. 补充行情数据
    pass

def _get_stock_seal_info(code: str) -> dict:
    """
    获取个股封单信息（修正版，移除不可获取的指标）

    返回：
    {
        "seal_amount": 50000000,              # 当前封单金额
        "seal_ratio": 0.01,                   # 封单/流通盘比
        "seal_strength_score": 85,            # 封单强度评分 0-100
        "seal_stability": 0.5,                # 封单稳定性（分时K线估算，可选）
        "board_type": "换手",                 # 一字/T字/换手
    }

    注意：
    - 不返回 seal_amount_peak（不可获取）
    - 不返回 withdraw_count（不可获取）
    - seal_stability 需要分时K线数据，如果无法获取则返回 None
    """
    pass

def _get_seal_stability_from_intraday(code: str) -> float | None:
    """
    从分时K线估算封单稳定性（可选指标）

    逻辑：
    1. 获取当日分时K线数据
    2. 提取封单金额序列（如果有）
    3. 计算标准差/均值

    返回：
    - float: 封单稳定性（标准差/均值）
    - None: 如果无法获取分时数据

    注意：此函数为可选，如果分时接口不支持封单数据则返回 None
    """
    pass

def _get_historical_activity(code: str) -> float:
    """
    获取历史股性评分

    逻辑：
    - 近1年涨停次数 >=5：活跃（80-100分）
    - 近1年涨停次数 2-4：一般（40-70分）
    - 近1年涨停次数 0-1：僵尸股（0-30分）
    """
    pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #3：新增题材纯正度量化函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _calculate_theme_purity(
    code: str,
    theme_name: str,
    theme_stocks: list[dict],
    same_theme_ladder: dict,
) -> float:
    """
    计算题材纯正度（0-100分）

    评分维度：
    1. 是否为题材内连板最高的票 → +30分
    2. 涨停原因是否直接匹配公司主营业务关键词 → +30分
    3. 题材涨停家数>=10 → +20分
    4. 有梯队支撑（同题材有2板以上）→ +20分
    """
    score = 0

    # 1. 是否为题材内连板最高
    my_board_num = next((s["board_num"] for s in theme_stocks if s["code"] == code), 0)
    max_board = max((s["board_num"] for s in theme_stocks), default=0)
    if my_board_num == max_board and my_board_num > 0:
        score += 30

    # 2. 涨停原因匹配主营业务（简化实现）
    # 实际中可以用同花顺/东财的主营业务关键词匹配
    # 这里简化为：如果涨停原因包含公司名称关键词则加分
    # ... 实现逻辑

    # 3. 题材涨停家数
    if len(theme_stocks) >= 10:
        score += 20
    elif len(theme_stocks) >= 5:
        score += 10

    # 4. 梯队支撑
    if same_theme_ladder.get(2, 0) > 0 or same_theme_ladder.get(3, 0) > 0:
        score += 20

    return min(100, score)

def judge_strong_bullish_first_board(
    theme_heat: float,
    seal_strength: float,
    first_limit_time: str,
    market_emotion: str,
    theme_stock_count: int,
) -> dict:
    """
    强看好首板判断（超龙头硬核逻辑）

    核心逻辑：只做"题材龙头首板"

    条件1：题材够强（涨停家数>=10）
    条件2：封单够强（封单/流通盘>3%）
    条件3：时间够早（涨停时间<10:00）
    条件4：市场情绪支持（升温或高潮）

    强看好信号：全部满足 → 打板参与
    """
    if theme_stock_count < 10:
        return {"strong_bullish": False, "reason": "题材不够强"}

    if seal_strength < 3:
        return {"strong_bullish": False, "reason": "封单不够强"}

    if first_limit_time >= "10:00":
        return {"strong_bullish": False, "reason": "涨停时间太晚"}

    if market_emotion not in ["升温", "高潮"]:
        return {"strong_bullish": False, "reason": "市场情绪不支持"}

    return {
        "strong_bullish": True,
        "reason": "题材龙头首板 + 封单强 + 早盘涨停",
        "action": "打板参与",
        "target": "二板预期高",
    }

def judge_strong_bearish_first_board(
    theme_heat: float,
    seal_strength: float,
    first_limit_time: str,
    market_emotion: str,
    board_type: str,
) -> dict:
    """
    强看空首板判断（超龙头硬核逻辑）

    核心逻辑：回避"垃圾首板"

    看空信号1：题材太弱（涨停家数<5）
    看空信号2：封单太弱（封单/流通盘<1%）
    看空信号3：尾盘偷袭（涨停时间>14:00）
    看空信号4：一字板（开板风险高）

    强看空信号：任一条件满足 → 不参与
    """
    reasons = []

    if theme_heat < 30:
        reasons.append("题材太弱")

    if seal_strength < 1:
        reasons.append("封单太弱")

    if first_limit_time >= "14:00":
        reasons.append("尾盘偷袭板")

    if board_type == "一字":
        reasons.append("一字板（开板风险高）")

    if reasons:
        return {
            "strong_bearish": True,
            "reason": " + ".join(reasons),
            "action": "不参与",
        }

    return {"strong_bearish": False, "reason": "无明显看空信号"}
```

### Step 3：对外接口（a_stock.py）

```python
def get_first_board_screen(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
    min_score: Annotated[int, "最低二板预期评分, 默认60"] = 60,
) -> str:
    """首板筛选 + 二板预期评估"""
    pass
```

### Step 4：工具注册

```python
# signal_data_tools.py
@tool
def get_first_board_screen(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
    min_score: Annotated[int, "最低二板预期评分, 默认60"] = 60,
) -> str:
    """首板筛选 + 二板预期评估"""
    return route_to_vendor("get_first_board_screen", trade_date, min_score)

# interface.py
VENDOR_METHODS["get_first_board_screen"] = {
    "a_stock": get_astock_first_board_screen,
}
```

### Step 5：Agent 接入

```python
# short_term_analyst.py（新建的短线博弈分析师）
tools = [
    ...,
    get_first_board_screen,  # 新增
]
```

---

## 4. 单元测试

### 4.1 测试文件

```python
# tests/test_short_term_features.py

class TestFirstBoardScreen:
    """首板筛选测试"""

    def test_get_first_board_stocks(self):
        """测试获取首板股票"""
        result = _get_first_board_stocks("2026-06-13")
        assert isinstance(result, list)
        if result:
            assert "code" in result[0]
            assert "seal_amount" in result[0]
            # 验证不包含不可获取的字段
            assert "seal_amount_peak" not in result[0]
            assert "withdraw_count" not in result[0]

    def test_calculate_theme_purity(self):
        """测试题材纯正度计算"""
        theme_stocks = [
            {"code": "000001", "board_num": 3},
            {"code": "000002", "board_num": 1},
            {"code": "000003", "board_num": 1},
        ]
        # 000001 是题材内连板最高的
        purity = _calculate_theme_purity("000001", "AI", theme_stocks, {1: 2})
        assert purity >= 50  # 应该有较高纯正度

    def test_calculate_volume_match_score_optimal(self):
        """测试量价配合评分 - 最佳区间"""
        score = _calculate_volume_match_score(
            turnover_rate=10,
            amount=150000000,
            volume_ratio=2.0
        )
        assert 80 <= score <= 100

    def test_calculate_volume_match_score_low(self):
        """测试量价配合评分 - 低换手"""
        score = _calculate_volume_match_score(
            turnover_rate=2,
            amount=30000000,
            volume_ratio=0.8
        )
        assert 30 <= score <= 60

    def test_calculate_second_board_score(self):
        """测试二板预期评分计算"""
        score = calculate_second_board_score(
            seal_strength=80,
            volume_match=70,
            theme_heat=90,
            board_type="换手"
        )
        assert 70 <= score <= 85

    def test_calculate_second_board_score_yizi(self):
        """测试一字板扣分"""
        score_normal = calculate_second_board_score(70, 70, 70, "换手")
        score_yizi = calculate_second_board_score(70, 70, 70, "一字")
        assert score_yizi < score_normal  # 一字板应该更低

    def test_calculate_second_board_score_market_emotion(self):
        """测试市场情绪权重调整"""
        # 情绪好 vs 情绪差，其他条件相同
        score_good = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="换手", market_emotion="高潮",
            circulation_mv=1e10, first_limit_time="09:45",
            theme_purity=70, historical_activity=70
        )
        score_bad = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="换手", market_emotion="冰点",
            circulation_mv=1e10, first_limit_time="09:45",
            theme_purity=70, historical_activity=70
        )
        assert score_good > score_bad

    def test_circulation_mv_threshold(self):
        """测试流通市值阈值调整"""
        # 小盘股（<50亿）
        score_small = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="换手", market_emotion="升温",
            circulation_mv=3e9, first_limit_time="09:45",
            theme_purity=70, historical_activity=70
        )
        # 大盘股（>200亿）
        score_large = calculate_second_board_score(
            seal_strength=70, volume_match=70, theme_heat=70,
            board_type="换手", market_emotion="升温",
            circulation_mv=3e10, first_limit_time="09:45",
            theme_purity=70, historical_activity=70
        )
        assert score_small > score_large

    def test_get_first_board_screen_returns_string(self):
        """测试主接口返回格式"""
        result = get_first_board_screen("2026-06-13", min_score=70)
        assert isinstance(result, str)
        assert "首板" in result or "二板" in result

    def test_get_first_board_screen_min_score_filter(self):
        """测试最低评分过滤"""
        result = get_first_board_screen("2026-06-13", min_score=90)
        assert isinstance(result, str)

    def test_seal_stability_optional(self):
        """测试封单稳定性为可选指标"""
        result = _get_seal_stability_from_intraday("000001")
        # 应该返回 float 或 None
        assert result is None or isinstance(result, float)
```

### 4.2 运行测试

```bash
python -m pytest tests/test_short_term_features.py::TestFirstBoardScreen -v
```

---

## 5. 验收标准

- [ ] `_get_first_board_stocks()` 正确筛选首板票（不含不可获取字段）
- [ ] `_calculate_theme_purity()` 评分合理
- [ ] `calculate_second_board_score()` 综合评分正确
- [ ] 流通市值阈值已调整（50亿/200亿）
- [ ] 市场情绪权重已调整（20%）
- [ ] `get_first_board_screen()` 返回完整报告
- [ ] 二板预期评分排序正确
- [ ] 异常情况处理完善
- [ ] 单元测试覆盖率 100%
- [ ] 限流走 `_em_get()`

## 6. 评审修正记录

| # | 原问题 | 修正方案 | 影响范围 |
|---|--------|----------|----------|
| 1 | 封单峰值不可获取 | 改用当前封单/流通盘比 | 封单强度指标 |
| 2 | 撤单次数不可获取 | 移除，改用封单稳定性（可选） | 封单稳定性 |
| 3 | 题材纯正度无量化方法 | 新增 `_calculate_theme_purity()` 四维度评分 | 题材纯正度 |
| 4 | 评分权重：市场情绪偏低 | 市场情绪从15%上调到20%，纯正度从10%下调到5% | 评分模型 |
| 5 | 流通市值阈值不合理 | 调整为50亿/200亿 | 市值调整 |
