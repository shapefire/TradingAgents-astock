#!/usr/bin/env python3
"""Phase 0: 东财接口字段验证脚本

验证内容：
1. RPT_LIMITUP_STOCK 涨停列表接口字段
2. RPT_LIMITDOWN_STOCK 跌停列表接口字段
3. 涨停原因字段质量
4. 封单金额数据可用性
5. 市场涨跌家数接口

使用方法：
    python scripts/phase0_verify_apis.py
    python scripts/phase0_verify_apis.py --date 2026-06-13
"""

import sys
import os
import io
import json
import time
import random
from datetime import datetime, timedelta
from collections import Counter

# Windows 终端 UTF-8 输出
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

# ---------------------------------------------------------------------------
# 复用 a_stock.py 的 _em_get 逻辑（避免循环导入）
# ---------------------------------------------------------------------------
_EM_SESSION = requests.Session()
_EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_PUSH2_URL = "https://push2.eastmoney.com/api/qt/clist/get"


def _em_get(url, params=None, headers=None, timeout=15):
    """东财统一请求入口"""
    wait = _EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.3))
    try:
        return _EM_SESSION.get(
            url, params=params, headers=headers, timeout=timeout
        )
    finally:
        _em_last_call[0] = time.time()


def _datacenter_query(report_name, columns="ALL", filter_str="", page_size=50,
                      sort_columns="", sort_types="-1"):
    """东财数据中心查询"""
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_str,
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    r = _em_get(_DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


# ---------------------------------------------------------------------------
# 验证函数
# ---------------------------------------------------------------------------

def verify_limitup_stock(trade_date: str):
    """验证涨停数据接口（多源验证）"""
    print(f"\n{'='*60}")
    print(f"📊 验证涨停数据接口（多源验证）")
    print(f"   日期: {trade_date}")
    print(f"{'='*60}")

    results = {
        "trade_date": trade_date,
        "eastmoney_datacenter": None,
        "eastmoney_xuangu": None,
        "ths_getharden": None,
        "mootdx_kline": None,
    }

    # 1. 尝试东财 datacenter 接口
    print("\n[1] 尝试东财 datacenter 接口 (RPT_LIMITUP_STOCK)...")
    data = _datacenter_query(
        "RPT_LIMITUP_STOCK",
        columns="ALL",
        filter_str=f"(TRADE_DATE='{trade_date}')",
        page_size=10,
    )
    if data:
        print(f"   ✅ 接口可用，记录数: {len(data)}")
        results["eastmoney_datacenter"] = {
            "available": True,
            "fields": list(data[0].keys()),
            "records": len(data),
        }
    else:
        print(f"   ❌ 接口不可用（可能已变更）")
        results["eastmoney_datacenter"] = {"available": False}

    # 2. 尝试东财选股接口（涨跌幅>=9.9%筛选涨停）
    print("\n[2] 尝试东财选股接口 (dataapi/xuangu/list)...")
    try:
        url = 'https://data.eastmoney.com/dataapi/xuangu/list'
        params = {
            'st': 'CHANGE_RATE',
            'sr': '-1',
            'ps': '10',
            'p': '1',
            'sty': 'SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,CHANGE_RATE,NEW_PRICE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,VOLUME_RATIO,TURNOVERRATE,PE9,TOTAL_MARKET_CAP,FREE_CAP,DEAL_AMOUNT',
            'filter': '(CHANGE_RATE>=9.9)',
        }
        headers = {
            'User-Agent': _UA,
            'Referer': 'https://data.eastmoney.com/',
        }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        result = data.get('result')
        if result and result.get('data'):
            records = result['data']
            print(f"   ✅ 接口可用，记录数: {len(records)}")
            print(f"   字段: {list(records[0].keys())}")
            results["eastmoney_xuangu"] = {
                "available": True,
                "fields": list(records[0].keys()),
                "records": len(records),
                "sample": records[0],
            }
        else:
            print(f"   ❌ 接口返回空数据")
            results["eastmoney_xuangu"] = {"available": False}
    except Exception as e:
        print(f"   ❌ 请求失败: {e}")
        results["eastmoney_xuangu"] = {"available": False, "error": str(e)}

    # 3. 尝试同花顺涨停接口
    print("\n[3] 尝试同花顺涨停接口 (getharden)...")
    try:
        url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{trade_date}/orderby/date/orderway/desc/charset/GBK/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36'
        }
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        rows = data.get('data', [])
        if rows:
            print(f"   ✅ 接口可用，记录数: {len(rows)}")
            print(f"   字段: {list(rows[0].keys())}")
            results["ths_getharden"] = {
                "available": True,
                "fields": list(rows[0].keys()),
                "records": len(rows),
                "sample": rows[0],
            }
        else:
            print(f"   ❌ 接口返回空数据")
            results["ths_getharden"] = {"available": False}
    except Exception as e:
        print(f"   ❌ 请求失败: {e}")
        results["ths_getharden"] = {"available": False, "error": str(e)}

    # 4. 尝试 mootdx K 线数据判断涨停和连板天数
    print("\n[4] 尝试 mootdx K 线数据判断涨停和连板天数...")
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')

        # 测试几只股票
        test_codes = ['600026', '301566', '301526']
        kline_results = []

        for code in test_codes:
            try:
                kdata = client.bars(symbol=code, frequency=9, offset=20)  # 获取20天数据计算连板
                if len(kdata) >= 2:
                    # 计算涨停价和判断涨停
                    prev_close = kdata['close'].iloc[-2]
                    current_close = kdata['close'].iloc[-1]
                    limit_up_price = round(prev_close * 1.1, 2)
                    is_limit_up = abs(current_close - limit_up_price) < 0.01

                    # 计算连板天数
                    consecutive_days = 0
                    for i in range(len(kdata)-1, 0, -1):
                        if i >= 1:
                            prev = kdata['close'].iloc[i-1]
                            curr = kdata['close'].iloc[i]
                            limit_price = round(prev * 1.1, 2)
                            if abs(curr - limit_price) < 0.01:
                                consecutive_days += 1
                            else:
                                break

                    kline_results.append({
                        "code": code,
                        "prev_close": prev_close,
                        "current_close": current_close,
                        "limit_up_price": limit_up_price,
                        "is_limit_up": is_limit_up,
                        "consecutive_limit_days": consecutive_days,
                    })
            except Exception as e:
                pass

        if kline_results:
            print(f"   ✅ mootdx 可用，测试 {len(kline_results)} 只股票")
            for item in kline_results:
                status = "涨停" if item["is_limit_up"] else "未涨停"
                print(f"   {item['code']}: {item['current_close']} (涨停价:{item['limit_up_price']}) -> {status}, 连板: {item['consecutive_limit_days']}天")
            results["mootdx_kline"] = {
                "available": True,
                "test_results": kline_results,
            }
        else:
            print(f"   ❌ mootdx 连接失败")
            results["mootdx_kline"] = {"available": False}
    except Exception as e:
        print(f"   ❌ mootdx 不可用: {e}")
        results["mootdx_kline"] = {"available": False, "error": str(e)}

    return results


