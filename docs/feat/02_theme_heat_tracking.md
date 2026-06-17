# 功能2：题材热度追踪

## 1. 功能说明

### 1.1 核心价值

短线交易者的**第二决策依据**：这个题材炒了几天了？还有没有空间？还是该撤了？

### 1.2 解决的问题

| 现状 | 目标 |
|------|------|
| `get_concept_blocks` 只给个股所属概念 | 给出题材热度排名 |
| 没有题材启动时间 | 知道题材从哪天开始炒 |
| 没有题材持续性评估 | 判断题材处于哪个阶段 |

### 1.3 使用场景

```
场景1：盘前决策
  交易者查看题材热度 → 选择今日主攻方向

场景2：题材切换识别
  交易者追踪热度变化 → 识别新题材启动、旧题材退潮

场景3：持续性判断
  交易者查看题材持续天数 → 判断是否还有参与价值
```

---

## 2. 技术方案

### 2.0 ⚠️ 前置验证任务（Phase 0，同功能1）

> **问题**：涨停原因字段的归因精度问题。东财 `RPT_LIMITUP_STOCK` 的涨停原因字段是编辑人工标注的，
> 同一只票可能被归到多个原因，且同一概念可能有多个细分方向名称。

**验证步骤：**

```python
# 1. 采样分析涨停原因字段
def _analyze_limitup_reasons(trade_date: str) -> dict:
    """
    分析涨停原因字段的质量

    返回：
    {
        "total_stocks": int,
        "unique_reasons": int,         # 不同原因数量
        "reason_frequency": dict,      # 原因出现频率
        "multi_reason_stocks": int,    # 有多个原因的股票数
        "top_20_reasons": list[str],   # 前20个最常见原因
    }
    """
    pass

# 2. 构建原因归一化映射表
# 例如：
REASON_NORMALIZATION = {
    "人工智能": "AI",
    "AI": "AI",
    "大模型": "AI",
    "ChatGPT": "AI",
    "算力": "AI",
    "新能源": "新能源",
    "光伏": "新能源",
    "锂电池": "新能源",
    "储能": "新能源",
    # ... 手工维护 + 自动扩展
}
```

### 2.1 数据源分析

| 数据 | 来源 | 接口 | 说明 |
|------|------|------|------|
| 涨停股票 + 涨停原因 | 东财 datacenter | `RPT_LIMITUP_STOCK` | 每只涨停股的题材归因（需归一化） |
| 概念板块行情 | 东财 push2 | 板块列表接口 | 板块涨跌幅、成交额 |
| 历史涨停数据 | 东财 datacenter | `RPT_LIMITUP_STOCK` | 用于计算题材启动时间 |
| 北向资金流向 | 同花顺 hsgtApi | `get_northbound_flow()` | 题材资金验证 |

### 2.2 核心指标计算（实战版）

