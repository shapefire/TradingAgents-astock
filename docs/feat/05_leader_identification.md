# 功能5：龙头识别 + 卡位分析

## 1. 功能说明

### 1.1 核心价值

短线交易者的**博弈核心**：这只票是真龙头还是假龙头？有没有卡位的？补涨龙是谁？

### 1.2 解决的问题

| 现状 | 目标 |
|------|------|
| 龙虎榜只给当日席位 | 识别真龙头/假龙头 |
| 没有同题材竞争分析 | 发现卡位/补涨关系 |
| 没有席位风格画像 | 识别游资操作风格 |

### 1.3 使用场景

```
场景1：龙头识别
  交易者在同题材多只涨停股中 → 识别谁是真龙头 → 聚焦龙头

场景2：卡位识别
  交易者发现新的强势股 → 判断是否在卡位龙头 → 决定是否切换

场景3：补涨龙挖掘
  龙头已高位 → 挖掘同题材低位补涨龙 → 低吸或打首板
```

---

## 2. 技术方案

### 2.1 数据源分析

| 数据 | 来源 | 接口 | 说明 |
|------|------|------|------|
| 涨停股票列表 | 东财 datacenter | `RPT_LIMITUP_STOCK` | 连板天数、涨停时间 |
| 个股行情 | 东财 push2 | 实时行情 | 封单量、成交额 |
| 龙虎榜席位 | 东财 datacenter | `RPT_DAILYBILLBOARD` | 买卖席位明细 |
| 游资席位库 | 东财 datacenter | 席位统计 | 游资历史操作 |

### 2.2 核心指标计算（实战版）