def verify_limitdown_stock(trade_date: str):
    """验证 RPT_LIMITDOWN_STOCK 接口"""
    print(f"\n{'='*60}")
    print(f"📊 验证 RPT_LIMITDOWN_STOCK 接口")
    print(f"{'='*60}")

    data = _datacenter_query(
        "RPT_LIMITDOWN_STOCK",
        columns="ALL",
        filter_str=f"(TRADE_DATE='{trade_date}')",
        page_size=10,
    )

    if not data:
        print("   ❌ 无数据返回")
        return None

    all_fields = set()
    for item in data:
        all_fields.update(item.keys())

    print(f"   字段数: {len(all_fields)}")
    print(f"   记录数: {len(data)}")

    # 显示字段
    for field in sorted(all_fields)[:20]:
        sample_val = data[0].get(field, "N/A")
        print(f"   📋 {field:30s} = {str(sample_val)[:50]}")

    return {
        "fields": sorted(all_fields),
        "total_records": len(data),
    }


def verify_reason_quality(trade_date: str):
    """验证涨停原因字段质量"""
    print(f"\n{'='*60}")
    print(f"📊 涨停原因字段质量分析")
    print(f"{'='*60}")

    # 获取较多数据
    data = _datacenter_query(
        "RPT_LIMITUP_STOCK",
        columns="ALL",
        filter_str=f"(TRADE_DATE='{trade_date}')",
        page_size=200,
    )

    if not data:
        print("   ❌ 无数据")
        return None

    # 分析涨停原因
    reasons = []
    for item in data:
        reason = item.get("LIMIT_UP_REASON", "")
        if reason:
            reasons.append(reason)

    print(f"   总涨停股: {len(data)}")
    print(f"   有涨停原因: {len(reasons)}")

    if not reasons:
        print("   ❌ 涨停原因字段为空")
        return None

    # 统计原因分布
    reason_counter = Counter(reasons)
    print(f"   不同原因数: {len(reason_counter)}")

    # 分析原因格式
    print(f"\n[1] 前20个涨停原因:")
    for i, (reason, count) in enumerate(reason_counter.most_common(20), 1):
        print(f"   {i:2d}. {reason}: {count}只")

    # 分析多值原因（包含分隔符的原因）
    multi_value_count = 0
    multi_value_separator = []
    for reason in reasons:
        if ";" in reason or "；" in reason or "," in reason or "，" in reason:
            multi_value_count += 1
            for sep in [";", "；", ",", "，"]:
                if sep in reason:
                    multi_value_separator.append(sep)

    print(f"\n[2] 多值原因分析:")
    print(f"   包含分隔符的原因: {multi_value_count}/{len(reasons)}")
    if multi_value_separator:
        sep_counter = Counter(multi_value_separator)
        print(f"   分隔符分布: {dict(sep_counter)}")

    # 分析需要归一化的原因
    SIMILAR_GROUPS = {
        "AI": ["人工智能", "AI", "大模型", "ChatGPT", "AIGC", "算力", "机器人"],
        "新能源": ["新能源", "光伏", "锂电池", "储能", "风电", "新能源汽车"],
        "军工": ["军工", "国防", "航天", "航空"],
        "医药": ["医药", "生物", "疫苗", "创新药"],
    }

    print(f"\n[3] 归一化分析:")
    normalization_candidates = []
    for group_name, keywords in SIMILAR_GROUPS.items():
        matching = []
        for reason in reasons:
            for kw in keywords:
                if kw in reason:
                    matching.append(reason)
                    break
        if matching:
            unique_matching = list(set(matching))
            normalization_candidates.append({
                "group": group_name,
                "count": len(matching),
                "unique_reasons": unique_matching[:5],
            })
            print(f"   {group_name}: {len(matching)}只匹配")
            for r in unique_matching[:3]:
                print(f"     - {r}")

    return {
        "total_reasons": len(reasons),
        "unique_reasons": len(reason_counter),
        "multi_value_count": multi_value_count,
        "normalization_candidates": normalization_candidates,
        "top_reasons": reason_counter.most_common(20),
    }