```python
# 题材热度指标（资深交易者视角）

1. 题材涨停家数
   - 按涨停原因聚合（归一化后）
   - 按涨停家数排名

2. 题材阶段判断（实战版）
   阶段定义：
   - 试探期（1-2天）：涨停家数2-5只，无连板
     * 特征：零星涨停，试探市场反应
     * 交易策略：不参与，观察

   - 发酵期（2-3天）：涨停家数5-10只，出现2板
     * 特征：资金开始认可，龙头初现
     * 交易策略：可以小仓位试错

   - 主升期（3-5天）：涨停家数>10只，连板梯队完整
     * 特征：龙头明确，补涨龙涌现
     * 交易策略：积极参与，做龙头或补涨龙

   - 高潮期（1-2天）：涨停家数达到峰值，后排也开始涨停
     * 特征：全面开花，但风险积累
     * 交易策略：兑现利润，不追高

   - 退潮期（2-3天）：涨停家数锐减，龙头开始分歧
     * 特征：分化加剧，后排开始亏钱
     * 交易策略：空仓或只做最强

   - 冰点期：涨停家数<3只，龙头断板
     * 特征：全面亏钱，资金撤退
     * 交易策略：空仓等待

3. 题材热度趋势（实战版）
   核心逻辑：
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #2：修改持续天数定义
   # 原问题：用"连续天数"不准确，题材可能"断一天再续"
   # 修正：用"近N日内出现涨停的天数"而非"连续天数"
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   - 看3日趋势，不是2日
     * 连续3天增加 → 升温
     * 连续3天减少 → 退潮
     * 先增后减 → 高潮转退潮

   - 结合龙头状态
     * 龙头封板 → 题材还有空间
     * 龙头分歧 → 题材可能见顶
     * 龙头断板 → 题材大概率结束

   - 结合梯队高度
     * 梯队高度提升 → 强势
     * 梯队高度下降 → 弱势

   - 特殊情况处理
     * 周五涨停少 → 不代表退潮（周末效应）
     * 节假日前涨停少 → 不代表退潮
     * 需要对比同周期（周一vs周一，周五vs周五）

   - 题材活跃天数（修正后定义）：
     * 近7日内有涨停的天数（不要求连续）
     * 例：近7天有5天出现涨停 → 活跃天数=5
     * 比"连续天数"更能反映题材的真实热度

4. 题材强度评分
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #3：调整热度评分权重
   # 原问题：龙头状态权重过低（10%），实战中龙头状态很关键
   # 修正：龙头状态权重提升到25%，涨停家数降到30%
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   - 涨停家数：30%（从40%下调）
   - 连板股数量：20%
   - 持续天数（活跃天数）：15%（从20%下调）
   - 龙头状态：25%（从10%上调）★关键修正★
   - 北向资金方向：10%（新增）

5. 题材博弈维度（新增）
   - 题材卡位识别
     * A题材退潮时，B题材启动
     * 需要识别这种切换

   - 题材接力识别
     * 同一概念的不同细分方向
     * 比如"人工智能"→"算力"→"应用"

   - 题材辨识度评估（核心指标，需要量化）

   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #4：补充辨识度量化方法
   # 原问题：文档提到辨识度评估但没给出具体实现
   # 修正：用多个代理变量量化辨识度
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   题材辨识度量化方法：
   - 涨停家数 >=10 → +30分
   - 有连板梯队（>=3板）→ +25分
   - 龙头封板状态 → +20分
   - 封单集中度（前3名封单占总封单比例）→ +15分
   - 北向资金流入该题材相关个股 → +10分
   - 总分 >=70 → 高辨识度
   - 总分 40-70 → 中辨识度
   - 总分 <40 → 低辨识度

   低辨识度特征：涨停<3只、无连板、无讨论

   - 题材持续性评估
     * 政策驱动型题材：持续性长（如新能源政策、AI政策）
     * 事件驱动型题材：持续性短（如某公司公告、某事件催化）
     * 消息驱动型题材：持续性中等（如行业数据发布）
     * 需要区分题材类型（通过涨停原因关键词判断）

6. 超龙头视角简化（核心改进）
   - 超龙头选手不关心题材阶段，只关心龙头还在不在
   - 只判断3件事：
     1. 龙头还在封板吗？
     2. 龙头还在提升吗？
     3. 有没有新龙头接力？
   - 龙头还在 → 题材还有空间
   - 龙头断板 → 题材结束
```

### 2.3 接口设计

```python
def get_theme_heat(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
    top_n: Annotated[int, "返回前N个题材, 默认10"] = 10,
) -> str:
    """
    题材热度排名 + 周期评估

    返回内容：
    1. 按涨停家数排名的概念板块（涨停原因归一化后）
    2. 每个板块内涨停股票列表
    3. 板块活跃天数（近N日内有涨停的天数）
    4. 板块热度趋势（升温/高潮/退潮）
    5. 题材辨识度评分
    6. 龙头状态

    数据源：东财 datacenter RPT_LIMITUP_STOCK
    限流：统一走 _em_get()
    """
```