```python
# 龙头识别指标（资深交易者视角）

1. 连板高度（权重35%）
   - 连板天数最高
   - 市场最高板 = 高度标
   - 最高板=龙头（绝对高度）

2. 首板时间（权重15%，⚠️ 从20%下调）
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #2：调整首板时间权重
   # 原问题：首板时间只在同板数比较时有意义，跨板数比较无意义
   # 修正：权重从20%下调到15%，且只在同板数内部比较
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   - 谁最先涨停（同板数比较）
   - 首板时间越早，龙头地位越强
   - 9:30-9:35涨停：秒板（最强）
   - 9:35-10:00涨停：早盘强封
   - 10:00后涨停：相对弱

3. 封单强度（权重25%，⚠️ 从20%上调）
   - 封单金额
   - 封单/流通盘比
   - 封单强度 = 封单金额 / 流通市值

4. 题材纯正度（权重15%）
   - 主营业务与题材的关联度
   - 是否为题材内最纯正标的

5. 市场认可度（权重10%）
   - 同题材涨停家数
   - 题材内排名
   - 是否有卡位竞争者

特殊加成：
- 市场最高板：+10分
- 首板时间最早（同板数内）：+5分
- 连续一字板：+5分（但有风险）

特殊扣分：
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #1：调整流通市值扣分阈值
# 原问题：>100亿扣5分太严格，很多市场龙头流通市值都很大
# 修正：改为>200亿才扣分，且仅在同板数比较时
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 流通市值>200亿：-5分（⚠️ 从100亿上调）（大船难掉头）
- 历史经常炸板：-5分（股性不好）

# 卡位分析指标（实战版）

1. 卡位定义
   同题材、同板数或低一板的股票，封单强度超过龙头，或分时走势强于龙头。

2. 卡位类型
   - 强卡位（高威胁）
     * 同板数，封单强度>龙头
     * 涨停时间早于龙头
     * 市场开始讨论"新龙头"

   - 弱卡位（低威胁）
     * 低一板，封单强度接近龙头
     * 涨停时间晚于龙头
     * 只是跟风

   - 补涨（非卡位）
     * 低位票涨停，但不威胁龙头地位
     * 龙头还在封板

3. 卡位时机
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #3：调整卡位阈值
   # 原问题：卡位票封单/龙头封单>1.5才算强卡位太严格
   # 修正：龙头分歧时降低阈值
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   - 龙头分歧时卡位 → 真卡位（阈值降低）
   - 龙头封死时卡位 → 只是跟风

4. 卡位强度评估（修正后）
   - 龙头封板状态好时：
     * 卡位票封单/龙头封单 >1.5 → 强卡位
     * 卡位票封单/龙头封单 1-1.5 → 中卡位
     * 卡位票封单/龙头封单 <1 → 弱卡位

   - 龙头分歧时：
     * 卡位票封单/龙头封单 >1.2 → 强卡位（⚠️ 阈值降低）
     * 卡位票封单/龙头封单 0.8-1.2 → 中卡位
     * 卡位票封单/龙头封单 <0.8 → 弱卡位

# 补涨龙识别指标（实战版）

1. 补涨龙定义
   当龙头高位（>=4板⚠️ 从5板下调），同题材低位票开始补涨，可能是补涨龙。

2. 补涨龙条件
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   # 📌 评审修正 #4：放宽补涨龙启动条件
   # 原问题：要求龙头>=5板才考虑补涨龙，太严格
   # 修正：降为>=4板，且龙头处于分歧状态
   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   - 龙头连板数 >=4（⚠️ 从5下调）
   - 龙头处于分歧状态（⚠️ 新增条件）
   - 同题材、同主营业务
   - 连板数 1-2板（低位）
   - 封单强度高（>3%）
   - 流通市值 < 龙头（小盘更容易封）

3. 补涨龙空间评估
   - 补涨龙理论高度 = 龙头高度 - 2
     * 龙头5板 → 补涨龙最高3板
     * 龙头7板 → 补涨龙最高5板

4. 补涨龙时机
   - 龙头高位震荡时启动 → 好时机
   - 龙头断板后启动 → 可能是新龙头，不是补涨

5. 补涨龙风险
   - 龙头断板 → 补涨龙可能跟着断
   - 市场情绪转差 → 补涨龙先死

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #5：新增补涨龙vs新龙头区分方法
# 原问题：文档提到"龙头断板后启动的可能是新龙头，不是补涨"，但没给出区分标准
# 修正：新增区分逻辑
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. 补涨龙 vs 新龙头 区分方法
   补涨龙特征（同时满足）：
   - 龙头还在（未断板，可能分歧）
   - 低位票在龙头分歧时启动
   - 低位票连板数 <= 龙头 - 2
   - 低位票与龙头同题材

   新龙头特征（同时满足）：
   - 龙头已断板
   - 新票在龙头断板后启动
   - 新票连板数 >= 龙头 - 1
   - 新票可能是不同题材（新方向）

   超龙头选手策略：
   - 补涨龙 → 可以参与，但空间有限（龙头高度-2）
   - 新龙头 → 重点关注，可能是新周期的开始

7. 超龙头视角简化（核心改进）
   - 龙头识别简化为3点：
     1. 连板高度最高
     2. 封单最强
     3. 市场认可度最高
   - 不需要复杂的多因子评分
   - 3秒判断：最高板+封单最强=龙头

8. 真假卡位判断（核心改进）
   - 真卡位条件（必须同时满足）：
     1. 龙头分歧或断板
     2. 卡位股封单强度 > 龙头
     3. 卡位股涨停时间早于龙头（同板数内）
     4. 卡位股连板数 >= 龙头 - 1
   - 假卡位特征：
     1. 龙头还在封板
     2. 卡位股只是跟风
     3. 卡位股连板数比龙头低很多
   - 超龙头选手只做真卡位，忽略假卡位
```

### 2.3 接口设计

```python
def get_leader_identification(
    ticker: Annotated[str, "A-stock code (e.g. 000001)"],
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
) -> str:
    """
    龙头识别 + 卡位分析

    返回内容：
    1. 该股是否为龙头判断
    2. 同题材竞争者列表
    3. 卡位风险评估（含龙头封板状态对阈值的影响）
    4. 补涨龙候选列表（含补涨龙vs新龙头区分）
    5. 游资席位分析（如有龙虎榜数据）

    数据源：东财 datacenter + push2
    限流：统一走 _em_get()
    """
```