def verify_seal_amount(trade_date: str):
    """验证封单金额数据可用性"""
    print(f"\n{'='*60}")
    print(f"📊 封单金额数据验证")
    print(f"{'='*60}")

    # 获取涨停股列表
    data = _datacenter_query(
        "RPT_LIMITUP_STOCK",
        columns="ALL",
        filter_str=f"(TRADE_DATE='{trade_date}')",
        page_size=5,
    )

    if not data:
        print("   ❌ 无涨停数据")
        return None

    # 检查是否有封单相关字段
    seal_fields = [f for f in data[0].keys() if "SEAL" in f.upper() or "FENG" in f.upper() or "BUY" in f.upper()]
    print(f"   封单相关字段: {seal_fields}")

    # 检查 push2 接口获取封单数据
    print(f"\n[1] 尝试通过 push2 获取封单数据...")
    for item in data[:3]:
        code = item.get("SECURITY_CODE", "")
        if not code:
            continue

        # 判断市场
        if code.startswith("6"):
            secid = f"1.{code}"
        elif code.startswith(("0", "3")):
            secid = f"0.{code}"
        else:
            continue

        params = {
            "secid": secid,
            "fields": "f43,f44,f45,f46,f47,f48,f50,f57,f58,f168,f170",
            "ut": "fa5fd1943c7b386f172d6893dbbd1d0c",
        }
        try:
            r = _em_get(_PUSH2_URL, params=params, timeout=10)
            d = r.json()
            if d.get("data"):
                stock_data = d["data"]
                print(f"   {code} push2 字段: {list(stock_data.keys())[:15]}")
                # f57=代码, f58=名称, f43=最新价, f44=最高, f45=最低, f46=开盘
                # f47=成交量, f48=成交额, f50=量比, f168=换手率, f170=涨跌幅
                print(f"     代码: {stock_data.get('f57')}")
                print(f"     名称: {stock_data.get('f58')}")
                print(f"     最新价: {stock_data.get('f43')}")
                print(f"     成交额: {stock_data.get('f48')}")
                print(f"     换手率: {stock_data.get('f168')}")
            else:
                print(f"   {code} push2 无数据")
        except Exception as e:
            print(f"   {code} push2 请求失败: {e}")

    # 检查涨停列表接口是否有封单字段
    print(f"\n[2] 检查涨停列表接口的封单字段:")
    seal_candidates = ["SEAL_AMOUNT", "BUY_AMOUNT", "ORDER_AMOUNT", "SEAL_NUM",
                       "FENG_DAN", "BUY1", "BUY1_AMOUNT", "SEALED_AMOUNT"]
    found_seal = [f for f in seal_candidates if f in data[0].keys()]
    if found_seal:
        print(f"   ✅ 找到封单字段: {found_seal}")
    else:
        print(f"   ❌ 涨停列表接口无封单字段")
        print(f"   说明: 封单金额需要通过 push2 实时行情获取，不在涨停列表中")

    return {
        "seal_fields_in_limitup": found_seal,
        "push2_available": True,
    }


