# Phase 0 接口验证报告

## 验证时间
- 日期: 2026-06-15
- 验证日期: 2026-06-13 (交易日)

## 验证结果汇总

| 接口 | 状态 | 可用性 | 备注 |
|------|------|--------|------|
| 东财 RPT_LIMITUP_STOCK | ❌ | 不可用 | 接口已变更，返回参数错误 |
| 东财 dataapi/xuangu/list | ✅ | 可用 | 涨跌幅>=9.9%筛选涨停股 |
| 同花顺 getharden | ✅ | 可用 | 涨停原因数据 |
| mootdx K线 | ✅ | 可用 | 可判断涨停和计算连板天数 |
| 东财 push2 | ⚠️ | 部分可用 | 连接不稳定 |

## 详细验证结果

### 1. 东财 RPT_LIMITUP_STOCK 接口

**状态**: ❌ 不可用

**错误信息**: `报表配置不存在,RPT_LIMITUP_STOCK`

**结论**: 该接口已变更或下线，无法使用。

### 2. 东财选股接口 (dataapi/xuangu/list)

**状态**: ✅ 可用

**接口地址**: `https://data.eastmoney.com/dataapi/xuangu/list`

**请求参数**:
```python
params = {
    'st': 'CHANGE_RATE',
    'sr': '-1',
    'ps': '10',
    'p': '1',
    'sty': 'SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,CHANGE_RATE,NEW_PRICE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,VOLUME_RATIO,TURNOVERRATE,PE9,TOTAL_MARKET_CAP,FREE_CAP,DEAL_AMOUNT',
    'filter': '(CHANGE_RATE>=9.9)',
}
```

**可用字段**:
| 字段 | 说明 | 样本值 |
|------|------|--------|
| SECUCODE | 证券代码 | 920126.BJ |
| SECURITY_CODE | 股票代码 | 920126 |
| SECURITY_NAME_ABBR | 股票简称 | 永大股份 |
| CHANGE_RATE | 涨跌幅 | 126.96 |
| NEW_PRICE | 最新价 | 17.68 |
| OPEN_PRICE | 开盘价 | 19.01 |
| HIGH_PRICE | 最高价 | 23.11 |
| LOW_PRICE | 最低价 | 17.56 |
| VOLUME_RATIO | 量比 | - |
| TURNOVERRATE | 换手率 | 85.01 |
| PE9 | 市盈率 | 31.41 |
| TOTAL_MARKET_CAP | 总市值 | 3289894400 |
| FREE_CAP | 流通市值 | 789730240 |
| DEAL_AMOUNT | 成交额 | 749364696.04 |
| MAX_TRADE_DATE | 交易日期 | 2026-06-15 |

**缺失字段**:
- ❌ CONTINUOUS_LIMIT_NUM (连板天数)
- ❌ LIMIT_UP_REASON (涨停原因)
- ❌ FIRST_LIMIT_TIME (首次涨停时间)
- ❌ LAST_LIMIT_TIME (最后涨停时间)
- ❌ OPEN_TIMES (开板次数)
- ❌ LIMIT_UP_TYPE (涨停类型)

### 3. 同花顺 getharden 接口

**状态**: ✅ 可用

**接口地址**: `http://zx.10jqka.com.cn/event/api/getharden/date/{date}/orderby/date/orderway/desc/charset/GBK/`

**可用字段**:
| 字段 | 说明 | 样本值 |
|------|------|--------|
| id | 记录ID | 90288930 |
| name | 股票名称 | 中远海能 |
| code | 股票代码 | 600026 |
| reason | 涨停原因 | LNG运输+一季报增长+央企 |
| date | 交易日期 | 2026-06-15 |
| market | 市场 | 17 |

**数据质量**:
- 返回 160 条涨停记录
- 涨停原因格式: `原因1+原因2+原因3` (多值用+分隔)
- 需要进行归一化处理

### 4. mootdx K线接口

**状态**: ✅ 可用

**功能**:
- ✅ 可判断股票是否涨停
- ✅ 可计算连板天数
- ✅ 可获取历史K线数据

**涨停判断逻辑**:
```python
# 涨停价 = 前收盘 * 1.1 (四舍五入到分)
limit_up_price = round(prev_close * 1.1, 2)
is_limit_up = abs(current_close - limit_up_price) < 0.01
```

**连板天数计算**:
```python
# 从当日往前追溯，连续涨停的天数
consecutive_days = 0
for i in range(len(kdata)-1, 0, -1):
    prev = kdata['close'].iloc[i-1]
    curr = kdata['close'].iloc[i]
    limit_price = round(prev * 1.1, 2)
    if abs(curr - limit_price) < 0.01:
        consecutive_days += 1
    else:
        break
```

## 推荐实现方案

### 数据源组合

| 数据 | 来源 | 说明 |
|------|------|------|
| 涨停股列表 | 同花顺 getharden | 获取涨停原因 |
| 涨停判断 | mootdx K线 | 判断是否涨停 |
| 连板天数 | mootdx K线 | 计算连板天数 |
| 基础行情 | 东财选股接口 | 获取市值、换手率等 |

### 实现步骤

1. **获取涨停股列表**: 使用同花顺 getharden 接口
2. **获取涨停原因**: 从同花顺数据中提取
3. **计算连板天数**: 使用 mootdx K线数据
4. **获取基础行情**: 使用东财选股接口补充

### 备选方案

如果同花顺接口不可用：
- 使用东财选股接口获取涨跌幅>=9.9%的股票
- 使用 mootdx K线数据自行判断涨停

## 涨停原因归一化映射表

基于同花顺数据，建议的归一化映射：

| 原始原因 | 归一化为 | 说明 |
|----------|----------|------|
| AI, 人工智能, 大模型, ChatGPT, AIGC | AI概念 | 人工智能相关 |
| 新能源, 光伏, 锂电池, 储能, 风电 | 新能源 | 新能源相关 |
| 军工, 国防, 航天, 航空 | 军工 | 军工相关 |
| 医药, 生物, 疫苗, 创新药 | 医药 | 医药相关 |
| 华为, 鸿蒙, HUAWEI | 华为概念 | 华为相关 |

## 后续工作

1. 实现涨停数据获取接口
2. 实现连板天数计算
3. 实现涨停原因归一化
4. 编写单元测试
5. 更新接口文档

## 验证脚本

验证脚本位置: `scripts/phase0_verify_apis.py`

运行命令:
```bash
python scripts/phase0_verify_apis.py --date 2026-06-13
```