---

## 3. 实现步骤

### Step 1：数据获取层（a_stock.py）

```python
def _get_same_theme_stocks(
    code: str,
    trade_date: str,
) -> list[dict]:
    """
    获取同题材股票列表

    逻辑：
    1. 获取目标股票的概念板块
    2. 获取同板块所有涨停股
    3. 按连板天数、涨停时间排序
    """
    pass

def _get_leader_candidates(
    trade_date: str,
) -> list[dict]:
    """
    获取龙头候选列表

    逻辑：
    1. 获取所有涨停股
    2. 按连板天数分组
    3. 每组内按涨停时间排序
    4. 返回各题材的龙头候选
    """
    pass

def _get_stock_billboard(code: str, trade_date: str) -> list[dict]:
    """
    获取个股龙虎榜席位

    返回：
    [
        {"name": "机构专用", "buy": 50000000, "sell": 0},
        {"name": "华泰证券深圳益田路", "buy": 30000000, "sell": 5000000},
    ]
    """
    pass
```

### Step 2：指标计算层（a_stock.py）

```python
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #1 #2：调整权重和阈值
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _calculate_leader_score(
    board_num: int,
    first_limit_time: str,
    seal_strength: float,
    theme_purity: float,
    theme_stocks_count: int,
    rank_in_theme: int,
    historical_limitup_count: int,
    circulation_mv: float,
) -> dict:
    """
    龙头评分（修正版）

    核心因子及权重（修正后）：
    1. 连板高度：35%
       - 最高板=龙头（绝对高度）
       - 同板数内比较其他因子

    2. 首板时间：15%（⚠️ 从20%下调）
       - 9:30-9:35涨停：100分（秒板）
       - 9:35-9:45涨停：90分
       - 9:45-10:00涨停：80分
       - 10:00-10:30涨停：70分
       - 10:30后涨停：60分
       - 注意：首板时间只在同板数内部比较时使用

    3. 封单强度：25%（⚠️ 从20%上调）
       - 封单/流通盘比

    4. 题材纯正度：15%
       - 主营业务与题材的关联度

    5. 市场认可度：10%
       - 同题材涨停家数
       - 题材内排名

    特殊加成：
    - 市场最高板：+10分
    - 首板时间最早（同板数内）：+5分
    - 连续一字板：+5分（但有风险）

    特殊扣分：
    - 流通市值>200亿：-5分（⚠️ 从100亿上调）
    - 历史经常炸板：-5分（股性不好）
    """
    pass

def _calculate_time_score(limit_time: str) -> float:
    """
    计算涨停时间评分

    逻辑：
    - 9:30-9:35 涨停：100分（秒板）
    - 9:35-9:45 涨停：90分
    - 9:45-10:00 涨停：80分
    - 10:00-10:30 涨停：70分
    - 10:30-13:00 涨停：60分
    - 13:00后涨停：50分
    """
    pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #3：卡位识别阈值修正
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _identify_card_position(
    leader_code: str,
    leader_board_num: int,
    leader_seal_strength: float,
    leader_seal_status: str,          # 新增：龙头封板状态
    same_theme_stocks: list[dict],
    market_emotion: str,
) -> list[dict]:
    """
    识别卡位关系（修正版）

    卡位定义：
    同题材、同板数或低一板的股票，封单强度超过龙头，或分时走势强于龙头。

    卡位类型：
    1. 强卡位（高威胁）
    2. 弱卡位（低威胁）
    3. 补涨（非卡位）

    卡位时机：
    - 龙头分歧时卡位 → 真卡位（阈值降低）
    - 龙头封死时卡位 → 只是跟风

    卡位强度评估（修正后）：
    - 龙头封板状态好时：
      * 卡位票封单/龙头封单 >1.5 → 强卡位
      * 1-1.5 → 中卡位
      * <1 → 弱卡位

    - 龙头分歧时（⚠️ 阈值降低）：
      * 卡位票封单/龙头封单 >1.2 → 强卡位
      * 0.8-1.2 → 中卡位
      * <0.8 → 弱卡位
    """
    results = []

    for stock in same_theme_stocks:
        if stock["code"] == leader_code:
            continue

        # 计算封单强度比
        seal_ratio = stock["seal_strength"] / leader_seal_strength if leader_seal_strength > 0 else 0

        # 根据龙头封板状态调整阈值
        if leader_seal_status == "封板":
            # 龙头封板状态好，阈值高
            if seal_ratio > 1.5:
                card_type = "强卡位"
            elif seal_ratio > 1.0:
                card_type = "中卡位"
            else:
                card_type = "弱卡位"
        else:
            # 龙头分歧，阈值降低
            if seal_ratio > 1.2:
                card_type = "强卡位"
            elif seal_ratio > 0.8:
                card_type = "中卡位"
            else:
                card_type = "弱卡位"

        results.append({
            "code": stock["code"],
            "name": stock["name"],
            "board_num": stock["board_num"],
            "seal_strength": stock["seal_strength"],
            "seal_ratio_to_leader": round(seal_ratio, 2),
            "card_type": card_type,
        })

    return results

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #4：放宽补涨龙条件
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _identify_deputy_leader(
    leader_code: str,
    leader_board_num: int,
    leader_seal_status: str,          # 新增：龙头封板状态
    leader_circulation_mv: float,
    same_theme_stocks: list[dict],
    market_emotion: str,
) -> list[dict]:
    """
    识别补涨龙（修正版）

    补涨龙定义：
    当龙头高位（>=4板⚠️ 从5下调），同题材低位票开始补涨，可能是补涨龙。

    补涨龙条件（修正后）：
    1. 龙头连板数 >=4（⚠️ 从5下调）
    2. 龙头处于分歧状态（⚠️ 新增条件）
    3. 同题材、同主营业务
    4. 连板数 1-2板（低位）
    5. 封单强度高（>3%）
    6. 流通市值 < 龙头（小盘更容易封）

    补涨龙空间评估：
    - 补涨龙理论高度 = 龙头高度 - 2

    补涨龙时机：
    - 龙头高位震荡时启动 → 好时机
    - 龙头断板后启动 → 可能是新龙头，不是补涨
    """
    results = []

    # 条件1：龙头连板数>=4
    if leader_board_num < 4:
        return results

    # 条件2：龙头处于分歧状态
    if leader_seal_status == "封板":
        return results  # 龙头还在封板，不需要补涨

    for stock in same_theme_stocks:
        if stock["code"] == leader_code:
            continue

        # 条件3-6
        if stock["board_num"] <= 2 and stock.get("seal_strength", 0) > 3:
            if stock["circulation_mv"] < leader_circulation_mv:
                results.append({
                    "code": stock["code"],
                    "name": stock["name"],
                    "board_num": stock["board_num"],
                    "seal_strength": stock["seal_strength"],
                    "theoretical_height": leader_board_num - 2,
                    "is_possible_new_leader": False,
                })

    return results

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 评审修正 #5：新增补涨龙vs新龙头区分
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _distinguish_deputy_vs_new_leader(
    leader_code: str,
    leader_board_num: int,
    leader_seal_status: str,
    candidate_code: str,
    candidate_board_num: int,
    candidate_theme: str,
    leader_theme: str,
) -> dict:
    """
    区分补涨龙 vs 新龙头

    补涨龙特征（同时满足）：
    - 龙头还在（未断板，可能分歧）
    - 低位票在龙头分歧时启动
    - 低位票连板数 <= 龙头 - 2
    - 低位票与龙头同题材

    新龙头特征（同时满足）：
    - 龙头已断板
    - 新票在龙头断板后启动
    - 新票连板数 >= 龙头 - 1
    - 新票可能是不同题材（新方向）

    返回：
    {
        "type": "deputy_leader" | "new_leader" | "uncertain",
        "confidence": float,  # 0-1
        "reason": str,
    }
    """
    # 新龙头特征
    if leader_seal_status == "断板":
        if candidate_board_num >= leader_board_num - 1:
            return {
                "type": "new_leader",
                "confidence": 0.8,
                "reason": f"龙头断板后，{candidate_code}连板数{candidate_board_num}板，可能是新龙头",
            }

    # 补涨龙特征
    if leader_seal_status in ["分歧", "封板"]:
        if candidate_board_num <= leader_board_num - 2:
            if candidate_theme == leader_theme:
                return {
                    "type": "deputy_leader",
                    "confidence": 0.7,
                    "reason": f"龙头{leader_seal_status}，{candidate_code}低位补涨",
                }

    return {
        "type": "uncertain",
        "confidence": 0.3,
        "reason": "无法明确判断",
    }

def judge_strong_bullish_leader(
    board_num: int,
    first_limit_time: str,
    seal_strength: float,
    theme_stock_count: int,
    theme_active_days: int,
    is_market_highest: bool,
) -> dict:
    """
    强看好龙头判断（超龙头硬核逻辑）

    核心逻辑：必须是"市场公认龙头"

    条件1：高度最高（连板数是同题材最高）
    条件2：封单最强（封单/流通盘>5%）
    条件3：时间最早（同板数内最早）
    条件4：题材支撑（涨停家数>=10，活跃天数>=3）

    强看好信号：全部满足 → 龙头确认，重仓参与
    """
    if board_num < 4:
        return {"strong_bullish": False, "reason": "高度不够"}

    if seal_strength < 5:
        return {"strong_bullish": False, "reason": "封单不够强"}

    if first_limit_time >= "10:00":
        return {"strong_bullish": False, "reason": "涨停时间太晚"}

    if theme_stock_count < 10:
        return {"strong_bullish": False, "reason": "题材不够强"}

    if theme_active_days < 3:
        return {"strong_bullish": False, "reason": "题材持续性不足"}

    return {
        "strong_bullish": True,
        "reason": f"市场龙头{board_num}板 + 封单强 + 题材强",
        "action": "龙头确认，重仓参与",
        "target": f"{board_num + 1}板",
    }

def judge_strong_bearish_leader(
    board_num: int,
    seal_status: str,
    seal_strength: float,
    theme_stock_count: int,
    card_position_code: str,
    card_position_seal_status: str,
) -> dict:
    """
    强看空龙头判断（超龙头硬核逻辑）

    核心逻辑：龙头出现"致命危险"

    看空信号1：龙头断板
    看空信号2：龙头分歧 + 卡位出现
    看空信号3：题材崩塌
    看空信号4：封单崩溃

    强看空信号：任一条件满足 → 回避该龙头
    """
    reasons = []

    if seal_status == "断板":
        reasons.append("龙头断板（最强看空信号）")

    if seal_status == "分歧" and card_position_code and card_position_seal_status == "封板":
        reasons.append("龙头分歧 + 卡位出现")

    if theme_stock_count < 5:
        reasons.append("题材涨停家数不足")

    if seal_strength < 1:
        reasons.append("封单崩溃")

    if reasons:
        return {
            "strong_bearish": True,
            "reason": " + ".join(reasons),
            "action": "回避该龙头，等待新龙头",
        }

    return {"strong_bearish": False, "reason": "无明显看空信号"}

def judge_card_position_outcome(
    leader_seal_status: str,
    card_seal_status: str,
    leader_board_num: int,
    card_board_num: int,
    leader_seal_strength: float,
    card_seal_strength: float,
) -> dict:
    """
    卡位结果判断（超龙头硬核逻辑）

    强看好卡位（卡位成功）：
      - 龙头断板
      - 卡位股封板
      - 卡位股连板数 >= 龙头 - 1
      - 卡位股封单 > 龙头

    强看空卡位（卡位失败）：
      - 龙头回封
      - 卡位股炸板
      - 卡位股连板数 < 龙头 - 2

    超龙头选手只在卡位成功后跟随新龙头
    """
    # 卡位成功条件
    if leader_seal_status == "断板" and card_seal_status == "封板":
        if card_board_num >= leader_board_num - 1 and card_seal_strength > leader_seal_strength:
            return {
                "card_success": True,
                "reason": "龙头断板 + 卡位股封板 + 连板数够",
                "action": "跟随新龙头",
                "new_leader": card_board_num,
            }

    # 卡位失败条件
    if leader_seal_status == "封板" and card_seal_status == "断板":
        return {
            "card_success": False,
            "reason": "龙头回封 + 卡位股断板",
            "action": "继续跟随原龙头",
        }

    if leader_seal_status == "断板" and card_seal_status == "断板":
        return {
            "card_success": False,
            "reason": "双龙断板，情绪崩塌",
            "action": "空仓观望",
        }

    return {"card_success": False, "reason": "卡位进行中，等待结果"}
```