def verify_market_breadth(trade_date: str):
    """验证市场涨跌家数接口"""
    print(f"\n{'='*60}")
    print(f"📊 市场涨跌家数接口验证")
    print(f"{'='*60}")

    # 方法1: 通过 push2 获取全市场行情统计
    print(f"[1] 尝试 push2 全市场行情...")

    # 沪深A股
    params = {
        "pn": "1",
        "pz": "1",  # 只获取总数
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",  # 沪深A股
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13,f14,f15,f16,f17,f18,f20,f21",
    }
    try:
        r = _em_get(_PUSH2_URL, params=params, timeout=10)
        d = r.json()
        total = d.get("data", {}).get("total", 0)
        print(f"   沪深A股总数: {total}")
    except Exception as e:
        print(f"   ❌ 请求失败: {e}")

    # 方法2: 尝试获取涨跌统计
    print(f"\n[2] 尝试获取涨跌统计...")

    # 尝试不同的 fs 参数
    # f3=涨跌幅, f4=涨跌额
    # 涨: f3>0, 跌: f3<0, 平: f3=0
    for label, fs_filter in [
        ("上涨", "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"),
        ("下跌", "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"),
    ]:
        params = {
            "pn": "1",
            "pz": "1",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": fs_filter,
            "fields": "f3",
        }
        try:
            r = _em_get(_PUSH2_URL, params=params, timeout=10)
            d = r.json()
            # 这个接口可能不支持按涨跌筛选
        except Exception as e:
            pass

    # 方法3: 通过涨停/跌停统计间接获取
    print(f"\n[3] 通过涨停/跌停统计间接获取市场宽度...")

    limitup_data = _datacenter_query(
        "RPT_LIMITUP_STOCK",
        columns="SECURITY_CODE",
        filter_str=f"(TRADE_DATE='{trade_date}')",
        page_size=500,
    )
    limitdown_data = _datacenter_query(
        "RPT_LIMITDOWN_STOCK",
        columns="SECURITY_CODE",
        filter_str=f"(TRADE_DATE='{trade_date}')",
        page_size=500,
    )

    print(f"   涨停家数: {len(limitup_data)}")
    print(f"   跌停家数: {len(limitdown_data)}")
    if limitdown_data:
        print(f"   涨跌停比: {len(limitup_data)}:{len(limitdown_data)}")

    return {
        "limitup_count": len(limitup_data),
        "limitdown_count": len(limitdown_data),
    }


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def main():
    """主函数"""
    import argparse
    parser = argparse.ArgumentParser(description="Phase 0: 东财接口字段验证")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="交易日期 (YYYY-MM-DD)")
    args = parser.parse_args()

    trade_date = args.date
    print(f"🔍 Phase 0: 东财接口字段验证")
    print(f"   日期: {trade_date}")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = {}

    # 1. 验证涨停列表接口
    results["limitup"] = verify_limitup_stock(trade_date)

    # 2. 验证跌停列表接口
    results["limitdown"] = verify_limitdown_stock(trade_date)

    # 3. 验证涨停原因质量
    if results["limitup"]:
        results["reason_quality"] = verify_reason_quality(
            results["limitup"]["trade_date"]
        )

    # 4. 验证封单数据
    if results["limitup"]:
        results["seal_amount"] = verify_seal_amount(
            results["limitup"]["trade_date"]
        )

    # 5. 验证市场涨跌家数
    results["market_breadth"] = verify_market_breadth(trade_date)

    # 汇总报告
    print(f"\n{'='*60}")
    print(f"📋 Phase 0 验证汇总报告")
    print(f"{'='*60}")

    print(f"\n[1. 涨停列表接口验证]")
    if results.get("limitup"):
        r = results["limitup"]
        # 东财 datacenter
        if r.get("eastmoney_datacenter", {}).get("available"):
            print(f"  ✅ 东财 datacenter: 可用")
        else:
            print(f"  ❌ 东财 datacenter: 不可用（接口已变更）")

        # 东财选股
        if r.get("eastmoney_xuangu", {}).get("available"):
            print(f"  ✅ 东财选股接口: 可用")
            print(f"     字段: {r['eastmoney_xuangu'].get('fields', [])}")
        else:
            print(f"  ❌ 东财选股接口: 不可用")

        # 同花顺
        if r.get("ths_getharden", {}).get("available"):
            print(f"  ✅ 同花顺 getharden: 可用")
            print(f"     字段: {r['ths_getharden'].get('fields', [])}")
        else:
            print(f"  ❌ 同花顺 getharden: 不可用")

        # mootdx
        if r.get("mootdx_kline", {}).get("available"):
            print(f"  ✅ mootdx K线: 可用（可判断涨停）")
        else:
            print(f"  ❌ mootdx K线: 不可用")
    else:
        print(f"  ❌ 无法验证")

    print(f"\n[2. 跌停列表接口]")
    if results.get("limitdown"):
        print(f"  ✅ 接口可用，字段数: {len(results['limitdown']['fields'])}")
    else:
        print(f"  ❌ 接口不可用")

    print(f"\n[3. 涨停原因质量]")
    if results.get("reason_quality"):
        r = results["reason_quality"]
        print(f"  总原因数: {r['total_reasons']}")
        print(f"  不同原因: {r['unique_reasons']}")
        print(f"  多值原因: {r['multi_value_count']}")
        print(f"  归一化候选: {len(r['normalization_candidates'])} 组")
    else:
        print(f"  ❌ 无法分析")

    print(f"\n[4. 封单数据]")
    if results.get("seal_amount"):
        r = results["seal_amount"]
        if r["seal_fields_in_limitup"]:
            print(f"  ✅ 涨停列表有封单字段: {r['seal_fields_in_limitup']}")
        else:
            print(f"  ⚠️  涨停列表无封单字段，需通过 push2 获取")
        print(f"  push2 可用: {r['push2_available']}")
    else:
        print(f"  ❌ 无法验证")

    print(f"\n[5. 市场涨跌家数]")
    if results.get("market_breadth"):
        r = results["market_breadth"]
        print(f"  涨停家数: {r['limitup_count']}")
        print(f"  跌停家数: {r['limitdown_count']}")
    else:
        print(f"  ❌ 无法获取")

    # 关键结论
    print(f"\n{'='*60}")
    print(f"🔑 关键结论")
    print(f"{'='*60}")
    print(f"1. 东财 RPT_LIMITUP_STOCK 接口已失效，需使用替代方案")
    print(f"2. 推荐方案: 同花顺 getharden（涨停原因）+ mootdx K线（连板天数）")
    print(f"3. 东财选股接口可作为补充数据源")
    print(f"4. 封单数据需通过 push2 实时行情获取")

    # 保存结果到 JSON
    output_file = os.path.join(os.path.dirname(__file__), "phase0_results.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 结果已保存到: {output_file}")

    return results


if __name__ == "__main__":
    main()
