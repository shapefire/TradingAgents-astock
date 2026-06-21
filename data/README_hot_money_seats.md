# 一线游资席位库维护说明

`known_hot_money_seats.json` 用于龙虎榜席位匹配：当日一线游资席位净买入时，首板二板预期评分 **+10**。

## 文件位置

`data/known_hot_money_seats.json`

## 结构

```json
{
  "version": "1.0",
  "description": "...",
  "seats": [
    {
      "name": "游资昵称",
      "aliases": ["营业部全称", "简称..."]
    }
  ]
}
```

- `name`：展示用昵称（日志/报告）
- `aliases`：东财龙虎榜返回的营业部字符串，**尽量写全称**，可附常见简写

## 维护流程

1. 从当日龙虎榜核对买入席位营业部原文（东财 `RPT_DAILYBILLBOARD_DETAILSNEW`）
2. 将新一线席位按 `aliases` 追加到 `seats` 数组，避免重复 `name`
3. 运行 `python -m pytest tests/test_short_term_features.py -k hot_money -v` 确认匹配逻辑
4. 更新 `version` 或在本文件记录变更日期

## 匹配逻辑

代码路径：`tradingagents/dataflows/a_stock.py` → `_get_lhb_seat_metrics()`

- 龙虎榜买入席位与 `aliases` 子串匹配（归一化后）
- 命中且净买入 → `hot_money_buy=True`，首板评分 +10

## 注意事项

- 营业部更名后保留旧 `aliases`，避免历史数据漏匹配
- 不要写入个人联系方式或非公开信息
- 批量扫描时可设 `EM_MIN_INTERVAL=1.5` 降低东财限流风险