### Step 3：对外接口（a_stock.py）

```python
def get_leader_identification(
    ticker: Annotated[str, "A-stock code (e.g. 000001)"],
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
) -> str:
    """龙头识别 + 卡位分析"""
    pass
```

### Step 4：工具注册

```python
# signal_data_tools.py
@tool
def get_leader_identification(
    ticker: Annotated[str, "A-stock code (e.g. 000001)"],
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
) -> str:
    """龙头识别 + 卡位分析"""
    return route_to_vendor("get_leader_identification", ticker, trade_date)

# interface.py
VENDOR_METHODS["get_leader_identification"] = {
    "a_stock": get_astock_leader_identification,
}
```

### Step 5：Agent 接入

```python
# short_term_analyst.py（新建的短线博弈分析师）
tools = [
    ...,
    get_leader_identification,  # 新增
]
```

---

## 4. 单元测试

### 4.1 测试文件

```python
# tests/test_short_term_features.py

class TestLeaderIdentification:
    """龙头识别测试"""

    def test_get_same_theme_stocks(self):
        """测试获取同题材股票"""
        result = _get_same_theme_stocks("000001", "2026-06-13")
        assert isinstance(result, list)
        if result:
            assert "board_num" in result[0]

    def test_calculate_leader_score_high(self):
        """测试龙头评分 - 高分"""
        score = _calculate_leader_score(
            board_num=5,
            first_limit_time="09:30",
            seal_strength=0.05,
            theme_purity=90
        )
        assert 70 <= score <= 100

    def test_calculate_leader_score_low(self):
        """测试龙头评分 - 低分"""
        score = _calculate_leader_score(
            board_num=1,
            first_limit_time="14:00",
            seal_strength=0.01,
            theme_purity=50
        )
        assert 20 <= score <= 50

    def test_calculate_time_score_early(self):
        """测试时间评分 - 早盘"""
        score = _calculate_time_score("09:30")
        assert score == 100

    def test_calculate_time_score_late(self):
        """测试时间评分 - 尾盘"""
        score = _calculate_time_score("14:30")
        assert score == 50

    def test_identify_card_position_leader_sealed(self):
        """测试卡位识别 - 龙头封板时阈值高"""
        same_theme = [
            {"code": "000001", "board_num": 3, "seal_strength": 0.03, "first_limit_time": "09:35"},
            {"code": "000002", "board_num": 3, "seal_strength": 0.05, "first_limit_time": "09:40"},
        ]
        result = _identify_card_position("000001", 3, 0.03, "封板", same_theme, "升温")
        # 000002封单是000001的1.67倍，龙头封板时>1.5才是强卡位
        assert any(r["card_type"] == "强卡位" for r in result)

    def test_identify_card_position_leader_divergence(self):
        """测试卡位识别 - 龙头分歧时阈值低"""
        same_theme = [
            {"code": "000001", "board_num": 3, "seal_strength": 0.03, "first_limit_time": "09:35"},
            {"code": "000002", "board_num": 3, "seal_strength": 0.04, "first_limit_time": "09:40"},
        ]
        result = _identify_card_position("000001", 3, 0.03, "分歧", same_theme, "升温")
        # 000002封单是000001的1.33倍，龙头分歧时>1.2就是强卡位
        assert any(r["card_type"] == "强卡位" for r in result)

    def test_identify_deputy_leader_conditions(self):
        """测试补涨龙识别条件"""
        same_theme = [
            {"code": "000002", "board_num": 1, "seal_strength": 0.04, "theme_purity": 85, "circulation_mv": 3e9},
            {"code": "000003", "board_num": 2, "seal_strength": 0.03, "theme_purity": 70, "circulation_mv": 5e9},
        ]
        # 龙头>=4板且分歧时才启动补涨龙
        result = _identify_deputy_leader("000001", 5, "分歧", 1e10, same_theme, "升温")
        assert len(result) > 0

    def test_identify_deputy_leader_no_start(self):
        """测试补涨龙不启动的情况"""
        same_theme = [
            {"code": "000002", "board_num": 1, "seal_strength": 0.04, "theme_purity": 85, "circulation_mv": 3e9},
        ]
        # 龙头还在封板，不需要补涨
        result = _identify_deputy_leader("000001", 5, "封板", 1e10, same_theme, "升温")
        assert len(result) == 0

    def test_distinguish_deputy_vs_new_leader(self):
        """测试补涨龙vs新龙头区分"""
        # 龙头断板，新票连板数>=龙头-1 → 新龙头
        result = _distinguish_deputy_vs_new_leader(
            "000001", 5, "断板", "000002", 4, "AI", "AI"
        )
        assert result["type"] == "new_leader"

        # 龙头分歧，低位票补涨 → 补涨龙
        result = _distinguish_deputy_vs_new_leader(
            "000001", 5, "分歧", "000002", 2, "AI", "AI"
        )
        assert result["type"] == "deputy_leader"

    def test_get_leader_identification_returns_string(self):
        """测试主接口返回格式"""
        result = get_leader_identification("000001", "2026-06-13")
        assert isinstance(result, str)
        assert "龙头" in result or "题材" in result

    def test_get_leader_identification_no_data(self):
        """测试无数据情况"""
        result = get_leader_identification("999999", "2026-06-13")
        assert isinstance(result, str)
```