---

## 3. 实现步骤

### Step 0：涨停原因归一化（Phase 0，必须先完成）

```python
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #1：新增涨停原因归一化
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REASON_NORMALIZATION_MAP = {
    # AI 相关
    "人工智能": "AI",
    "AI": "AI",
    "大模型": "AI",
    "ChatGPT": "AI",
    "算力": "AI",
    "AIGC": "AI",
    "机器人": "AI",
    "自动驾驶": "AI",

    # 新能源相关
    "新能源": "新能源",
    "光伏": "新能源",
    "锂电池": "新能源",
    "储能": "新能源",
    "风电": "新能源",

    # 军工相关
    "军工": "军工",
    "国防": "军工",
    "航天": "军工",

    # ... 可以从历史数据中自动扩展
}

def _normalize_theme_name(raw_reason: str) -> str:
    """
    将原始涨停原因归一化为标准题材名称

    逻辑：
    1. 精确匹配归一化表
    2. 模糊匹配（关键词包含）
    3. 匹配不到则保留原名

    例：
    "人工智能概念" → "AI"
    "ChatGPT概念股" → "AI"
    "新能源汽车" → "新能源"
    """
    # 精确匹配
    if raw_reason in REASON_NORMALIZATION_MAP:
        return REASON_NORMALIZATION_MAP[raw_reason]

    # 模糊匹配
    for keyword, normalized in REASON_NORMALIZATION_MAP.items():
        if keyword in raw_reason:
            return normalized

    return raw_reason

def _auto_expand_normalization_map(reasons: list[str]) -> dict:
    """
    自动扩展归一化映射表

    逻辑：
    1. 统计所有出现的涨停原因
    2. 找出相似的原因（编辑距离<3）
    3. 合并为同一归一化名称
    4. 人工确认后加入映射表
    """
    pass
```

### Step 1：数据获取层（a_stock.py）

```python
def _get_limitup_by_theme(trade_date: str) -> dict:
    """
    获取涨停股票按题材聚合（归一化后）

    返回：
    {
        "AI": [
            {"code": "000001", "name": "股票A", "board_num": 3, "first_limit_time": "09:35", "raw_reason": "人工智能概念"},
            {"code": "000002", "name": "股票B", "board_num": 1, "first_limit_time": "10:15", "raw_reason": "ChatGPT"},
        ],
        "新能源": [...],
    }

    注意：同一股票可能出现在多个题材中（如果有多条涨停原因）
    """
    # 1. 获取当日涨停列表（含涨停原因）
    # 2. 对涨停原因做归一化
    # 3. 按归一化后的题材聚合
    pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #2：修改题材历史热度获取逻辑
# 原问题：用"连续天数"不准确
# 修正：用"近N日内有涨停的天数"
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _get_theme_history(theme_name: str, days: int = 7) -> list[dict]:
    """
    获取某题材近N日涨停情况

    返回：
    [
        {"date": "2026-06-13", "count": 12, "highest_board": 5},
        {"date": "2026-06-12", "count": 8, "highest_board": 4},
        {"date": "2026-06-11", "count": 5, "highest_board": 3},
        {"date": "2026-06-10", "count": 0, "highest_board": 0},  # 该日无涨停
        {"date": "2026-06-09", "count": 3, "highest_board": 2},
    ]

    注意：
    - 返回所有日期（包括count=0的日期）
    - 用于计算"活跃天数"（count>0的天数）
    """
    # 查询近N日涨停数据，按题材筛选
    pass

def _get_theme_active_days(theme_history: list[dict]) -> int:
    """
    计算题材活跃天数

    逻辑：
    - 近N日内有涨停的天数（不要求连续）
    - 例：近7天有5天出现涨停 → 活跃天数=5
    """
    return sum(1 for day in theme_history if day["count"] > 0)

def _get_theme_start_date(theme_name: str) -> str:
    """
    获取题材启动日期

    逻辑：该题材首次出现>=3只涨停的日期
    """
    pass

def _get_theme_leader_status(theme_name: str) -> dict:
    """
    获取题材龙头状态

    返回：
    {
        "leader_code": "000001",
        "leader_board_num": 5,
        "leader_seal_status": "封板",  # 封板/分歧/断板
        "theme_purity": 85,            # 题材纯正度
    }
    """
    pass
```