### 4.2 运行测试

```bash
python -m pytest tests/test_short_term_features.py::TestLeaderIdentification -v
```

---

## 5. 验收标准

- [ ] `_get_same_theme_stocks()` 正确获取同题材股票
- [ ] `_calculate_leader_score()` 评分合理（流通市值阈值已调整）
- [ ] `_calculate_time_score()` 时间评分正确
- [ ] `_identify_card_position()` 卡位识别准确（含龙头状态对阈值的影响）
- [ ] `_identify_deputy_leader()` 补涨龙识别准确（条件已放宽）
- [ ] `_distinguish_deputy_vs_new_leader()` 区分补涨龙vs新龙头
- [ ] `get_leader_identification()` 返回完整报告
- [ ] 异常情况处理完善
- [ ] 单元测试覆盖率 100%
- [ ] 限流走 `_em_get()`

## 6. 评审修正记录

| # | 原问题 | 修正方案 | 影响范围 |
|---|--------|----------|----------|
| 1 | 流通市值扣分阈值过低（>100亿） | 改为>200亿才扣分 | 龙头评分 |
| 2 | 首板时间权重偏高（20%）且跨板数比较无意义 | 下调到15%，只在同板数内部比较 | 龙头评分 |
| 3 | 卡位阈值过严格（>1.5） | 龙头分歧时降低阈值到>1.2 | 卡位识别 |
| 4 | 补涨龙条件过严格（>=5板） | 放宽到>=4板，且需龙头分歧 | 补涨龙识别 |
| 5 | 缺少补涨龙vs新龙头区分方法 | 新增 `_distinguish_deputy_vs_new_leader()` | 补涨龙识别 |