### Step 2：指标计算层（a_stock.py）

```python
def _get_theme_phase(
    theme_name: str,
    history: list[dict],
    leader_status: dict,
) -> dict:
    """
    题材阶段判断（实战版）

    阶段定义：
    1. 试探期（1-2天）：涨停家数2-5只，无连板
    2. 发酵期（2-3天）：涨停家数5-10只，出现2板
    3. 主升期（3-5天）：涨停家数>10只，连板梯队完整
    4. 高潮期（1-2天）：涨停家数达到峰值，后排也开始涨停
    5. 退潮期（2-3天）：涨停家数锐减，龙头开始分歧
    6. 冰点期：涨停家数<3只，龙头断板

    判断依据：
    - 涨停家数趋势
    - 连板梯队高度
    - 龙头股状态
    """
    pass

def _calculate_theme_trend(
    history: list[dict],
    leader_status: str,
) -> dict:
    """
    题材热度趋势判断（实战版）

    核心逻辑：
    1. 看3日趋势，不是2日
    2. 结合龙头状态
    3. 结合梯队高度
    4. 特殊情况处理（周五/节假日）
    """
    pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #4：新增辨识度量化函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _calculate_theme_recognition_score(
    stock_count: int,
    highest_board: int,
    leader_seal_status: str,
    seal_concentration: float,
    northbound_inflow: bool,
) -> dict:
    """
    题材辨识度评分

    评分维度：
    1. 涨停家数 >=10 → +30分
    2. 有连板梯队（>=3板）→ +25分
    3. 龙头封板状态 → +20分
    4. 封单集中度 → +15分
    5. 北向资金流入 → +10分

    返回：
    {
        "score": float,           # 总分 0-100
        "level": str,             # 高辨识度/中辨识度/低辨识度
        "breakdown": dict,        # 各维度得分
    }
    """
    score = 0
    breakdown = {}

    # 1. 涨停家数
    if stock_count >= 10:
        breakdown["stock_count"] = 30
    elif stock_count >= 5:
        breakdown["stock_count"] = 15
    else:
        breakdown["stock_count"] = 5
    score += breakdown["stock_count"]

    # 2. 连板梯队
    if highest_board >= 3:
        breakdown["ladder"] = 25
    elif highest_board >= 2:
        breakdown["ladder"] = 15
    else:
        breakdown["ladder"] = 0
    score += breakdown["ladder"]

    # 3. 龙头封板状态
    if leader_seal_status == "封板":
        breakdown["leader"] = 20
    elif leader_seal_status == "分歧":
        breakdown["leader"] = 10
    else:
        breakdown["leader"] = 0
    score += breakdown["leader"]

    # 4. 封单集中度
    if seal_concentration > 0.5:
        breakdown["seal_concentration"] = 15
    elif seal_concentration > 0.3:
        breakdown["seal_concentration"] = 10
    else:
        breakdown["seal_concentration"] = 5
    score += breakdown["seal_concentration"]

    # 5. 北向资金
    if northbound_inflow:
        breakdown["northbound"] = 10
    else:
        breakdown["northbound"] = 0
    score += breakdown["northbound"]

    # 判断辨识度等级
    if score >= 70:
        level = "高辨识度"
    elif score >= 40:
        level = "中辨识度"
    else:
        level = "低辨识度"

    return {
        "score": score,
        "level": level,
        "breakdown": breakdown,
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #3：调整热度评分权重
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _calculate_heat_score(
    stock_count: int,
    highest_board: int,
    active_days: int,
    phase: str,
    leader_seal_status: str,
    northbound_direction: str,
) -> float:
    """
    热度评分计算（权重已调整）

    权重（修正后）：
    - 涨停家数：30%（从40%下调）
    - 最高连板：20%
    - 活跃天数（衰减）：15%（从20%下调）
    - 龙头状态：25%（从10%上调）★关键修正★
    - 北向资金方向：10%（新增）
    """
    # 各维度评分（0-100）
    stock_score = min(100, stock_count * 8)  # 12.5只=100分
    board_score = min(100, highest_board * 15)  # 6.7板=100分
    active_score = min(100, active_days * 15)  # 6.7天=100分

    # 龙头状态评分
    leader_score = 0
    if leader_seal_status == "封板":
        leader_score = 100
    elif leader_seal_status == "分歧":
        leader_score = 50
    else:
        leader_score = 0

    # 北向资金评分
    northbound_score = 0
    if northbound_direction == "大幅流入":
        northbound_score = 100
    elif northbound_direction == "小幅流入":
        northbound_score = 60
    elif northbound_direction == "小幅流出":
        northbound_score = 30
    else:
        northbound_score = 0

    # 加权计算
    heat_score = (
        stock_score * 0.30 +
        board_score * 0.20 +
        active_score * 0.15 +
        leader_score * 0.25 +
        northbound_score * 0.10
    )

    return round(heat_score, 1)

def _calculate_theme_metrics(
    theme_stocks: list[dict],
    theme_history: list[dict],
    start_date: str,
    theme_phase: dict,
    theme_trend: dict,
    leader_status: dict,
    recognition_score: dict,
) -> dict:
    """计算题材热度指标"""
    return {
        "theme_name": str,
        "stock_count": int,           # 今日涨停家数
        "stocks": list[dict],         # 涨停股票列表
        "start_date": str,            # 启动日期
        "active_days": int,           # 活跃天数（近7日内有涨停的天数）
        "phase": str,                 # 试探/发酵/主升/高潮/退潮/冰点
        "trend": str,                 # 升温/高潮/退潮
        "heat_score": float,          # 热度评分
        "recognition_score": dict,    # 辨识度评分（新增）
        "leader_status": dict,        # 龙头状态
        "trading_suggestion": str,    # 交易建议
    }

def judge_strong_bullish_theme(
    theme_name: str,
    theme_stock_count: int,
    leader_board_num: int,
    leader_seal_status: str,
    theme_active_days: int,
    deputy_leaders_count: int,
    recognition_score: float,
) -> dict:
    """
    强看好题材判断（超龙头硬核逻辑）

    核心逻辑：题材必须是"主线题材"

    条件1：涨停家数足够
      - 涨停家数 >=10
      - 或者涨停家数/全市场涨停 >30%

    条件2：有明确龙头
      - 龙头连板数 >=4
      - 龙头封板（未炸板）

    条件3：有梯队支撑
      - 有补涨龙（2-3板）
      - 有首板接力

    条件4：题材持续性
      - 活跃天数 >=3（近7日内有涨停的天数）
      - 涨停家数未明显下降

    条件5：辨识度高
      - 辨识度评分 >=70（新增）

    强看好信号：全部满足 → 主线题材，重仓参与
    """
    if theme_stock_count < 10:
        return {"strong_bullish": False, "reason": "涨停家数不足"}

    if leader_board_num < 4 or leader_seal_status != "封板":
        return {"strong_bullish": False, "reason": "龙头不够强"}

    if deputy_leaders_count < 2:
        return {"strong_bullish": False, "reason": "缺乏梯队支撑"}

    if theme_active_days < 3:
        return {"strong_bullish": False, "reason": "持续性不足"}

    if recognition_score < 70:
        return {"strong_bullish": False, "reason": "辨识度不足"}

    return {
        "strong_bullish": True,
        "reason": f"主线题材：{theme_name}",
        "action": "重仓参与龙头或补涨龙",
        "leader": f"龙头{leader_board_num}板",
    }

def judge_strong_bearish_theme(
    theme_name: str,
    theme_stock_count: int,
    leader_seal_status: str,
    theme_stock_count_change: float,
    yesterday_theme_avg_return: float,
) -> dict:
    """
    强看空题材判断（超龙头硬核逻辑）

    核心逻辑：题材见顶或退潮

    看空信号1：龙头分歧或断板
    看空信号2：涨停家数锐减（今日<昨日50%）
    看空信号3：后排亏钱（题材内昨日涨停今日平均跌幅>3%）

    强看空信号：任一条件满足 → 回避该题材
    """
    reasons = []

    if leader_seal_status in ["分歧", "断板"]:
        reasons.append("龙头分歧或断板")

    if theme_stock_count_change < -50:
        reasons.append("涨停家数锐减")

    if yesterday_theme_avg_return < -3:
        reasons.append("后排亏钱效应强")

    if reasons:
        return {
            "strong_bearish": True,
            "reason": " + ".join(reasons),
            "action": "回避该题材，不参与",
        }

    return {"strong_bearish": False, "reason": "无明显看空信号"}
```

### Step 3：对外接口（a_stock.py）

```python
def get_theme_heat(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
    top_n: Annotated[int, "返回前N个题材, 默认10"] = 10,
) -> str:
    """题材热度排名 + 周期评估"""
    pass
```

### Step 4：工具注册

```python
# signal_data_tools.py
@tool
def get_theme_heat(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
    top_n: Annotated[int, "返回前N个题材, 默认10"] = 10,
) -> str:
    """题材热度排名 + 周期评估"""
    return route_to_vendor("get_theme_heat", trade_date, top_n)

# interface.py
VENDOR_METHODS["get_theme_heat"] = {
    "a_stock": get_astock_theme_heat,
}
```

### Step 5：Agent 接入

```python
# short_term_analyst.py（新建的短线博弈分析师）
tools = [
    ...,
    get_theme_heat,  # 新增
]
```

---

## 4. 单元测试

### 4.1 测试文件

```python
# tests/test_short_term_features.py

class TestThemeHeatTracking:
    """题材热度追踪测试"""

    def test_normalize_theme_name(self):
        """测试涨停原因归一化"""
        assert _normalize_theme_name("人工智能概念") == "AI"
        assert _normalize_theme_name("ChatGPT概念股") == "AI"
        assert _normalize_theme_name("新能源汽车") == "新能源"
        assert _normalize_theme_name("锂电池") == "新能源"

    def test_get_limitup_by_theme(self):
        """测试涨停股票按题材聚合"""
        result = _get_limitup_by_theme("2026-06-13")
        assert isinstance(result, dict)
        # 每个题材应该有股票列表
        for theme, stocks in result.items():
            assert isinstance(stocks, list)
            if stocks:
                assert "code" in stocks[0]

    def test_get_theme_history(self):
        """测试题材历史热度"""
        result = _get_theme_history("AI", days=7)
        assert isinstance(result, list)
        assert len(result) == 7  # 应该返回所有日期
        if result:
            assert "date" in result[0]
            assert "count" in result[0]

    def test_get_theme_active_days(self):
        """测试活跃天数计算"""
        history = [
            {"date": "2026-06-13", "count": 12},
            {"date": "2026-06-12", "count": 8},
            {"date": "2026-06-11", "count": 5},
            {"date": "2026-06-10", "count": 0},  # 无涨停
            {"date": "2026-06-09", "count": 3},
            {"date": "2026-06-08", "count": 0},  # 无涨停
            {"date": "2026-06-07", "count": 1},
        ]
        active_days = _get_theme_active_days(history)
        assert active_days == 5  # 5天有涨停

    def test_calculate_theme_recognition_score(self):
        """测试辨识度评分"""
        result = _calculate_theme_recognition_score(
            stock_count=12,
            highest_board=5,
            leader_seal_status="封板",
            seal_concentration=0.6,
            northbound_inflow=True,
        )
        assert result["score"] >= 70
        assert result["level"] == "高辨识度"

    def test_calculate_heat_score_weights(self):
        """测试热度评分权重"""
        # 龙头封板 vs 龙头断板，其他条件相同
        score_sealed = _calculate_heat_score(
            stock_count=10, highest_board=5, active_days=5,
            phase="主升", leader_seal_status="封板", northbound_direction="小幅流入"
        )
        score_broken = _calculate_heat_score(
            stock_count=10, highest_board=5, active_days=5,
            phase="主升", leader_seal_status="断板", northbound_direction="小幅流入"
        )
        # 龙头封板应该明显高于断板
        assert score_sealed > score_broken + 20

    def test_calculate_trend_warming(self):
        """测试升温趋势判断"""
        history = [
            {"date": "2026-06-13", "count": 15},
            {"date": "2026-06-12", "count": 10},
        ]
        assert _calculate_trend(history) == "升温"

    def test_calculate_trend_cooling(self):
        """测试退潮趋势判断"""
        history = [
            {"date": "2026-06-13", "count": 5},
            {"date": "2026-06-12", "count": 10},
        ]
        assert _calculate_trend(history) == "退潮"

    def test_calculate_trend_peak(self):
        """测试高潮趋势判断"""
        history = [
            {"date": "2026-06-13", "count": 10},
            {"date": "2026-06-12", "count": 11},
        ]
        assert _calculate_trend(history) == "高潮"

    def test_get_theme_heat_returns_string(self):
        """测试主接口返回格式"""
        result = get_theme_heat("2026-06-13", top_n=5)
        assert isinstance(result, str)
        assert "题材" in result or "涨停" in result

    def test_get_theme_heat_top_n(self):
        """测试top_n参数"""
        result = get_theme_heat("2026-06-13", top_n=3)
        assert isinstance(result, str)
```

### 4.2 运行测试

```bash
python -m pytest tests/test_short_term_features.py::TestThemeHeatTracking -v
```

---

## 5. 验收标准

- [ ] Phase 0：涨停原因归一化映射表构建完成
- [ ] `_normalize_theme_name()` 正确归一化各类涨停原因
- [ ] `_get_limitup_by_theme()` 正确聚合涨停股票
- [ ] `_get_theme_history()` 返回题材历史热度（含count=0的日期）
- [ ] `_get_theme_active_days()` 正确计算活跃天数
- [ ] `_calculate_theme_recognition_score()` 辨识度评分合理
- [ ] `_calculate_heat_score()` 热度评分权重正确（龙头状态25%）
- [ ] `_calculate_trend()` 正确判断趋势
- [ ] `get_theme_heat()` 返回完整报告
- [ ] 异常情况处理完善
- [ ] 单元测试覆盖率 100%
- [ ] 限流走 `_em_get()`

## 6. 评审修正记录

| # | 原问题 | 修正方案 | 影响范围 |
|---|--------|----------|----------|
| 1 | 涨停原因归因精度差 | 新增 `_normalize_theme_name()` 归一化 | 数据预处理 |
| 2 | 题材持续天数定义不准确 | 改用"活跃天数"（近N日内有涨停的天数） | 题材阶段判断 |
| 3 | 龙头状态权重过低（10%） | 提升到25%，涨停家数降到30% | 热度评分 |
| 4 | 辨识度评估无量化方法 | 新增 `_calculate_theme_recognition_score()` 五维度评分 | 辨识度评估 |
