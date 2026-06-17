"""A-stock (China mainland) data vendor for TradingAgents.

Zero third-party data dependency (no akshare). All sources are direct HTTP APIs
or mootdx TCP.

Data sources:
- mootdx (TCP 7709): OHLCV K-lines, financial snapshots, F10 text
- Tencent Finance (HTTP GBK): PE/PB/market cap/turnover
- 东方财富 push2 / datacenter-web (direct HTTP): stock info, dragon-tiger, lockup,
  fund flow, concept blocks, industry comparison, margin trading, block trades,
  shareholder count, research reports, dividends
- 新浪财经 (direct HTTP): K-line fallback, financial statements
- 同花顺 (direct HTTP): consensus EPS, hot stocks, northbound capital flow

V3.2.2 changes (aligned with a-stock-data SKILL.md):
- Concept blocks: Baidu PAE getrelatedblock → 东财 slist API (spt=3)
- Global news: CLS wire offline (cls.cn migrated to Next.js) → Eastmoney 7x24 only
- Sina financial reports: Fixed report_list parsing structure
- Fund flow: Extended from 20 to 120 trading days

New endpoints (V3.2.2 additions):
- get_margin_trading: 融资融券明细 (leverage sentiment indicator)
- get_block_trade: 大宗交易 (institutional intent, premium/discount signals)
- get_shareholder_count: 股东户数变化 (chip concentration, accumulation detection)
- get_research_reports: 研报列表 (institutional ratings, EPS forecasts)
- get_dividend_history: 分红送转历史 (dividend yield, high bonus/transfer catalyst)
- get_daily_dragon_tiger: 全市场龙虎榜 (daily full-market summary)
- get_northbound_stock_holdings: 北向个股持仓 (foreign institutional holdings)
"""

from __future__ import annotations

from typing import Annotated
from datetime import datetime
from dateutil.relativedelta import relativedelta
import json as _json
import os
import logging
import math
import random
import re as _re
import time
import uuid
import urllib.request

import pandas as pd
import requests as _requests

from .utils import safe_ticker_component

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers: ticker format & market detection
# ---------------------------------------------------------------------------

def _get_prefix(code: str) -> str:
    """6-digit A-stock code -> market prefix for Tencent API."""
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    return "sz"


def _normalize_ticker(symbol: str) -> str:
    """Strip exchange prefix/suffix, return pure 6-digit code.

    Handles: '688017', 'SH688017', '688017.SH', 'sh688017'
    """
    s = symbol.strip().upper()
    # Remove .SH / .SZ / .BJ suffix
    for suffix in (".SH", ".SZ", ".BJ"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    # Remove SH / SZ / BJ prefix
    for prefix in ("SH", "SZ", "BJ"):
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    return safe_ticker_component(s)


# ---------------------------------------------------------------------------
# Stock name <-> code mapping (cached)
# ---------------------------------------------------------------------------

_name_to_code: dict[str, str] | None = None
_code_to_name: dict[str, str] | None = None


def _build_name_code_map() -> tuple[dict[str, str], dict[str, str]]:
    """Build name→code and code→name maps via mootdx or HTTP fallback.

    Strategy:
    1. Try mootdx TCP (fast, full market data)
    2. If mootdx fails (overseas network), fallback to Eastmoney HTTP API

    Returns empty dicts if both methods fail.
    On failure the cache is NOT populated (``_name_to_code`` stays ``None``)
    so the next call automatically retries — transient network issues recover
    naturally without any manual reset.
    """
    global _name_to_code, _code_to_name
    if _name_to_code is not None:
        return _name_to_code, _code_to_name

    # Method 1: Try mootdx TCP (preferred for speed)
    n2c, c2n = _build_name_code_map_mootdx()
    if n2c:
        _name_to_code = n2c
        _code_to_name = c2n
        return _name_to_code, _code_to_name

    # Method 2: Fallback to HTTP API (works overseas)
    logger.info("mootdx unavailable, trying HTTP API fallback for name-code map")
    n2c, c2n = _build_name_code_map_http()
    if n2c:
        _name_to_code = n2c
        _code_to_name = c2n
        return _name_to_code, _code_to_name

    return {}, {}


def resolve_ticker_online(name: str) -> str:
    """Resolve Chinese stock name to 6-digit code via Eastmoney search API.

    This is a lightweight alternative to building full market map.
    Works even when push2 API is blocked by proxy.
    """
    import urllib.parse
    try:
        encoded_name = urllib.parse.quote(name)
        url = (
            f"http://searchapi.eastmoney.com/api/suggest/get?"
            f"input={encoded_name}&type=14"
            f"&token=D43BF722C8E33BDC906FB84D85E326E8&count=5"
        )
        req = urllib.request.Request(url)
        req.add_header("User-Agent", _UA)
        resp = urllib.request.urlopen(req, timeout=10)
        data = _json.loads(resp.read().decode("utf-8"))

        items = data.get("QuotationCodeTable", {}).get("Data", [])
        if not items:
            return ""

        # Find first A-stock result
        for item in items:
            if item.get("Classify") == "AStock":
                code = item.get("UnifiedCode", "")
                if code and _re.match(r"^[036]\d{5}$", code):
                    return code

        return ""
    except Exception as exc:
        logger.warning("Eastmoney search API failed for '%s': %s", name, exc)
        return ""


def _build_name_code_map_mootdx() -> tuple[dict[str, str], dict[str, str]]:
    """Build name→code map via mootdx TCP (both SH & SZ markets).

    Returns empty dicts if mootdx is unreachable (e.g. TCP 7709 down).
    """
    try:
        from mootdx.quotes import Quotes

        client = Quotes.factory(market="std")
    except Exception as exc:
        logger.warning("mootdx connection failed: %s", exc)
        return {}, {}

    n2c: dict[str, str] = {}
    c2n: dict[str, str] = {}

    try:
        for market in (0, 1):  # 0=SZ, 1=SH
            stocks = client.stocks(market=market)
            if stocks is None or stocks.empty:
                continue
            for _, row in stocks.iterrows():
                code = str(row["code"]).strip()
                name = str(row["name"]).strip()
                if not _re.match(r"^[036]\d{5}$", code):
                    continue
                clean_name = name.replace(" ", "").replace("　", "")
                n2c[clean_name] = code
                c2n[code] = clean_name
    except Exception as exc:
        logger.warning("mootdx stocks() failed: %s", exc)
        return {}, {}

    logger.info("Built stock name-code map via mootdx: %d entries", len(n2c))
    return n2c, c2n


def _build_name_code_map_http() -> tuple[dict[str, str], dict[str, str]]:
    """Build name→code map via Eastmoney HTTP API (works overseas).

    Uses push2 API to fetch full A-stock list (~5000 stocks).
    Returns empty dicts if HTTP request fails.
    """
    n2c: dict[str, str] = {}
    c2n: dict[str, str] = {}

    try:
        # Eastmoney push2 API: fs=m:0+t:6 (SZ main), m:0+t:80 (SZ SME),
        # m:1+t:2 (SH main), m:1+t:23 (SH STAR)
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": "10000",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f12,f14",
        }
        r = _em_get(url, params=params, timeout=30)
        data = r.json()

        items = data.get("data", {}).get("diff", [])
        if not items:
            logger.warning("Eastmoney HTTP API returned empty stock list")
            return {}, {}

        for item in items:
            code = str(item.get("f12", "")).strip()
            name = str(item.get("f14", "")).strip()
            if not code or not name:
                continue
            if not _re.match(r"^[036]\d{5}$", code):
                continue
            clean_name = name.replace(" ", "").replace("　", "")
            n2c[clean_name] = code
            c2n[code] = clean_name

        logger.info("Built stock name-code map via HTTP: %d entries", len(n2c))
        return n2c, c2n

    except Exception as exc:
        logger.warning("Eastmoney HTTP API failed for name-code map: %s", exc)
        return {}, {}


def resolve_ticker(user_input: str) -> str:
    """Resolve user input (code or Chinese name) to a 6-digit A-stock code.

    Accepts: '600379', 'SH600379', '600379.SH', '宝光股份'
    Returns: '600379'
    Raises: ValueError if not resolvable.
    """
    s = user_input.strip()
    if not s:
        raise ValueError("输入不能为空")

    has_chinese = any("一" <= ch <= "鿿" for ch in s)

    if not has_chinese:
        return _normalize_ticker(s)

    clean = s.replace(" ", "").replace("　", "")
    n2c, _ = _build_name_code_map()

    # Try local map first
    if n2c:
        if clean in n2c:
            return n2c[clean]

        matches = {name: code for name, code in n2c.items() if clean in name}
        if len(matches) == 1:
            return next(iter(matches.values()))
        if len(matches) > 1:
            examples = ", ".join(f"{n}({c})" for n, c in list(matches.items())[:5])
            raise ValueError(f"'{s}' 匹配到多只股票: {examples}，请输入完整名称或代码")

    # Fallback: online search API (works even when push2 is blocked)
    logger.info("Local map miss for '%s', trying online search API", s)
    code = resolve_ticker_online(clean)
    if code:
        logger.info("Resolved '%s' -> %s via online search API", s, code)
        return code

    if not n2c:
        raise ValueError(
            f"无法解析中文股票名 '{s}'：本地映射表为空且在线搜索失败。"
            "请直接输入 6 位股票代码（如 000539）"
        )

    raise ValueError(f"找不到股票 '{s}'，请检查名称是否正确")


# ---------------------------------------------------------------------------
# mootdx client (singleton)
# ---------------------------------------------------------------------------

_mootdx_client = None


def _get_mootdx_client():
    """Lazy-init mootdx Quotes client (TCP connection, reusable)."""
    global _mootdx_client
    if _mootdx_client is None:
        from mootdx.quotes import Quotes

        _mootdx_client = Quotes.factory(market="std")
    return _mootdx_client


# ---------------------------------------------------------------------------
# Tencent Finance API
# ---------------------------------------------------------------------------

def _tencent_quote(codes: list[str]) -> dict[str, dict]:
    """Batch real-time quotes from Tencent Finance (qt.gtimg.cn).

    Returns dict[code] -> {name, price, pe_ttm, pb, mcap_yi, ...}
    """
    cache_key = ("tencent_quote", tuple(sorted(codes)))
    if cache_key in _session_cache:
        return _session_cache[cache_key]

    try:
        prefixed = [f"{_get_prefix(c)}{c}" for c in codes]
        url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("gbk")

        result = {}
        for line in raw.strip().split(";"):
            if not line.strip() or "=" not in line or '"' not in line:
                continue
            key = line.split("=")[0].split("_")[-1]
            vals = line.split('"')[1].split("~")
            if len(vals) < 53:
                continue
            code = key[2:]  # strip sh/sz/bj prefix
            result[code] = {
                "name": vals[1],
                "price": float(vals[3]) if vals[3] else 0,
                "last_close": float(vals[4]) if vals[4] else 0,
                "open": float(vals[5]) if vals[5] else 0,
                "change_pct": float(vals[32]) if vals[32] else 0,
                "high": float(vals[33]) if vals[33] else 0,
                "low": float(vals[34]) if vals[34] else 0,
                "turnover_pct": float(vals[38]) if vals[38] else 0,
                "pe_ttm": float(vals[39]) if vals[39] else 0,
                "mcap_yi": float(vals[44]) if vals[44] else 0,
                "float_mcap_yi": float(vals[45]) if vals[45] else 0,
                "pb": float(vals[46]) if vals[46] else 0,
                "limit_up": float(vals[47]) if vals[47] else 0,
                "limit_down": float(vals[48]) if vals[48] else 0,
                "pe_static": float(vals[52]) if vals[52] else 0,
            }
        _session_cache[cache_key] = result
        return result
    except Exception as e:
        logger.warning("_tencent_quote failed: %s", e)
        _session_cache[cache_key] = {}
        return {}


# ---------------------------------------------------------------------------
# Eastmoney Datacenter unified helper (龙虎榜/解禁 etc.)
# ---------------------------------------------------------------------------

_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


# ---------------------------------------------------------------------------
# 东财防封：全局节流 + 会话复用 (Eastmoney anti-ban: throttle + Keep-Alive)
# ---------------------------------------------------------------------------
# 东财系 HTTP 接口（push2 / push2his / datacenter-web / search-api / np-weblist）
# 有风控：每秒 >5 次 / 单 IP 并发 ≥10 / 1 分钟 ≥200 次 / 5 分钟 ≥300 次 → 临时封 IP。
# 多 Agent 投研跑批量分析时会高频请求东财，是被封的头号元凶。所有 eastmoney.com
# 请求一律走 _em_get()：串行限流（最小间隔 + 随机抖动）+ 复用 Keep-Alive 会话 + 默认 UA。
# 注意：仅东财接口走此入口；mootdx(TCP) / 腾讯 / 新浪 / 同花顺 / 财联社 / 百度 等
# 不限流（实测不封 IP 或风控极弱）。批量任务可调大 EM_MIN_INTERVAL 进一步降速。
_EM_SESSION = _requests.Session()
_EM_SESSION.headers.update({"User-Agent": _UA})
# 两次东财请求最小间隔(秒)；批量多 Agent 场景可设环境变量 EM_MIN_INTERVAL=1.5~2 降速。
_EM_MIN_INTERVAL = float(os.environ.get("EM_MIN_INTERVAL", "1.0"))
_em_last_call = [0.0]  # 模块级上次东财请求时间戳
# 连续失败计数器：连续 N 次失败后自动跳过后续请求（快速失败，避免卡住）
_em_consecutive_fails = [0]
_EM_FAIL_FAST_THRESHOLD = 3  # 连续失败 3 次后跳过
_EM_COOLDOWN_SECONDS = 30    # 跳过冷却时间（秒）


def _em_get(url, params=None, headers=None, timeout=15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA + 快速失败。

    所有 eastmoney.com 接口都应通过它请求，避免多 Agent 高频拉数据被封 IP。
    串行限流：与上次东财请求间隔 < EM_MIN_INTERVAL 时 sleep 补足 + 0.1~0.5s 随机抖动。
    传入的 headers 会覆盖 session 默认 UA（用于保留各端点自己的 Referer/Origin）。

    快速失败：连续失败超过 _EM_FAIL_FAST_THRESHOLD 次后，直接返回 None
    而非每次都等待 timeout 秒，避免分析流程被卡住。冷却 _EM_COOLDOWN_SECONDS
    秒后自动恢复。
    """
    # 快速失败检查
    if _em_consecutive_fails[0] >= _EM_FAIL_FAST_THRESHOLD:
        elapsed = time.time() - _em_last_call[0]
        if elapsed < _EM_COOLDOWN_SECONDS:
            logger.debug("_em_get: skipping (cooldown %ds left)", int(_EM_COOLDOWN_SECONDS - elapsed))
            return None
        # 冷却期结束，重置计数器，允许重试
        _em_consecutive_fails[0] = 0

    wait = _EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        resp = _EM_SESSION.get(
            url, params=params, headers=headers, timeout=timeout, **kwargs
        )
        _em_consecutive_fails[0] = 0  # 成功，重置计数器
        return resp
    except Exception:
        _em_consecutive_fails[0] += 1
        raise
    finally:
        _em_last_call[0] = time.time()


# ---------------------------------------------------------------------------
# 会话级缓存：消除内部函数重复 HTTP 请求
# ---------------------------------------------------------------------------
# 多个短贷公共函数（consecutive_limit_stats, first_board_screen, theme_heat,
# high_board_status, leader_identification）共享底层数据获取函数（_get_limitup_stocks,
# _get_market_breadth 等），但这些函数没有缓存，导致同一分析运行中同一数据被重复请求
# 5-20 次。_session_cache 在进程生命周期内缓存结果，每次分析运行开始时通过
# clear_session_cache() 清除。
_session_cache: dict[tuple, object] = {}


def clear_session_cache() -> None:
    """清除会话级缓存（在每次分析运行开始时调用）。"""
    _session_cache.clear()


def _eastmoney_datacenter(
    report_name: str,
    columns: str = "ALL",
    filter_str: str = "",
    page_size: int = 50,
    sort_columns: str = "",
    sort_types: str = "-1",
) -> list[dict]:
    """东财数据中心统一查询 — 龙虎榜/解禁 共用."""
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
# 同花顺 EPS forecast helper (direct HTTP, no akshare)
# ---------------------------------------------------------------------------


def _ths_eps_forecast(code: str) -> pd.DataFrame:
    """Fetch consensus EPS forecast from 同花顺 (direct HTTP).

    Returns DataFrame with columns roughly: 年度, 预测机构数, 最小值, 均值, 最大值.
    """
    url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
    headers = {
        "User-Agent": _UA,
        "Referer": "https://basic.10jqka.com.cn/",
    }
    r = _requests.get(url, headers=headers, timeout=15)
    r.encoding = "gbk"
    dfs = pd.read_html(r.text)
    # Find the table containing EPS data
    for df in dfs:
        cols = [str(c) for c in df.columns]
        if any("每股收益" in c or "均值" in c for c in cols):
            return df
    # Fallback: return first table if exists
    return dfs[0] if dfs else pd.DataFrame()


# ---------------------------------------------------------------------------
# Sina K-line fallback helper (direct HTTP, no akshare)
# ---------------------------------------------------------------------------


def _sina_kline_fallback(code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """Fetch daily K-line from Sina HTTP API as mootdx fallback.

    Returns DataFrame with columns: Date, Open, High, Low, Close, Volume.
    """
    prefix = "sh" if code.startswith("6") else "sz"
    url = (
        "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "CN_MarketData.getKLineData"
    )
    params = {
        "symbol": f"{prefix}{code}",
        "scale": "240",  # daily
        "ma": "no",
        "datalen": "800",
    }
    r = _requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = _json.loads(r.text)

    if not data:
        return pd.DataFrame()

    rows = []
    for item in data:
        rows.append({
            "Date": item["day"],
            "Open": float(item["open"]),
            "High": float(item["high"]),
            "Low": float(item["low"]),
            "Close": float(item["close"]),
            "Volume": int(item["volume"]),
        })

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])

    if start_date:
        df = df[df["Date"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["Date"] <= pd.to_datetime(end_date)]

    return df


# ---------------------------------------------------------------------------
# OHLCV loading with cache (mootdx -> CSV)
# ---------------------------------------------------------------------------

def _load_ohlcv_astock(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV via mootdx, cache to CSV, filter by curr_date.

    Mirrors stockstats_utils.load_ohlcv but uses mootdx instead of yfinance.
    Returns DataFrame with columns: Date, Open, High, Low, Close, Volume
    """
    from .config import get_config

    code = _normalize_ticker(symbol)
    config = get_config()
    cache_dir = config.get(
        "data_cache_dir", os.path.expanduser("~/.tradingagents/cache")
    )
    os.makedirs(cache_dir, exist_ok=True)

    cache_file = os.path.join(cache_dir, f"{code}-astock-daily.csv")

    if os.path.exists(cache_file):
        mtime = datetime.fromtimestamp(os.path.getmtime(cache_file))
        if mtime.date() == datetime.now().date():
            data = pd.read_csv(cache_file, on_bad_lines="skip", encoding="utf-8")
            data["Date"] = pd.to_datetime(data["Date"])
            cutoff = pd.to_datetime(curr_date)
            return data[data["Date"] <= cutoff]

    # Fetch from mootdx — 800 daily bars (~3 years of trading days)
    try:
        client = _get_mootdx_client()
        df = client.bars(symbol=code, category=4, offset=800)

        if df is None or df.empty:
            raise ValueError(f"No OHLCV data from mootdx for {code}")

        # mootdx returns index named 'datetime' AND a column named 'datetime'
        # (plus year/month/day/hour/minute/volume). Drop duplicates before reset.
        df = df.drop(columns=["datetime", "year", "month", "day", "hour", "minute"], errors="ignore")
        df = df.reset_index()  # moves index 'datetime' → column 'datetime'
        rename_map = {
            "datetime": "Date",
            "open": "Open",
            "close": "Close",
            "high": "High",
            "low": "Low",
            "volume": "Volume",
        }
        df = df.rename(columns=rename_map)
        df = df[["Date", "Open", "High", "Low", "Close", "Volume"]]
        df["Date"] = pd.to_datetime(df["Date"])
    except Exception as e:
        logger.warning("mootdx OHLCV failed for %s: %s, trying sina HTTP fallback", code, e)
        # Fallback: Sina direct HTTP API
        try:
            df = _sina_kline_fallback(code)
            if df.empty:
                raise ValueError(f"No OHLCV data from sina for {code}")
        except Exception:
            raise ValueError(f"No OHLCV data from mootdx/sina for {code}")

    # Cache to disk
    df.to_csv(cache_file, index=False, encoding="utf-8")

    # Filter by curr_date to prevent look-ahead bias
    cutoff = pd.to_datetime(curr_date)
    return df[df["Date"] <= cutoff]


# ===========================================================================
# 9 Vendor Methods (matching interface.py VENDOR_METHODS signatures)
# ===========================================================================


# ---- 1. get_stock_data ----


def get_stock_data(
    symbol: Annotated[str, "A-stock code (e.g. 688017, SH688017)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Get OHLCV stock price data via mootdx."""
    code = _normalize_ticker(symbol)

    data_source = "mootdx (TCP)"
    try:
        client = _get_mootdx_client()
        df = client.bars(symbol=code, category=4, offset=800)

        if df is None or df.empty:
            raise ValueError(f"No data from mootdx for {code}")

        # Drop duplicate datetime column + extra columns before reset_index
        df = df.drop(
            columns=["datetime", "year", "month", "day", "hour", "minute"],
            errors="ignore",
        )
        df = df.reset_index()  # index 'datetime' → column 'datetime'
        df = df.rename(
            columns={
                "datetime": "Date",
                "open": "Open",
                "close": "Close",
                "high": "High",
                "low": "Low",
                "volume": "Volume",
                "amount": "Amount",
            }
        )
        df["Date"] = pd.to_datetime(df["Date"])

    except Exception as e:
        logger.warning("mootdx K-line failed for %s: %s, trying sina HTTP fallback", code, e)
        # Fallback: Sina direct HTTP API
        try:
            df = _sina_kline_fallback(code, start_date, end_date)
            if df.empty:
                return "K线数据获取失败：mootdx和新浪备用源均不可用，请检查网络连接"
            data_source = "sina HTTP (fallback)"
        except Exception:
            return "K线数据获取失败：mootdx和新浪备用源均不可用，请检查网络连接"

    # Filter by date range
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    df = df[(df["Date"] >= start_dt) & (df["Date"] <= end_dt)]

    if df.empty:
        return (
            f"No data found for A-stock '{code}' "
            f"between {start_date} and {end_date}"
        )

    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = df[col].round(2)

    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    csv_out = df[["Date", "Open", "High", "Low", "Close", "Volume"]].to_csv(
        index=False
    )

    header = f"# Stock data for {code} (A-stock) from {start_date} to {end_date}\n"
    header += f"# Total records: {len(df)}\n"
    header += f"# Data source: {data_source}\n"
    header += (
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )

    return header + csv_out


# ---- 2. get_indicators ----

# Supported technical indicators with descriptions
_INDICATOR_DESCRIPTIONS = {
    "close_50_sma": "50 SMA: Medium-term trend indicator.",
    "close_200_sma": "200 SMA: Long-term trend benchmark.",
    "close_10_ema": "10 EMA: Responsive short-term average.",
    "macd": "MACD: Momentum via EMA differences.",
    "macds": "MACD Signal: EMA smoothing of MACD line.",
    "macdh": "MACD Histogram: Gap between MACD and signal.",
    "rsi": "RSI: Momentum overbought/oversold indicator (70/30 thresholds).",
    "boll": "Bollinger Middle: 20 SMA basis for Bollinger Bands.",
    "boll_ub": "Bollinger Upper Band: 2 std devs above middle.",
    "boll_lb": "Bollinger Lower Band: 2 std devs below middle.",
    "atr": "ATR: Average True Range volatility measure.",
    "vwma": "VWMA: Volume-weighted moving average.",
    "mfi": "MFI: Money Flow Index (volume + price momentum).",
}


def get_indicators(
    symbol: Annotated[str, "A-stock code"],
    indicator: Annotated[
        str, "technical indicator (e.g. rsi, macd, close_50_sma)"
    ],
    curr_date: Annotated[str, "Current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """Get technical indicators using stockstats on mootdx OHLCV data."""
    from stockstats import wrap

    code = _normalize_ticker(symbol)

    if indicator not in _INDICATOR_DESCRIPTIONS:
        raise ValueError(
            f"Indicator {indicator} not supported. "
            f"Choose from: {list(_INDICATOR_DESCRIPTIONS.keys())}"
        )

    try:
        data = _load_ohlcv_astock(code, curr_date)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

        # Trigger stockstats calculation
        df[indicator]

        # Build date -> value lookup
        ind_dict = {}
        for _, row in df.iterrows():
            d = row["Date"]
            v = row[indicator]
            ind_dict[d] = "N/A" if pd.isna(v) else str(round(float(v), 4))

        # Generate output for look_back window
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        before = curr_dt - relativedelta(days=look_back_days)

        lines = []
        dt = curr_dt
        while dt >= before:
            ds = dt.strftime("%Y-%m-%d")
            val = ind_dict.get(ds, "N/A: Not a trading day (weekend or holiday)")
            lines.append(f"{ds}: {val}")
            dt -= relativedelta(days=1)

        result = (
            f"## {indicator} values for {code} "
            f"from {before.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
            + "\n".join(lines)
            + "\n\n"
            + _INDICATOR_DESCRIPTIONS.get(indicator, "")
        )
        return result

    except Exception as e:
        return f"Error calculating {indicator} for {code}: {str(e)}"


# ---- 3. get_fundamentals ----


def get_fundamentals(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "current date"] = None,
) -> str:
    """Get company fundamentals from Tencent + mootdx + Eastmoney + 同花顺."""
    code = _normalize_ticker(ticker)

    try:
        lines = []

        # --- Tencent: real-time valuation ---
        try:
            tq = _tencent_quote([code])
            if code in tq:
                q = tq[code]
                lines.extend(
                    [
                        f"Name: {q['name']}",
                        f"Price: {q['price']}",
                        f"PE (TTM): {q['pe_ttm']}",
                        f"PE (Static): {q['pe_static']}",
                        f"PB: {q['pb']}",
                        f"Market Cap (100M CNY): {q['mcap_yi']}",
                        f"Float Market Cap (100M CNY): {q['float_mcap_yi']}",
                        f"Turnover Rate: {q['turnover_pct']}%",
                        f"Change: {q['change_pct']}%",
                        f"Limit Up: {q['limit_up']}",
                        f"Limit Down: {q['limit_down']}",
                    ]
                )
        except Exception as e:
            logger.warning("Tencent quote failed for %s: %s", code, e)

        # --- mootdx: financial snapshot (quarterly) ---
        try:
            client = _get_mootdx_client()
            fin = client.finance(symbol=code)
            if fin is not None and not (
                isinstance(fin, pd.DataFrame) and fin.empty
            ):
                row = fin.iloc[0] if isinstance(fin, pd.DataFrame) else fin
                field_map = {
                    "eps": "EPS (Quarterly)",
                    "bvps": "Book Value Per Share",
                    "roe": "ROE (%)",
                    "profit": "Net Profit",
                    "income": "Revenue",
                    "liutongguben": "Float Shares",
                    "zongguben": "Total Shares",
                }
                idx = row.index if hasattr(row, "index") else []
                for field, label in field_map.items():
                    if field in idx:
                        val = row[field]
                        if val is not None and str(val) != "nan":
                            lines.append(f"{label}: {val}")
        except Exception as e:
            logger.warning("mootdx finance failed for %s: %s", code, e)

        # --- Eastmoney push2: basic stock info (direct HTTP) ---
        try:
            market_code = 1 if code.startswith("6") else 0
            _info_url = "https://push2.eastmoney.com/api/qt/stock/get"
            _info_params = {
                "fltt": "2",
                "invt": "2",
                "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43",
                "secid": f"{market_code}.{code}",
            }
            r = _em_get(_info_url, params=_info_params, timeout=10)
            d = r.json().get("data", {})
            if d:
                if d.get("f127"):
                    lines.append(f"行业: {d['f127']}")
                if d.get("f84"):
                    lines.append(f"总股本: {d['f84']}")
                if d.get("f85"):
                    lines.append(f"流通股本: {d['f85']}")
                if d.get("f116"):
                    lines.append(f"总市值: {d['f116']}")
                if d.get("f117"):
                    lines.append(f"流通市值: {d['f117']}")
                if d.get("f189"):
                    lines.append(f"上市日期: {d['f189']}")
        except Exception as e:
            logger.warning("eastmoney push2 stock info failed for %s: %s", code, e)

        # --- 同花顺 direct HTTP: consensus EPS forecast ---
        try:
            forecast_df = _ths_eps_forecast(code)
            if forecast_df is not None and not forecast_df.empty:
                lines.append("\n--- Consensus EPS Forecast (同花顺) ---")
                eps_by_year = {}
                for _, row in forecast_df.iterrows():
                    year = str(row.iloc[0]) if len(row) > 0 else ""
                    mean_eps_val = row.iloc[3] if len(row) > 3 else 0
                    count_val = row.iloc[1] if len(row) > 1 else 0
                    min_eps_val = row.iloc[2] if len(row) > 2 else "N/A"
                    max_eps_val = row.iloc[4] if len(row) > 4 else "N/A"
                    try:
                        mean_eps = float(mean_eps_val)
                    except (ValueError, TypeError):
                        mean_eps = 0
                    try:
                        count = int(count_val)
                    except (ValueError, TypeError):
                        count = 0
                    lines.append(
                        f"FY{year}: EPS={mean_eps} "
                        f"(range {min_eps_val}~{max_eps_val}, {count} analysts)"
                    )
                    if count < 3:
                        lines.append("  Warning: low coverage (<3 analysts)")
                    eps_by_year[year] = mean_eps

                # Forward PE / PEG / PE digestion
                try:
                    tq = _tencent_quote([code])
                    if code in tq:
                        price = tq[code]["price"]
                        years_sorted = sorted(eps_by_year.keys())
                        if years_sorted and eps_by_year.get(years_sorted[0], 0) > 0:
                            eps_cur = eps_by_year[years_sorted[0]]
                            fwd_pe = price / eps_cur
                            lines.append(
                                f"\nForward PE (FY{years_sorted[0]}): "
                                f"{fwd_pe:.1f}x (price={price}, EPS={eps_cur})"
                            )
                            if (
                                len(years_sorted) >= 2
                                and eps_by_year.get(years_sorted[1], 0) > 0
                            ):
                                eps_next = eps_by_year[years_sorted[1]]
                                cagr = eps_next / eps_cur - 1
                                if cagr > 0:
                                    peg = fwd_pe / (cagr * 100)
                                    lines.append(
                                        f"PEG: {peg:.2f} "
                                        f"(EPS CAGR={cagr * 100:.0f}%)"
                                    )
                                    if fwd_pe > 30:
                                        digest = math.log(fwd_pe / 30) / math.log(
                                            1 + cagr
                                        )
                                        lines.append(
                                            f"PE Digestion to 30x: {digest:.1f} years"
                                        )
                                    else:
                                        lines.append("PE already below 30x target")
                                else:
                                    lines.append(
                                        f"EPS declining ({cagr * 100:.0f}%), "
                                        f"PEG not applicable"
                                    )
                except Exception as e:
                    logger.warning("Forward PE calc failed for %s: %s", code, e)
        except Exception as e:
            logger.warning("Consensus EPS forecast failed for %s: %s", code, e)

        if not lines:
            return f"No fundamentals data found for A-stock '{code}'"

        header = f"# Company Fundamentals for {code} (A-stock)\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + "\n".join(lines)

    except Exception as e:
        return f"Error retrieving fundamentals for {code}: {str(e)}"


# ---- 4. get_balance_sheet ----


def _sina_stock_code(code: str) -> str:
    """Pure 6-digit code → sina format (sh688017 / sz000001 / bj832000)."""
    return f"{_get_prefix(code)}{code}"


def _get_financial_report_sina(
    code: str, report_type: str, freq: str, curr_date: str = None,
) -> pd.DataFrame:
    """Shared helper: fetch financial report via Sina direct HTTP API.

    report_type: '资产负债表' | '利润表' | '现金流量表'

    V3.2.2: Fixed parsing for report_list structure. Sina actually returns
    result.data.report_list as a dict keyed by period (e.g. '20260331'),
    where each period's data field is a list of items with item_title/item_value.
    """
    _report_type_map = {
        "资产负债表": "fzb",
        "利润表": "lrb",
        "现金流量表": "llb",
    }
    source_type = _report_type_map.get(report_type, "lrb")

    prefix = "sh" if code.startswith("6") else "sz"
    paper_code = f"{prefix}{code}"
    url = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"
    params = {
        "paperCode": paper_code,
        "source": source_type,
        "type": "0",
        "page": "1",
        "num": "20",
    }
    r = _requests.get(url, params=params, headers={"User-Agent": _UA}, timeout=15)
    d = r.json()

    # V3.2.2: Sina structure is result.data.report_list (dict keyed by period)
    report_list = (
        d.get("result", {}).get("data", {}).get("report_list", {}) or {}
    )
    if not report_list:
        return pd.DataFrame()

    # Parse each period's items into rows
    rows = []
    for period in sorted(report_list.keys(), reverse=True)[:20]:
        obj = report_list[period]
        rec = {"报告日": f"{period[:4]}-{period[4:6]}-{period[6:8]}"}
        for it in obj.get("data", []) or []:
            title = it.get("item_title", "")
            if not title or it.get("item_value") is None:
                continue
            rec[title] = it.get("item_value")
            tongbi = it.get("item_tongbi")
            if tongbi not in (None, ""):
                rec[f"{title}_同比"] = tongbi
        rows.append(rec)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Filter by curr_date
    if curr_date and "报告日" in df.columns:
        df["报告日"] = pd.to_datetime(df["报告日"], errors="coerce")
        cutoff = pd.to_datetime(curr_date)
        df = df[df["报告日"] <= cutoff]

    # Filter by frequency (annual = month 12 reports only)
    if freq.lower() == "annual" and "报告日" in df.columns:
        months = pd.to_datetime(df["报告日"], errors="coerce").dt.month
        df = df[months == 12]

    return df.head(8)


def get_balance_sheet(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get balance sheet via Sina direct HTTP API."""
    code = _normalize_ticker(ticker)

    try:
        df = _get_financial_report_sina(code, "资产负债表", freq, curr_date)

        if df.empty:
            return f"No balance sheet data found for A-stock '{code}'"

        csv_string = df.to_csv(index=False)

        header = f"# Balance Sheet for {code} (A-stock, {freq})\n"
        header += "# Data source: sina direct HTTP\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        return f"Error retrieving balance sheet for {code}: {str(e)}"


# ---- 5. get_cashflow ----


def get_cashflow(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get cash flow statement via Sina direct HTTP API."""
    code = _normalize_ticker(ticker)

    try:
        df = _get_financial_report_sina(code, "现金流量表", freq, curr_date)

        if df.empty:
            return f"No cash flow data found for A-stock '{code}'"

        csv_string = df.to_csv(index=False)

        header = f"# Cash Flow for {code} (A-stock, {freq})\n"
        header += "# Data source: sina direct HTTP\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        return f"Error retrieving cash flow for {code}: {str(e)}"


# ---- 6. get_income_statement ----


def get_income_statement(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get income statement via Sina direct HTTP API."""
    code = _normalize_ticker(ticker)

    try:
        df = _get_financial_report_sina(code, "利润表", freq, curr_date)

        if df.empty:
            return f"No income statement data found for A-stock '{code}'"

        csv_string = df.to_csv(index=False)

        header = f"# Income Statement for {code} (A-stock, {freq})\n"
        header += "# Data source: sina direct HTTP\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        return header + csv_string

    except Exception as e:
        return f"Error retrieving income statement for {code}: {str(e)}"


# ---- 7. get_news ----


def _fetch_news_eastmoney(code: str, page_size: int = 20) -> list[dict]:
    """Direct East Money search API for individual stock news."""
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    inner_param = {
        "uid": "",
        "keyword": code,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": page_size,
                "preTag": "",
                "postTag": "",
            }
        },
    }
    params = {
        "cb": "callback",
        "param": _json.dumps(inner_param, ensure_ascii=False),
        "_": "1",
    }
    headers = {
        "Referer": "https://so.eastmoney.com/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
    }

    resp = _em_get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    text = resp.text
    text = text[text.index("(") + 1 : text.rindex(")")]
    data = _json.loads(text)

    articles: list[dict] = []
    for item in data.get("result", {}).get("cmsArticleWebOld", []):
        articles.append({
            "title": item.get("title", ""),
            "content": item.get("content", ""),
            "time": item.get("date", ""),
            "source": item.get("mediaName", "东方财富"),
            "url": item.get("url", ""),
        })
    return articles


def _fetch_news_sina(code: str, page_size: int = 20) -> list[dict]:
    """Sina Finance stock news API (backup source)."""
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    url = (
        f"https://vip.stock.finance.sina.com.cn/corp/view/"
        f"vCB_AllNewsStock.php?symbol={prefix}{code}&Page=1"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
        "Referer": "https://finance.sina.com.cn/",
    }

    resp = _requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    resp.encoding = "gb2312"
    html = resp.text

    articles: list[dict] = []
    rows = _re.findall(
        r"(\d{4}-\d{2}-\d{2})\s*(?:&nbsp;)*(\d{2}:\d{2})\s*(?:&nbsp;)*"
        r"<a[^>]+href='([^']+)'[^>]*>([^<]+)</a>",
        html,
    )
    for date_str, time_str, link, title in rows[:page_size]:
        articles.append({
            "title": title.strip(),
            "content": "",
            "time": f"{date_str} {time_str}",
            "source": "新浪财经",
            "url": link,
        })
    return articles


def get_news(
    ticker: Annotated[str, "A-stock code"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Get stock-specific news via East Money direct API (Sina as fallback)."""
    code = _normalize_ticker(ticker)

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    articles: list[dict] = []
    source_label = ""

    try:
        articles = _fetch_news_eastmoney(code)
        source_label = "东方财富"
    except Exception as e:
        logger.warning("East Money news fetch failed for %s: %s", code, e)

    if not articles:
        try:
            articles = _fetch_news_sina(code)
            source_label = "新浪财经"
        except Exception as e:
            logger.warning("Sina news fetch failed for %s: %s", code, e)

    if not articles:
        return f"No news found for A-stock '{code}'"

    news_str = ""
    count = 0
    for art in articles:
        pub_time = art.get("time", "")
        try:
            pub_dt = datetime.strptime(pub_time[:10], "%Y-%m-%d")
            if pub_dt < start_dt or pub_dt > end_dt:
                continue
        except (ValueError, IndexError):
            pass

        title = art["title"]
        content = art.get("content", "")
        source = art.get("source", source_label)
        link = art.get("url", "")

        news_str += f"### {title} (source: {source})\n"
        if content:
            snippet = content[:300] + "..." if len(content) > 300 else content
            news_str += f"{snippet}\n"
        if link and link != "nan":
            news_str += f"Link: {link}\n"
        news_str += "\n"
        count += 1

    if count == 0:
        return (
            f"No news found for A-stock '{code}' "
            f"between {start_date} and {end_date}"
        )

    return (
        f"## {code} (A-stock) News, from {start_date} to {end_date}:\n\n"
        + news_str
    )


# ---- 8. get_global_news ----


def get_global_news(
    curr_date: Annotated[str, "Current date yyyy-mm-dd"],
    look_back_days: Annotated[int, "Days to look back"] = 7,
    limit: Annotated[int, "Max articles"] = 10,
) -> str:
    """Get China/global financial news via Eastmoney global news (direct HTTP).

    V3.2.2: CLS wire (财联社) API is offline since 2026-05 (cls.cn migrated
    to Next.js, old API returns 404). Now only uses Eastmoney 7x24 news.
    """
    start_dt = datetime.strptime(curr_date, "%Y-%m-%d") - relativedelta(
        days=look_back_days
    )
    start_date = start_dt.strftime("%Y-%m-%d")

    all_news: list[dict] = []

    # Source: Eastmoney global (东财7x24资讯) — direct HTTP (cls.cn offline)
    try:
        import uuid as _uuid

        em_url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
        em_params = {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": str(limit),
            "req_trace": str(_uuid.uuid4()),
        }
        em_headers = {"User-Agent": _UA, "Referer": "https://kuaixun.eastmoney.com/"}
        r_em = _em_get(em_url, params=em_params, headers=em_headers, timeout=10)
        d_em = r_em.json()
        for item in d_em.get("data", {}).get("fastNewsList", []):
            title = item.get("title", "")
            summary = item.get("summary", "")[:200]
            pub_time = item.get("showTime", "")
            all_news.append({
                "title": title,
                "content": summary,
                "time": pub_time,
                "source": "Eastmoney Global",
            })
    except Exception as e:
        logger.warning("Eastmoney global news fetch failed: %s", e)

    if not all_news:
        return f"No global news found for {curr_date}"

    # Deduplicate by title
    seen: set[str] = set()
    unique: list[dict] = []
    for n in all_news:
        if n["title"] not in seen:
            seen.add(n["title"])
            unique.append(n)

    news_str = ""
    for n in unique[:limit]:
        news_str += f"### {n['title']} (source: {n['source']})\n"
        if n.get("content"):
            snippet = (
                n["content"][:300] + "..."
                if len(n["content"]) > 300
                else n["content"]
            )
            news_str += f"{snippet}\n"
        news_str += "\n"

    return (
        f"## China & Global Market News, from {start_date} to {curr_date}:\n\n"
        + news_str
    )


# ---- 9. get_insider_transactions ----


def get_insider_transactions(
    ticker: Annotated[str, "A-stock code"],
) -> str:
    """Get shareholder/insider activity via mootdx F10.

    Note: A-stock insider transaction data differs from US markets.
    Uses mootdx F10 shareholder research as the closest equivalent.
    """
    code = _normalize_ticker(ticker)

    try:
        client = _get_mootdx_client()
        text = client.F10(symbol=code, name="股东研究")

        if not text or not text.strip():
            return f"No insider/shareholder data found for A-stock '{code}'"

        header = f"# Shareholder Research for {code} (A-stock)\n"
        header += "# Note: A-stock equivalent of insider transactions\n"
        header += "# Data source: mootdx F10\n"
        header += (
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        import re

        sec4_hits = list(re.finditer(r"\r?\n【4\.股东变化】\r?\n", text))
        if sec4_hits:
            sec4_pos = sec4_hits[-1].start()
            before_sec4 = text[:sec4_pos]
            sec4_text = text[sec4_pos:]
            cut_at = 2000
            if len(sec4_text) > cut_at:
                sec4_text = (
                    sec4_text[:cut_at]
                    + "\n\n(... older shareholder history omitted, "
                    f"{len(text) - sec4_pos - cut_at} chars truncated ...)"
                )
            text = before_sec4 + sec4_text

        return header + text

    except Exception as e:
        return f"Error retrieving insider/shareholder data for {code}: {str(e)}"


# ---- 10. get_profit_forecast ----


def get_profit_forecast(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "current date (unused, for interface compat)"] = None,
) -> str:
    """Get consensus EPS forecasts with forward valuation (同花顺 direct HTTP)."""
    code = _normalize_ticker(ticker)

    try:
        df = _ths_eps_forecast(code)

        if df is None or df.empty:
            return f"No analyst coverage found for A-stock '{code}'"

        lines = [
            f"# Consensus EPS Forecast for {code} (A-stock)",
            f"# Source: 同花顺 analyst consensus (direct HTTP)",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        eps_by_year = {}
        for _, row in df.iterrows():
            year = str(row.iloc[0]) if len(row) > 0 else ""
            count_val = row.iloc[1] if len(row) > 1 else 0
            mean_eps_val = row.iloc[3] if len(row) > 3 else 0
            min_eps_val = row.iloc[2] if len(row) > 2 else "N/A"
            max_eps_val = row.iloc[4] if len(row) > 4 else "N/A"
            try:
                count = int(count_val)
            except (ValueError, TypeError):
                count = 0
            try:
                mean_eps = float(mean_eps_val)
            except (ValueError, TypeError):
                mean_eps = 0
            lines.append(
                f"FY{year}: EPS={mean_eps} (range {min_eps_val}~{max_eps_val}), "
                f"analysts={count}"
            )
            if count < 3:
                lines.append("  Warning: low coverage (<3 analysts)")
            eps_by_year[year] = mean_eps

        # Forward valuation
        try:
            tq = _tencent_quote([code])
            if code in tq:
                price = tq[code]["price"]
                pe_ttm = tq[code]["pe_ttm"]
                lines.append(f"\nCurrent: price={price}, PE(TTM)={pe_ttm}")

                years_sorted = sorted(eps_by_year.keys())
                if years_sorted and eps_by_year.get(years_sorted[0], 0) > 0:
                    eps_cur = eps_by_year[years_sorted[0]]
                    fwd_pe = price / eps_cur
                    lines.append(
                        f"Forward PE (FY{years_sorted[0]}): {fwd_pe:.1f}x"
                    )
                    if (
                        len(years_sorted) >= 2
                        and eps_by_year.get(years_sorted[1], 0) > 0
                    ):
                        eps_next = eps_by_year[years_sorted[1]]
                        cagr = eps_next / eps_cur - 1
                        if cagr > 0:
                            peg = fwd_pe / (cagr * 100)
                            lines.append(
                                f"PEG: {peg:.2f} (CAGR={cagr * 100:.0f}%)"
                            )
                            if fwd_pe > 30:
                                digest = math.log(fwd_pe / 30) / math.log(
                                    1 + cagr
                                )
                                lines.append(
                                    f"PE Digestion to 30x: {digest:.1f} years"
                                )
                        else:
                            lines.append(
                                f"EPS declining ({cagr * 100:.0f}%), "
                                f"PEG not applicable"
                            )
        except Exception as e:
            logger.warning("Forward PE calc failed for %s: %s", code, e)

        return "\n".join(lines)

    except Exception as e:
        return f"Error retrieving profit forecast for {code}: {str(e)}"


# ---- 11. get_hot_stocks ----


def get_hot_stocks(
    curr_date: Annotated[str, "Date YYYY-MM-DD, empty string for today"] = "",
) -> str:
    """Get strong stocks with topic attribution from 同花顺 editorial team.

    Returns stocks that hit limit-up with human-curated reason tags
    explaining WHY they surged (e.g. '算力租赁+AI政务').
    """
    import requests

    if not curr_date or curr_date.strip() == "":
        curr_date = datetime.now().strftime("%Y-%m-%d")

    try:
        url = (
            f"http://zx.10jqka.com.cn/event/api/getharden/"
            f"date/{curr_date}/orderby/date/orderway/desc/charset/GBK/"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "Chrome/117.0.0.0 Safari/537.36"
            )
        }
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()

        if data.get("errocode", 0) != 0:
            return f"同花顺 API error: {data.get('errormsg', 'unknown')}"

        rows = data.get("data") or []
        if not rows:
            return (
                f"No hot stocks data for {curr_date} "
                f"(may be non-trading day or data not yet available)"
            )

        lines = [
            f"# Hot Stocks with Topic Attribution ({curr_date})",
            f"# Source: 同花顺 editorial (human-curated reason tags)",
            f"# Total: {len(rows)} stocks",
            "",
        ]

        from collections import Counter

        all_tags: list[str] = []

        for row in rows:
            code = row.get("code", "")
            name = row.get("name", "")
            reason = row.get("reason", "")
            zhangfu = row.get("zhangfu", "")
            huanshou = row.get("huanshou", "")
            chengjiaoe = row.get("chengjiaoe", "")
            dde = row.get("ddejingliang", "")

            lines.append(
                f"{code} {name}: +{zhangfu}% "
                f"换手{huanshou}% 成交额{chengjiaoe} "
                f"大单净量{dde} | {reason}"
            )

            if reason:
                tags = [t.strip() for t in str(reason).split("+") if t.strip()]
                all_tags.extend(tags)

        if all_tags:
            cnt = Counter(all_tags)
            lines.append(f"\n## Theme Frequency (top 15)")
            for tag, n in cnt.most_common(15):
                lines.append(f"  {tag}: {n} stocks")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching hot stocks for {curr_date}: {str(e)}"


# ---- 12. get_northbound_flow ----


def _northbound_cache_path() -> str:
    """Path to local CSV cache for northbound daily close snapshots."""
    from .config import get_config

    config = get_config()
    cache_dir = config.get(
        "data_cache_dir", os.path.expanduser("~/.tradingagents/cache")
    )
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "northbound_daily.csv")


def _save_northbound_snapshot(date_str: str, hgt: float, sgt: float) -> None:
    """Append today's northbound close to local CSV cache (dedup by date)."""
    import csv

    path = _northbound_cache_path()
    existing: dict[str, tuple[str, str]] = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) >= 3:
                    existing[row[0]] = (row[1], row[2])
    existing[date_str] = (f"{hgt:.2f}", f"{sgt:.2f}")
    sorted_dates = sorted(existing.keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "hgt", "sgt"])
        for d in sorted_dates:
            writer.writerow([d, existing[d][0], existing[d][1]])


def _load_northbound_history(n: int = 20) -> list[tuple[str, float, float]]:
    """Load last N days of northbound close data from local cache."""
    import csv

    path = _northbound_cache_path()
    if not os.path.exists(path):
        return []
    rows: list[tuple[str, float, float]] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 3:
                try:
                    rows.append((row[0], float(row[1]), float(row[2])))
                except ValueError:
                    continue
    return rows[-n:]


def get_northbound_flow(
    curr_date: Annotated[str, "Date YYYY-MM-DD"],
    include_history: Annotated[
        bool, "Include historical daily data (last 20 trading days)"
    ] = False,
) -> str:
    """Get northbound capital flow (沪深股通) from 同花顺 hsgtApi.

    Realtime: minute-level cumulative net buying for HGT(沪股通) + SGT(深股通).
    History: self-cached daily close snapshots (upstream APIs stopped updating
    northbound history since 2024-08).
    """
    import requests

    hsgt_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "Chrome/117.0.0.0 Safari/537.36"
        ),
        "Host": "data.hexin.cn",
        "Referer": "https://data.hexin.cn/",
    }

    lines = [
        f"# Northbound Capital Flow ({curr_date})",
        "# Source: 同花顺 hsgtApi (沪深股通) + local cache",
        "",
    ]

    hgt_close = 0.0
    sgt_close = 0.0
    got_realtime = False

    try:
        url_rt = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
        r = requests.get(url_rt, headers=hsgt_headers, timeout=10)
        d = r.json()

        times = d.get("time", [])
        hgt = d.get("hgt", [])
        sgt = d.get("sgt", [])

        if times:
            lines.append("## Realtime (cumulative net buying, 亿元)")
            n = len(times)
            start_idx = max(0, n - 10)
            for i in range(start_idx, n):
                t = times[i]
                h = hgt[i] if i < len(hgt) else "N/A"
                s = sgt[i] if i < len(sgt) else "N/A"
                lines.append(f"  {t}: HGT={h} SGT={s}")

            hgt_close = float(hgt[-1]) if hgt else 0
            sgt_close = float(sgt[-1]) if sgt else 0
            total = hgt_close + sgt_close
            lines.append(
                f"\nClose: HGT(沪股通)={hgt_close:.2f}亿 "
                f"SGT(深股通)={sgt_close:.2f}亿 "
                f"Total={total:.2f}亿"
            )
            if total > 0:
                lines.append("Signal: Net northbound INFLOW (bullish)")
            elif total < 0:
                lines.append("Signal: Net northbound OUTFLOW (bearish)")
            got_realtime = True
        else:
            lines.append("No realtime data (non-trading hours or holiday)")

        if got_realtime:
            today_str = datetime.now().strftime("%Y-%m-%d")
            _save_northbound_snapshot(today_str, hgt_close, sgt_close)

        if include_history:
            history = _load_northbound_history(20)
            if history:
                lines.append("\n## Historical Daily Close (local cache, 亿元)")
                lines.append("Date       | HGT(沪股通) | SGT(深股通) | Total")
                for date, h, s in history:
                    lines.append(f"  {date}: HGT={h:.2f} SGT={s:.2f} Total={h + s:.2f}")
                avg_total = sum(h + s for _, h, s in history) / len(history)
                lines.append(
                    f"\n{len(history)}-day avg net flow: {avg_total:.2f}亿"
                )
                if got_realtime:
                    today_total = hgt_close + sgt_close
                    diff = today_total - avg_total
                    lines.append(
                        f"Today vs avg: {'+' if diff >= 0 else ''}{diff:.2f}亿 "
                        f"({'above' if diff >= 0 else 'below'} average)"
                    )
            else:
                lines.append(
                    "\n## Historical Daily: No cached data yet. "
                    "History accumulates automatically with each call."
                )

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching northbound flow: {str(e)}"


# ---------------------------------------------------------------------------
# Concept/Sector Blocks — 东财 slist (replaces deprecated Baidu PAE)
# V3.2.2: Baidu PAE getrelatedblock returns ResultCode 10003, use 东财 slist
# ---------------------------------------------------------------------------


# ---- 13. get_concept_blocks ----


def get_concept_blocks(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
) -> str:
    """Get concept/sector/region blocks that a stock belongs to (东财 slist).

    V3.2.2: Replaced Baidu PAE getrelatedblock (ResultCode 10003 + empty array)
    with 东财 slist API (spt=3). One request gets ALL blocks (industry + concept
    + region mixed), with BK codes, change_pct, and lead stocks.

    Returns industry classification, concept themes, and region.
    Each block includes current day's change percentage.
    """
    code = _normalize_ticker(ticker)

    try:
        market_code = 1 if code.startswith("6") else 0
        url = "https://push2.eastmoney.com/api/qt/slist/get"
        params = {
            "fltt": "2",
            "invt": "2",
            "secid": f"{market_code}.{code}",
            "spt": "3",
            "pi": "0",
            "pz": "200",
            "po": "1",
            "fields": "f12,f14,f3,f128",
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://quote.eastmoney.com/",
        }
        r = _em_get(url, params=params, headers=headers, timeout=15)
        d = r.json()

        diff = (d.get("data") or {}).get("diff") or {}
        items = diff.values() if isinstance(diff, dict) else diff

        if not items:
            return f"No concept/block data for {code}"

        lines = [
            f"# Concept & Sector Blocks for {code} (A-stock)",
            f"# Source: 东财 slist (V3.2.2, replaces Baidu PAE)",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "Board Name | BK Code | Change % | Lead Stock",
            "--- | --- | --- | ---",
        ]

        concept_names: list[str] = []

        for it in items:
            name = it.get("f14", "")
            bk_code = it.get("f12", "")
            change_pct = it.get("f3", "")
            lead_stock = it.get("f128", "")
            lines.append(f"{name} | {bk_code} | {change_pct}% | {lead_stock}")
            if name:
                concept_names.append(name)

        if concept_names:
            lines.append(f"\nConcept tags: {' / '.join(concept_names)}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching concept blocks for {code}: {str(e)}"


# ---- 14. get_fund_flow ----


def get_fund_flow(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "Date YYYY-MM-DD"],
    include_history: Annotated[
        bool, "Include historical daily fund flow (last 20 days)"
    ] = True,
) -> str:
    """Get individual stock fund flow from 东财 push2.

    Realtime: minute-level main/large/medium/small/super order net inflow.
    History: daily net inflow for 20 trading days (push2his).

    V0.2.7: replaced 百度 PAE (fundflow/fundsortlist, offline since 2026-05)
    with 东财 push2 fund flow API.
    """
    code = _normalize_ticker(ticker)
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    lines = [
        f"# Fund Flow for {code} (A-stock)",
        f"# Source: 东财 push2 (Eastmoney)",
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    try:
        # Realtime minute-level fund flow
        url_rt = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
        params_rt = {
            "secid": secid, "klt": 1,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
        }
        r = _em_get(url_rt, params=params_rt, timeout=10)
        d = r.json()
        klines = d.get("data", {}).get("klines", [])

        if klines:
            lines.append(
                "## Realtime Minute Flow "
                "(主力/小单/中单/大单/超大单 净流入, 元)"
            )
            for line in klines[-10:]:
                parts = line.split(",")
                if len(parts) >= 6:
                    lines.append(
                        f"  {parts[0]}: "
                        f"主力={float(parts[1])/1e4:.0f}万 "
                        f"大单={float(parts[4])/1e4:.0f}万 "
                        f"超大单={float(parts[5])/1e4:.0f}万"
                    )

            last_parts = klines[-1].split(",")
            if len(last_parts) >= 2:
                main_net = float(last_parts[1])
                lines.append(
                    f"\nClose: 主力净流入={main_net/1e4:.0f}万元"
                )
                if main_net > 0:
                    lines.append(
                        "Signal: Net main force INFLOW (bullish)"
                    )
                elif main_net < 0:
                    lines.append(
                        "Signal: Net main force OUTFLOW (bearish)"
                    )
        else:
            lines.append(
                "No realtime fund flow (non-trading hours or holiday)"
            )

        # Historical daily fund flow (push2his)
        if include_history:
            url_hist = (
                "https://push2his.eastmoney.com"
                "/api/qt/stock/fflow/daykline/get"
            )
            params_hist = {
                "secid": secid, "lmt": 120, "klt": 101,
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57",
            }
            rh = _em_get(url_hist, params=params_hist, timeout=10)
            dh = rh.json()
            hist_klines = dh.get("data", {}).get("klines", [])

            if hist_klines:
                lines.append(
                    f"\n## Historical Daily Fund Flow "
                    f"(last {len(hist_klines)} trading days)"
                )
                lines.append(
                    "Date | 主力净流入(万) | 大单(万) "
                    "| 中单(万) | 小单(万) | 超大单(万)"
                )
                for line in hist_klines:
                    parts = line.split(",")
                    if len(parts) >= 6:
                        lines.append(
                            f"  {parts[0]} "
                            f"| main={float(parts[1])/1e4:.0f} "
                            f"| large={float(parts[4])/1e4:.0f} "
                            f"| mid={float(parts[3])/1e4:.0f} "
                            f"| small={float(parts[2])/1e4:.0f} "
                            f"| super={float(parts[5])/1e4:.0f}"
                        )

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching fund flow for {code}: {str(e)}"


# ---------------------------------------------------------------------------
# 15. Dragon Tiger Board (龙虎榜)
# ---------------------------------------------------------------------------

def get_dragon_tiger_board(
    ticker: str,
    trade_date: str,
    look_back_days: int = 30,
) -> str:
    """Get dragon-tiger board (龙虎榜) appearances and seat details.

    Args:
        ticker: 6-digit A-share code, e.g. '000858'
        trade_date: YYYY-MM-DD
        look_back_days: how many days back to search (default 30)

    Returns:
        Formatted text with LHB appearances, top buyer/seller seats,
        and institutional activity.
    """
    code = safe_ticker_component(ticker)
    end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
    start_dt = end_dt - pd.Timedelta(days=look_back_days)
    start_date_str = start_dt.strftime("%Y-%m-%d")
    lines = [f"# 龙虎榜数据 | {code} | {trade_date} (近{look_back_days}日)"]

    # 1. 上榜记录 — eastmoney datacenter direct HTTP
    try:
        data = _eastmoney_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=(
                f"(TRADE_DATE>='{start_date_str}')"
                f"(TRADE_DATE<='{trade_date}')"
                f"(SECURITY_CODE=\"{code}\")"
            ),
            page_size=50,
            sort_columns="TRADE_DATE",
            sort_types="-1",
        )
        if not data:
            lines.append(f"\n近{look_back_days}日未上龙虎榜。")
        else:
            lines.append(f"\n## 上榜记录 ({len(data)} 次)")
            lines.append("日期 | 原因 | 净买入(万) | 换手率")
            for row in data:
                net_buy = round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1)
                turnover = round(float(row.get("TURNOVERRATE") or 0), 2)
                lines.append(
                    f"  {str(row.get('TRADE_DATE', ''))[:10]} "
                    f"| {row.get('EXPLANATION', '')} "
                    f"| {net_buy:.0f} "
                    f"| {turnover:.2f}%"
                )
    except Exception as e:
        lines.append(f"龙虎榜列表查询失败: {e}")

    # 2. 最近上榜的买卖席位 — eastmoney datacenter direct HTTP
    buy_data = []
    sell_data = []
    try:
        if data:
            latest_date = str(data[0].get("TRADE_DATE", ""))[:10]
            lines.append(f"\n## 最近上榜席位明细 ({latest_date})")

            # 买入席位
            buy_data = _eastmoney_datacenter(
                "RPT_BILLBOARD_DAILYDETAILSBUY",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10,
                sort_columns="BUY",
                sort_types="-1",
            )
            if buy_data:
                lines.append("\n### 买入席位 TOP5")
                lines.append("营业部 | 买入(万) | 卖出(万) | 净额(万)")
                for row in buy_data[:5]:
                    buy_amt = round((row.get("BUY") or 0) / 10000, 1)
                    sell_amt = round((row.get("SELL") or 0) / 10000, 1)
                    net = round((row.get("NET") or 0) / 10000, 1)
                    lines.append(
                        f"  {row.get('OPERATEDEPT_NAME', '')} "
                        f"| {buy_amt:.0f} | {sell_amt:.0f} | {net:.0f}"
                    )

            # 卖出席位
            sell_data = _eastmoney_datacenter(
                "RPT_BILLBOARD_DAILYDETAILSSELL",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10,
                sort_columns="SELL",
                sort_types="-1",
            )
            if sell_data:
                lines.append("\n### 卖出席位 TOP5")
                lines.append("营业部 | 买入(万) | 卖出(万) | 净额(万)")
                for row in sell_data[:5]:
                    buy_amt = round((row.get("BUY") or 0) / 10000, 1)
                    sell_amt = round((row.get("SELL") or 0) / 10000, 1)
                    net = round((row.get("NET") or 0) / 10000, 1)
                    lines.append(
                        f"  {row.get('OPERATEDEPT_NAME', '')} "
                        f"| {buy_amt:.0f} | {sell_amt:.0f} | {net:.0f}"
                    )
    except Exception:
        pass

    # 3. 机构动向 — 从买卖席位明细筛选机构专用席位 (OPERATEDEPT_CODE="0")
    try:
        inst_buy = 0.0
        inst_sell = 0.0
        for detail, side in [(buy_data, "buy"), (sell_data, "sell")]:
            for row in (detail or []):
                if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                    if side == "buy":
                        inst_buy += (row.get("BUY") or 0)
                    else:
                        inst_sell += (row.get("SELL") or 0)
        if inst_buy > 0 or inst_sell > 0:
            lines.append("\n## 机构动向")
            lines.append(
                f"  机构买入 {inst_buy/1e4:.0f} 万 "
                f"| 卖出 {inst_sell/1e4:.0f} 万 "
                f"| 净额 {(inst_buy - inst_sell)/1e4:.0f} 万"
            )
    except Exception:
        pass

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 16. Lockup Expiry Calendar (限售解禁日历)
# ---------------------------------------------------------------------------

def get_lockup_expiry(
    ticker: str,
    trade_date: str,
    forward_days: int = 90,
) -> str:
    """Get lockup expiry schedule for a stock.

    Args:
        ticker: 6-digit A-share code
        trade_date: YYYY-MM-DD
        forward_days: how many days forward to check (default 90)

    Returns:
        Formatted text with historical unlock records and upcoming
        expiry calendar with impact metrics.
    """
    code = safe_ticker_component(ticker)
    lines = [f"# 限售解禁日历 | {code} | {trade_date}"]

    # 1. 历史解禁记录 — eastmoney datacenter direct HTTP
    try:
        history_data = _eastmoney_datacenter(
            "RPT_LIFT_STAGE",
            filter_str=f"(SECURITY_CODE=\"{code}\")",
            page_size=15,
            sort_columns="FREE_DATE",
            sort_types="-1",
        )
        if history_data:
            lines.append(f"\n## 个股解禁记录 (共 {len(history_data)} 批)")
            lines.append("解禁时间 | 类型 | 解禁数量 | 占比")
            for row in history_data:
                lines.append(
                    f"  {str(row.get('FREE_DATE', ''))[:10]} "
                    f"| {row.get('LIMITED_STOCK_TYPE', '')} "
                    f"| {row.get('FREE_SHARES_NUM', '')} "
                    f"| {row.get('FREE_RATIO', '')}"
                )
        else:
            lines.append("\n无历史解禁记录。")
    except Exception as e:
        lines.append(f"个股解禁查询失败: {e}")

    # 2. 未来待解禁 — eastmoney datacenter direct HTTP
    try:
        end_dt = datetime.strptime(trade_date, "%Y-%m-%d") + pd.Timedelta(
            days=forward_days
        )
        end_str = end_dt.strftime("%Y-%m-%d")
        upcoming_data = _eastmoney_datacenter(
            "RPT_LIFT_STAGE",
            filter_str=(
                f"(SECURITY_CODE=\"{code}\")"
                f"(FREE_DATE>='{trade_date}')"
                f"(FREE_DATE<='{end_str}')"
            ),
            page_size=20,
            sort_columns="FREE_DATE",
            sort_types="1",
        )
        if upcoming_data:
            lines.append(f"\n## 未来 {forward_days} 天待解禁")
            for row in upcoming_data:
                lines.append(
                    f"  {str(row.get('FREE_DATE', ''))[:10]} "
                    f"| {row.get('LIMITED_STOCK_TYPE', '')} "
                    f"| 数量 {row.get('FREE_SHARES_NUM', '')} "
                    f"| 占比 {row.get('FREE_RATIO', '')}"
                )
        else:
            lines.append(f"\n未来 {forward_days} 天无待解禁。")
    except Exception as e:
        lines.append(f"解禁日历查询失败: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 17. Industry Comparison (行业横向对比)
# ---------------------------------------------------------------------------

def get_industry_comparison(
    ticker: str,
    trade_date: str,
    top_n: int = 20,
) -> str:
    """Get industry sector performance comparison.

    Args:
        ticker: 6-digit A-share code (used to identify relevant sector)
        trade_date: YYYY-MM-DD
        top_n: number of top/bottom industries to show (default 20)

    Returns:
        Formatted text with sector performance ranking, highlighting
        the sector the target stock belongs to.
    """
    code = safe_ticker_component(ticker)
    lines = [f"# 行业横向对比 | {code} | {trade_date}"]

    # 东财 push2 行业板块排名 (direct HTTP, replaces 同花顺 which has 401)
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": "100",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fs": "m:90+t:2",
            "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
        }
        r = _em_get(url, params=params, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", [])

        if items:
            lines.append(
                f"\n## 全行业表现 (东财 {len(items)} 个行业)"
            )
            lines.append(
                "排名 | 行业 | 涨跌幅 | 上涨 | 下跌 | 领涨股"
            )
            for i, item in enumerate(items):
                name = item.get("f14", "")
                change_pct = item.get("f3", 0)
                up_count = item.get("f104", 0)
                down_count = item.get("f105", 0)
                leader = item.get("f140", "")
                lines.append(
                    f"  {i+1}. {name} "
                    f"| {change_pct}% "
                    f"| {up_count} "
                    f"| {down_count} "
                    f"| {leader}"
                )
                if i >= top_n * 2 - 1:
                    lines.append(f"  ... (showing top/bottom {top_n})")
                    break
        else:
            lines.append("行业数据获取为空。")
    except Exception as e:
        lines.append(f"行业对比查询失败: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 18. Margin Trading (融资融券明细) — V3.2.2 新增
# ---------------------------------------------------------------------------

def get_margin_trading(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
    page_size: Annotated[int, "Number of days to fetch (default 30)"] = 30,
) -> str:
    """Get margin trading data (融资融券明细).

    Returns daily margin balance, margin buying, short selling volumes.
    Rising margin balance = bullish leveraged conviction.
    Rising short selling = direct bearish bet.

    Data source: Eastmoney datacenter RPTA_WEB_RZRQ_GGMX.
    """
    code = _normalize_ticker(ticker)

    try:
        data = _eastmoney_datacenter(
            "RPTA_WEB_RZRQ_GGMX",
            filter_str=f'(SCODE="{code}")',
            page_size=page_size,
            sort_columns="DATE",
            sort_types="-1",
        )

        if not data:
            return f"No margin trading data for {code}"

        lines = [
            f"# 融资融券明细 | {code}",
            f"# Source: 东财 datacenter (RPTA_WEB_RZRQ_GGMX)",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "日期 | 融资余额(亿) | 融资买入(万) | 融券余额(亿) | 融券卖出(万股)",
            "--- | --- | --- | --- | ---",
        ]

        prev_rzye = None
        for row in data:
            date_str = str(row.get("DATE", ""))[:10]
            rzye = row.get("RZYE", 0) or 0
            rzmre = row.get("RZMRE", 0) or 0
            rqye = row.get("RQYE", 0) or 0
            rqmcl = row.get("RQMCL", 0) or 0

            # 计算融资余额环比变化
            change_str = ""
            if prev_rzye and prev_rzye > 0:
                change_pct = (rzye / prev_rzye - 1) * 100
                change_str = f" ({'+' if change_pct >= 0 else ''}{change_pct:.1f}%)"
            prev_rzye = rzye

            lines.append(
                f"  {date_str} "
                f"| {rzye/1e8:.2f}{change_str} "
                f"| {rzmre/1e4:.0f} "
                f"| {rqye/1e8:.4f} "
                f"| {rqmcl/1e4:.0f}"
            )

        # 趋势分析
        if len(data) >= 5:
            latest = data[0]
            earliest = data[-1]
            rzye_latest = latest.get("RZYE", 0) or 0
            rzye_earliest = earliest.get("RZYE", 0) or 0
            rqye_latest = latest.get("RQYE", 0) or 0
            rqye_earliest = earliest.get("RQYE", 0) or 0

            lines.append("")
            if rzye_earliest > 0:
                rz_change = (rzye_latest / rzye_earliest - 1) * 100
                lines.append(f"融资余额变化: {'+' if rz_change >= 0 else ''}{rz_change:.1f}% ({len(data)}日)")
                if rz_change > 5:
                    lines.append("Signal: 融资余额持续上升 → 多头杠杆加仓 (bullish)")
                elif rz_change < -5:
                    lines.append("Signal: 融资余额持续下降 → 多头去杠杆 (bearish)")

            if rqye_earliest > 0:
                rq_change = (rqye_latest / rqye_earliest - 1) * 100
                lines.append(f"融券余额变化: {'+' if rq_change >= 0 else ''}{rq_change:.1f}%")
                if rq_change > 10:
                    lines.append("Signal: 融券余额上升 → 空头加仓 (bearish)")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching margin trading for {code}: {str(e)}"


# ---------------------------------------------------------------------------
# 19. Block Trade (大宗交易) — V3.2.2 新增
# ---------------------------------------------------------------------------

def get_block_trade(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
    page_size: Annotated[int, "Number of records (default 20)"] = 20,
) -> str:
    """Get block trade records (大宗交易).

    Returns deal price, volume, buyer/seller broker names, premium/discount %.
    Block trades reveal institutional intent:
    - Premium (溢价) = motivated buyer
    - Discount (折价) = motivated seller (fund exit signal)

    Data source: Eastmoney datacenter RPT_DATA_BLOCKTRADE.
    """
    code = _normalize_ticker(ticker)

    try:
        data = _eastmoney_datacenter(
            "RPT_DATA_BLOCKTRADE",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=page_size,
            sort_columns="TRADE_DATE",
            sort_types="-1",
        )

        if not data:
            return f"No block trade data for {code}"

        lines = [
            f"# 大宗交易 | {code}",
            f"# Source: 东财 datacenter (RPT_DATA_BLOCKTRADE)",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "日期 | 成交价 | 收盘价 | 溢价% | 成交量(万股) | 成交额(万) | 买方 | 卖方",
            "--- | --- | --- | --- | --- | --- | --- | ---",
        ]

        discount_count = 0
        premium_count = 0
        for row in data:
            date_str = str(row.get("TRADE_DATE", ""))[:10]
            deal_price = row.get("DEAL_PRICE", 0) or 0
            close_price = row.get("CLOSE_PRICE", 0) or 0
            vol = row.get("DEAL_VOLUME", 0) or 0
            amount = row.get("DEAL_AMT", 0) or 0
            buyer = (row.get("BUYER_NAME", "") or "")[:15]
            seller = (row.get("SELLER_NAME", "") or "")[:15]

            # 计算溢价率
            premium_pct = 0
            if close_price and close_price > 0:
                premium_pct = (deal_price / close_price - 1) * 100

            if premium_pct < -1:
                discount_count += 1
            elif premium_pct > 1:
                premium_count += 1

            lines.append(
                f"  {date_str} "
                f"| {deal_price:.2f} "
                f"| {close_price:.2f} "
                f"| {'+' if premium_pct >= 0 else ''}{premium_pct:.2f}% "
                f"| {vol/1e4:.0f} "
                f"| {amount/1e4:.0f} "
                f"| {buyer} "
                f"| {seller}"
            )

        # 分析
        lines.append("")
        if discount_count > premium_count and discount_count >= 3:
            lines.append(
                f"⚠️ 近期 {discount_count} 笔折价大宗交易 → 机构出逃信号 (bearish)"
            )
        elif premium_count > discount_count and premium_count >= 3:
            lines.append(
                f"✅ 近期 {premium_count} 笔溢价大宗交易 → 机构抢筹信号 (bullish)"
            )
        else:
            lines.append(f"大宗交易折价{discount_count}笔 / 溢价{premium_count}笔")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching block trades for {code}: {str(e)}"


# ---------------------------------------------------------------------------
# 20. Shareholder Count Changes (股东户数变化) — V3.2.2 新增
# ---------------------------------------------------------------------------

def get_shareholder_count(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
    page_size: Annotated[int, "Number of quarters (default 10)"] = 10,
) -> str:
    """Get shareholder count changes (股东户数变化).

    Returns quarterly shareholder count, change ratio, avg shares per holder.
    Key signal: declining count + rising avg shares = chip concentration (筹码集中)
    = classic institutional accumulation pattern.

    Data source: Eastmoney datacenter RPT_HOLDERNUMLATEST.
    """
    code = _normalize_ticker(ticker)

    try:
        data = _eastmoney_datacenter(
            "RPT_HOLDERNUMLATEST",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=page_size,
            sort_columns="END_DATE",
            sort_types="-1",
        )

        if not data:
            return f"No shareholder count data for {code}"

        lines = [
            f"# 股东户数变化 | {code}",
            f"# Source: 东财 datacenter (RPT_HOLDERNUMLATEST)",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "日期 | 股东户数 | 变化 | 环比% | 户均持股(万股)",
            "--- | --- | --- | --- | ---",
        ]

        prev_count = None
        for row in data:
            date_str = str(row.get("END_DATE", ""))[:10]
            holder_num = row.get("HOLDER_NUM", 0) or 0
            change_num = row.get("HOLDER_NUM_CHANGE", 0) or 0
            change_ratio = row.get("HOLDER_NUM_RATIO", 0) or 0
            avg_shares = row.get("AVG_FREE_SHARES", 0) or 0

            change_str = f"{change_num:+d}" if change_num else "N/A"

            lines.append(
                f"  {date_str} "
                f"| {holder_num:,} "
                f"| {change_str} "
                f"| {change_ratio:+.1f}% "
                f"| {avg_shares/1e4:.2f}"
            )
            prev_count = holder_num

        # 趋势分析
        if len(data) >= 2:
            latest = data[0]
            earliest = data[-1]
            count_latest = latest.get("HOLDER_NUM", 0) or 0
            count_earliest = earliest.get("HOLDER_NUM", 0) or 0

            lines.append("")
            if count_earliest > 0:
                total_change = (count_latest / count_earliest - 1) * 100
                lines.append(
                    f"股东户数变化: {total_change:+.1f}% "
                    f"({count_earliest:,} → {count_latest:,})"
                )
                if total_change < -10:
                    lines.append(
                        "Signal: 股东户数持续减少 → 筹码集中，主力吸筹 (bullish)"
                    )
                elif total_change > 10:
                    lines.append(
                        "Signal: 股东户数持续增加 → 筹码分散，散户接盘 (bearish)"
                    )

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching shareholder count for {code}: {str(e)}"


# ---------------------------------------------------------------------------
# 21. Research Report List (研报列表) — V3.2.2 新增
# ---------------------------------------------------------------------------

_REPORT_API = "https://reportapi.eastmoney.com/report/list"


def get_research_reports(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
    max_pages: Annotated[int, "Max pages to fetch (default 2)"] = 2,
) -> str:
    """Get broker research reports with ratings and EPS forecasts.

    Returns: title, institution, rating (买入/增持/中性/减持), EPS forecasts.
    Key signals:
    - Rating distribution (买入 vs 增持 vs 中性)
    - Recent rating changes (downgrade = bearish)
    - EPS forecast trends

    Data source: Eastmoney reportapi (free, no key needed).
    """
    code = _normalize_ticker(ticker)
    all_records = []

    try:
        for page in range(1, max_pages + 1):
            params = {
                "industryCode": "*",
                "pageSize": "100",
                "industry": "*",
                "rating": "*",
                "ratingChange": "*",
                "beginTime": "2000-01-01",
                "endTime": "2030-01-01",
                "pageNo": str(page),
                "fields": "",
                "qType": "0",
                "orgCode": "",
                "code": code,
                "rcode": "",
                "p": str(page),
                "pageNum": str(page),
                "pageNumber": str(page),
            }
            r = _em_get(
                _REPORT_API,
                params=params,
                headers={"Referer": "https://data.eastmoney.com/"},
                timeout=30,
            )
            d = r.json()
            rows = d.get("data") or []
            if not rows:
                break
            all_records.extend(rows)
            if page >= (d.get("TotalPage", 1) or 1):
                break

        if not all_records:
            return f"No research reports found for {code}"

        lines = [
            f"# 研报列表 | {code}",
            f"# Source: 东财 reportapi (共 {len(all_records)} 篇)",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "日期 | 机构 | 评级 | 标题",
            "--- | --- | --- | ---",
        ]

        # 评级统计
        rating_counts: dict[str, int] = {}
        eps_forecasts: list[dict] = []

        for rec in all_records[:50]:  # 最近50篇
            date_str = str(rec.get("publishDate", ""))[:10]
            org = rec.get("orgSName", "")
            rating = rec.get("emRatingName", "")
            title = (rec.get("title", "") or "")[:60]

            rating_counts[rating] = rating_counts.get(rating, 0) + 1

            lines.append(f"  {date_str} | {org} | {rating} | {title}")

            # 收集 EPS 预测
            this_eps = rec.get("predictThisYearEps")
            next_eps = rec.get("predictNextYearEps")
            if this_eps:
                eps_forecasts.append({
                    "org": org,
                    "date": date_str,
                    "this_year": float(this_eps) if this_eps else 0,
                    "next_year": float(next_eps) if next_eps else 0,
                })

        # 评级分布
        lines.append("")
        lines.append("## 评级分布")
        for rating, count in sorted(rating_counts.items(), key=lambda x: -x[1]):
            if rating:
                lines.append(f"  {rating}: {count} 篇")

        # EPS 预测汇总
        if eps_forecasts:
            lines.append("")
            lines.append("## 机构 EPS 预测")
            avg_this = sum(e["this_year"] for e in eps_forecasts) / len(eps_forecasts)
            avg_next = sum(e["next_year"] for e in eps_forecasts) / len(eps_forecasts)
            lines.append(
                f"  今年一致预期 EPS: {avg_this:.4f} "
                f"(基于 {len(eps_forecasts)} 家机构)"
            )
            lines.append(
                f"  明年一致预期 EPS: {avg_next:.4f}"
            )
            if avg_this > 0:
                cagr = (avg_next / avg_this - 1) * 100
                lines.append(f"  EPS CAGR: {cagr:.1f}%")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching research reports for {code}: {str(e)}"


# ---------------------------------------------------------------------------
# 22. Dividend History (分红送转历史) — V3.2.2 新增
# ---------------------------------------------------------------------------

def get_dividend_history(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
    page_size: Annotated[int, "Number of records (default 10)"] = 10,
) -> str:
    """Get dividend and bonus share history (分红送转历史).

    Returns per-share cash dividend, bonus shares, transfer shares.
    Key signals:
    - Dividend yield calculation (missing from current system)
    - High bonus/transfer events (高送转 catalyst)

    Data source: Eastmoney datacenter RPT_SHAREBONUS_DET.
    """
    code = _normalize_ticker(ticker)

    try:
        data = _eastmoney_datacenter(
            "RPT_SHAREBONUS_DET",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=page_size,
            sort_columns="EX_DIVIDEND_DATE",
            sort_types="-1",
        )

        if not data:
            return f"No dividend history for {code}"

        lines = [
            f"# 分红送转历史 | {code}",
            f"# Source: 东财 datacenter (RPT_SHAREBONUS_DET)",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "除权日 | 每股派息(元) | 每10股送股 | 每10股转增 | 进度",
            "--- | --- | --- | --- | ---",
        ]

        total_dividend = 0
        for row in data:
            date_str = str(row.get("EX_DIVIDEND_DATE", ""))[:10]
            bonus_rmb = row.get("PRETAX_BONUS_RMB", 0) or 0
            bonus_ratio = row.get("BONUS_RATIO", 0) or 0
            transfer_ratio = row.get("TRANSFER_RATIO", 0) or 0
            progress = row.get("ASSIGN_PROGRESS", "") or ""

            total_dividend += bonus_rmb

            lines.append(
                f"  {date_str} "
                f"| {bonus_rmb:.4f} "
                f"| {bonus_ratio} "
                f"| {transfer_ratio} "
                f"| {progress}"
            )

        # 汇总
        lines.append("")
        if total_dividend > 0:
            lines.append(f"最近 {len(data)} 次累计每股派息: {total_dividend:.4f} 元")
        if any((row.get("BONUS_RATIO", 0) or 0) > 0 for row in data):
            lines.append("⚠️ 存在送股记录 (高送转题材)")
        if any((row.get("TRANSFER_RATIO", 0) or 0) > 0 for row in data):
            lines.append("⚠️ 存在转增记录 (高送转题材)")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching dividend history for {code}: {str(e)}"


# ---------------------------------------------------------------------------
# 23. Full Market Dragon Tiger (全市场龙虎榜) — V3.2.2 新增
# ---------------------------------------------------------------------------

def get_daily_dragon_tiger(
    trade_date: Annotated[str, "YYYY-MM-DD (default today)"] = "",
    min_net_buy: Annotated[float, "Min net buy in 万 (default no filter)"] = 0,
) -> str:
    """Get daily full-market dragon tiger board (全市场龙虎榜).

    Returns all stocks that hit the dragon tiger board on a given day,
    with reasons, net buy amounts, and turnover rates.

    Data source: Eastmoney datacenter RPT_DAILYBILLBOARD_DETAILSNEW.
    """
    if not trade_date or trade_date.strip() == "":
        trade_date = datetime.now().strftime("%Y-%m-%d")

    try:
        data = _eastmoney_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=(
                f"(TRADE_DATE>='{trade_date}')"
                f"(TRADE_DATE<='{trade_date}')"
            ),
            page_size=500,
            sort_columns="BILLBOARD_NET_AMT",
            sort_types="-1",
        )

        if not data:
            return f"无龙虎榜数据（非交易日或盘后未更新）| {trade_date}"

        actual_date = str(data[0].get("TRADE_DATE", ""))[:10]

        lines = [
            f"# 全市场龙虎榜 | {actual_date}",
            f"# Source: 东财 datacenter",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "代码 | 名称 | 原因 | 收盘价 | 涨跌% | 净买额(万) | 换手%",
            "--- | --- | --- | --- | --- | --- | ---",
        ]

        filtered = []
        for row in data:
            net_buy = (row.get("BILLBOARD_NET_AMT") or 0) / 10000
            if min_net_buy and net_buy < min_net_buy:
                continue
            filtered.append({
                "code": row.get("SECURITY_CODE", ""),
                "name": row.get("SECURITY_NAME_ABBR", ""),
                "reason": row.get("EXPLANATION", ""),
                "close": row.get("CLOSE_PRICE") or 0,
                "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
                "net_buy": round(net_buy, 1),
                "turnover": round(float(row.get("TURNOVERRATE") or 0), 2),
            })

        for s in filtered[:30]:
            lines.append(
                f"  {s['code']} | {s['name']} | {s['reason'][:30]} "
                f"| {s['close']} | {s['change_pct']}% "
                f"| {s['net_buy']} | {s['turnover']}%"
            )

        lines.append(f"\n共 {len(filtered)} 条记录")

        # 净买入 TOP5
        top5 = sorted(filtered, key=lambda x: -x["net_buy"])[:5]
        if top5 and top5[0]["net_buy"] > 0:
            lines.append("\n## 净买入 TOP5")
            for s in top5:
                lines.append(f"  {s['code']} {s['name']}: 净买{s['net_buy']}万 {s['reason'][:40]}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching daily dragon tiger: {str(e)}"


# ---------------------------------------------------------------------------
# 24. Northbound Stock Holdings (北向个股持仓) — V3.2.2 新增
# ---------------------------------------------------------------------------

def get_northbound_stock_holdings(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
) -> str:
    """Get northbound capital holdings for individual stock (北向个股持仓).

    Shows how much northbound (HK-SH/SZ) capital holds in a specific stock.
    Rising holdings = foreign institutional buying = bullish signal.

    Data source: Eastmoney datacenter RPT_MUTUAL_STOCK_NORTHSTA.
    """
    code = _normalize_ticker(ticker)

    try:
        data = _eastmoney_datacenter(
            "RPT_MUTUAL_STOCK_NORTHSTA",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=20,
            sort_columns="TRADE_DATE",
            sort_types="-1",
        )

        if not data:
            return f"No northbound holdings data for {code}"

        lines = [
            f"# 北向持仓 | {code}",
            f"# Source: 东财 datacenter (RPT_MUTUAL_STOCK_NORTHSTA)",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "日期 | 持股数(万股) | 持股市值(亿) | 持股占比% | 环比变化",
            "--- | --- | --- | --- | ---",
        ]

        prev_shares = None
        for row in data[:15]:
            date_str = str(row.get("TRADE_DATE", ""))[:10]
            shares = row.get("SHAREHOLDING_NUM", 0) or 0
            market_value = row.get("MUTUAL_MARKET_CAP", 0) or 0
            ratio = row.get("FREESHARES_RATIO", 0) or 0

            change_str = ""
            if prev_shares and prev_shares > 0:
                change_pct = (shares / prev_shares - 1) * 100
                change_str = f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}%"
            prev_shares = shares

            lines.append(
                f"  {date_str} "
                f"| {shares:.2f} "
                f"| {market_value/1e8:.2f} "
                f"| {ratio:.2f}% "
                f"| {change_str}"
            )

        # 趋势
        if len(data) >= 2:
            latest_shares = data[0].get("SHAREHOLDING_NUM", 0) or 0
            earliest_shares = data[-1].get("SHAREHOLDING_NUM", 0) or 0
            if earliest_shares > 0:
                change = (latest_shares / earliest_shares - 1) * 100
                lines.append(f"\n持仓变化: {change:+.1f}% ({len(data)}日)")
                if change > 5:
                    lines.append("Signal: 北向资金持续加仓 (bullish)")
                elif change < -5:
                    lines.append("Signal: 北向资金持续减仓 (bearish)")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching northbound holdings for {code}: {str(e)}"


# ---------------------------------------------------------------------------
# 25. cninfo Announcements (巨潮公告) — V3.2.2 新增
# ---------------------------------------------------------------------------

# ===========================================================================
# Phase 1: 短线交易数据基础设施
# 涨停/跌停获取、连板天数、市场宽度、北向资金信号、涨停原因归一化
# ===========================================================================


# ---------------------------------------------------------------------------
# P1-09: 涨停原因归一化映射表
# ---------------------------------------------------------------------------
REASON_NORMALIZATION_MAP: dict[str, str] = {
    # AI概念
    "AI": "AI概念",
    "人工智能": "AI概念",
    "大模型": "AI概念",
    "ChatGPT": "AI概念",
    "AIGC": "AI概念",
    "算力": "AI概念",
    "算力租赁": "AI概念",
    "AI政务": "AI概念",
    "AI应用": "AI概念",
    "智能体": "AI概念",
    "Sora": "AI概念",
    "CPO": "AI概念",
    "光模块": "AI概念",
    "液冷": "AI概念",
    "服务器": "AI概念",
    "GPU": "AI概念",
    "英伟达概念": "AI概念",
    # 新能源
    "新能源": "新能源",
    "光伏": "新能源",
    "锂电池": "新能源",
    "储能": "新能源",
    "风电": "新能源",
    "钠离子电池": "新能源",
    "固态电池": "新能源",
    "充电桩": "新能源",
    "新能源汽车": "新能源",
    "碳酸锂": "新能源",
    # 军工
    "军工": "军工",
    "国防": "军工",
    "航天": "军工",
    "航空": "军工",
    "导弹": "军工",
    "卫星": "军工",
    "无人机": "军工",
    # 医药
    "医药": "医药",
    "生物": "医药",
    "疫苗": "医药",
    "创新药": "医药",
    "CRO": "医药",
    "中药": "医药",
    "医疗器械": "医药",
    # 华为
    "华为": "华为概念",
    "鸿蒙": "华为概念",
    "HUAWEI": "华为概念",
    "欧拉": "华为概念",
    "盘古大模型": "华为概念",
    # 消费
    "白酒": "消费",
    "食品": "消费",
    "零售": "消费",
    "电商": "消费",
    "消费电子": "消费",
    # 金融
    "券商": "金融",
    "银行": "金融",
    "保险": "金融",
    "金融科技": "金融",
    # 房地产
    "房地产": "房地产",
    "地产": "房地产",
    "物业": "房地产",
    # 芯片/半导体
    "芯片": "芯片",
    "半导体": "芯片",
    "光刻机": "芯片",
    "封装": "芯片",
    "IGBT": "芯片",
    # 机器人
    "机器人": "机器人",
    "人形机器人": "机器人",
    "减速器": "机器人",
    "伺服电机": "机器人",
}


# ---------------------------------------------------------------------------
# P1-10: 涨停原因归一化函数
# ---------------------------------------------------------------------------

def _normalize_theme_name(reason: str) -> str:
    """归一化涨停原因为主题名称。

    将同花顺返回的细分原因（如"AI政务"、"大模型"）归一化为标准主题名（如"AI概念"）。
    如果找不到映射，返回原文。
    """
    if not reason:
        return ""
    # 精确匹配
    if reason in REASON_NORMALIZATION_MAP:
        return REASON_NORMALIZATION_MAP[reason]
    # 子串匹配：遍历映射表的key，看是否包含在reason中
    for key, normalized in REASON_NORMALIZATION_MAP.items():
        if key in reason:
            return normalized
    return reason


# ---------------------------------------------------------------------------
# P1-01: 同花顺涨停获取
# ---------------------------------------------------------------------------

def _get_limitup_stocks_ths(trade_date: str) -> list[dict]:
    """从同花顺 getharden 接口获取涨停股票列表（含涨停原因）。

    返回:
        [{"code": "000001", "name": "平安银行", "reason": "AI概念+大模型"}, ...]

    数据源: 同花顺 zx.10jqka.com.cn getharden
    限流: 无（同花顺风控极弱）
    """
    if not trade_date or trade_date.strip() == "":
        trade_date = datetime.now().strftime("%Y-%m-%d")

    try:
        url = (
            f"http://zx.10jqka.com.cn/event/api/getharden/"
            f"date/{trade_date}/orderby/date/orderway/desc/charset/GBK/"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "Chrome/117.0.0.0 Safari/537.36"
            )
        }
        r = _requests.get(url, headers=headers, timeout=10)
        data = r.json()

        if data.get("errocode", 0) != 0:
            logger.warning("同花顺 getharden API error: %s", data.get("errormsg"))
            return []

        rows = data.get("data") or []
        if not rows:
            return []

        return [
            {"code": str(row.get("code", "")).strip(),
             "name": str(row.get("name", "")).strip(),
             "reason": str(row.get("reason", "")).strip()}
            for row in rows
            if str(row.get("code", "")).strip()
        ]

    except Exception as e:
        logger.warning("_get_limitup_stocks_ths failed for %s: %s", trade_date, e)
        return []


# ---------------------------------------------------------------------------
# P1-02: mootdx涨停判断
# ---------------------------------------------------------------------------

def _detect_limitup_from_kline(code: str, trade_date: str) -> dict:
    """从K线数据判断个股是否涨停。

    逻辑:
    1. 获取当日K线（OHLCV）
    2. 计算涨停价 = 前收盘 * 1.1（四舍五入到分）
    3. 如果收盘价 == 涨停价 → 涨停
    4. 如果开盘价 == 涨停价 且 收盘价 == 涨停价 且 最高价 == 最低价 → 一字板

    返回:
        {"is_limit_up": bool, "is_yizi": bool, "prev_close": float, "limit_price": float}
    """
    try:
        code = _normalize_ticker(code)
        df = _load_ohlcv_astock(code, trade_date)
        if df is None or df.empty or len(df) < 2:
            return {"is_limit_up": False, "is_yizi": False, "prev_close": 0, "limit_price": 0}

        last_row = df.iloc[-1]
        prev_close = float(df.iloc[-2]["Close"])
        curr_close = float(last_row["Close"])
        curr_open = float(last_row["Open"])
        curr_high = float(last_row["High"])
        curr_low = float(last_row["Low"])

        # 涨停价 = 前收盘 * 1.1，四舍五入到分
        limit_price = round(prev_close * 1.1, 2)
        is_limit_up = abs(curr_close - limit_price) < 0.01
        # 一字板：开盘=收盘=涨停价，且最高=最低（无波动）
        is_yizi = (
            is_limit_up
            and abs(curr_open - limit_price) < 0.01
            and abs(curr_high - curr_low) < 0.01
        )

        return {
            "is_limit_up": is_limit_up,
            "is_yizi": is_yizi,
            "prev_close": prev_close,
            "limit_price": limit_price,
        }
    except Exception as e:
        logger.warning("_detect_limitup_from_kline failed for %s: %s", code, e)
        return {"is_limit_up": False, "is_yizi": False, "prev_close": 0, "limit_price": 0}


# ---------------------------------------------------------------------------
# P1-03: 连板天数计算
# ---------------------------------------------------------------------------

def _calculate_consecutive_days(code: str, trade_date: str) -> int:
    """计算个股连板天数（从trade_date往前追溯连续涨停的天数）。

    逻辑:
    1. 从trade_date开始，逐日检查是否涨停
    2. 如果当日收盘价 == 涨停价，连板天数+1
    3. 如果中断，停止计数

    返回: 连板天数（int），0表示当日未涨停
    """
    try:
        code = _normalize_ticker(code)
        df = _load_ohlcv_astock(code, trade_date)
        if df is None or df.empty or len(df) < 2:
            return 0

        consecutive = 0
        # 从最后一天往前追溯
        for i in range(len(df) - 1, 0, -1):
            prev_close = float(df.iloc[i - 1]["Close"])
            curr_close = float(df.iloc[i]["Close"])
            limit_price = round(prev_close * 1.1, 2)
            if abs(curr_close - limit_price) < 0.01:
                consecutive += 1
            else:
                break

        return consecutive

    except Exception as e:
        logger.warning("_calculate_consecutive_days failed for %s: %s", code, e)
        return 0


# ---------------------------------------------------------------------------
# P1-04: 统一涨停获取接口（整合THS+mootdx）
# ---------------------------------------------------------------------------

def _is_bse_code(code: str) -> bool:
    """判断是否为北交所股票代码（8/9 开头的 6 位代码，mootdx 不支持）。"""
    return len(code) == 6 and code[0] in ("8", "9") and not code.startswith("900")


def _enrich_limitup_stock(stock: dict, trade_date: str, em_quotes: dict) -> dict:
    """为单个涨停股补充连板天数、涨停类型和东财行情数据。"""
    code = stock["code"]
    # 北交所股票（8/9开头）mootdx 不支持，跳过 K 线查询
    if _is_bse_code(code):
        consecutive_days = 0
        limit_type = "换手"
    else:
        consecutive_days = _calculate_consecutive_days(code, trade_date)
        kline_info = _detect_limitup_from_kline(code, trade_date)
        limit_type = "一字" if kline_info.get("is_yizi") else "换手"
    em_data = em_quotes.get(code, {})
    return {
        "code": code,
        "name": stock["name"],
        "reason": stock["reason"],
        "consecutive_days": consecutive_days,
        "limit_type": limit_type,
        "circulation_mv": em_data.get("circulation_mv", 0),
        "turnover_rate": em_data.get("turnover_rate", 0),
        "amount": em_data.get("amount", 0),
    }


def _get_limitup_stocks(trade_date: str) -> list[dict]:
    """获取当日涨停股票列表（含连板天数、涨停类型等）。

    整合数据源:
    - 同花顺 getharden: 涨停股列表 + 涨停原因
    - mootdx K线: 连板天数 + 涨停类型（一字/换手）
    - 东财选股接口: 补充流通市值、换手率、成交额等

    返回:
        [{"code": "000001", "name": "平安银行", "reason": "AI概念",
          "consecutive_days": 3, "limit_type": "换手",
          "circulation_mv": 5000000000, "turnover_rate": 0.08,
          "amount": 200000000}, ...]

    数据源: 同花顺 getharden + mootdx K线 + 东财选股接口
    限流: _em_get()（仅东财部分）
    """
    cache_key = ("limitup", trade_date)
    if cache_key in _session_cache:
        return _session_cache[cache_key]
    try:
        ths_stocks = _get_limitup_stocks_ths(trade_date)
        if not ths_stocks:
            return []

        codes = [s["code"] for s in ths_stocks]
        em_quotes = _get_em_xuangu_quotes(codes)

        result = [
            _enrich_limitup_stock(stock, trade_date, em_quotes)
            for stock in ths_stocks
        ]
        _session_cache[cache_key] = result
        return result

    except Exception as e:
        logger.warning("_get_limitup_stocks failed for %s: %s", trade_date, e)
        _session_cache[cache_key] = []
        return []


def _get_em_xuangu_quotes(codes: list[str]) -> dict[str, dict]:
    """从东财选股接口批量获取个股行情（流通市值、换手率、成交额）。

    返回: {code: {"circulation_mv": float, "turnover_rate": float, "amount": float}}
    """
    if not codes:
        return {}

    try:
        # 构建股票代码过滤条件
        code_filter = " OR ".join([f'(SECURITY_CODE="{c}")' for c in codes[:50]])
        url = "https://data.eastmoney.com/dataapi/xuangu/list"
        params = {
            "st": "CHANGE_RATE",
            "sr": "-1",
            "ps": str(min(len(codes), 50)),
            "p": "1",
            "sty": "SECURITY_CODE,FREE_CAP,TURNOVERRATE,DEAL_AMOUNT",
            "filter": f'({code_filter})',
        }
        r = _em_get(url, params=params, timeout=15)
        if r is None:
            logger.warning("_get_em_xuangu_quotes: _em_get returned None")
            return {}
        try:
            d = r.json()
        except Exception:
            logger.warning("_get_em_xuangu_quotes: invalid JSON response (status=%s)", r.status_code)
            return {}
        if not isinstance(d, dict):
            logger.warning("_get_em_xuangu_quotes: unexpected response type %s", type(d))
            return {}

        result = {}
        for item in (d.get("result") or {}).get("data") or []:
            code = item.get("SECURITY_CODE", "")
            if code:
                result[code] = {
                    "circulation_mv": float(item.get("FREE_CAP") or 0),
                    "turnover_rate": float(item.get("TURNOVERRATE") or 0) / 100,
                    "amount": float(item.get("DEAL_AMOUNT") or 0),
                }
        return result

    except Exception as e:
        logger.warning("_get_em_xuangu_quotes failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# P1-05: 跌停获取
# ---------------------------------------------------------------------------

def _get_limitdown_stocks(trade_date: str) -> list[dict]:
    """获取当日跌停股票列表。

    使用东财选股接口筛选跌幅>=-9.9%的股票作为跌停近似。

    返回:
        [{"code": "000001", "name": "平安银行", "change_rate": -10.0}, ...]

    数据源: 东财选股接口
    限流: _em_get()
    """
    if not trade_date or trade_date.strip() == "":
        trade_date = datetime.now().strftime("%Y-%m-%d")

    cache_key = ("limitdown", trade_date)
    if cache_key in _session_cache:
        return _session_cache[cache_key]

    try:
        url = "https://data.eastmoney.com/dataapi/xuangu/list"
        params = {
            "st": "CHANGE_RATE",
            "sr": "1",
            "ps": "100",
            "p": "1",
            "sty": "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,CHANGE_RATE,NEW_PRICE",
            "filter": "(CHANGE_RATE<=-9.9)",
        }
        r = _em_get(url, params=params, timeout=15)
        if r is None:
            logger.warning("_get_limitdown_stocks: _em_get returned None for %s", trade_date)
            return []
        try:
            d = r.json()
        except Exception:
            logger.warning("_get_limitdown_stocks: invalid JSON (status=%s)", r.status_code)
            return []
        if not isinstance(d, dict):
            logger.warning("_get_limitdown_stocks: unexpected type %s", type(d))
            return []

        data = (d.get("result") or {}).get("data") or []
        if not data:
            return []

        result = [
            {"code": item["SECURITY_CODE"],
             "name": item.get("SECURITY_NAME_ABBR", ""),
             "change_rate": float(item.get("CHANGE_RATE") or 0)}
            for item in data
            if item.get("SECURITY_CODE")
        ]
        _session_cache[cache_key] = result
        return result

    except Exception as e:
        logger.warning("_get_limitdown_stocks failed for %s: %s", trade_date, e)
        _session_cache[cache_key] = []
        return []


# ---------------------------------------------------------------------------
# P4-01: 首板股票获取
# ---------------------------------------------------------------------------

def _get_first_board_stocks(trade_date: str) -> list[dict]:
    """获取今日首板股票（连板天数=1）。

    从 _get_limitup_stocks 中筛选 consecutive_days==1 的股票，
    并补充首板涨停时间。

    返回:
        [{"code": "000001", "name": "股票A", "reason": "AI概念",
          "consecutive_days": 1, "limit_type": "换手",
          "circulation_mv": 5e9, "turnover_rate": 0.08,
          "amount": 2e8, "first_limit_time": "09:35"}, ...]

    数据源: _get_limitup_stocks (同花顺 + mootdx + 东财)
    """
    limitup_stocks = _get_limitup_stocks(trade_date)
    if not limitup_stocks:
        return []

    first_boards = []
    for stock in limitup_stocks:
        if stock.get("consecutive_days", 0) != 1:
            continue

        # 获取首板涨停时间（从K线判断开盘即涨停还是盘中封板）
        code = stock["code"]
        first_limit_time = _estimate_first_limit_time(code, trade_date, stock.get("limit_type", ""))

        first_boards.append({
            **stock,
            "first_limit_time": first_limit_time,
        })

    return first_boards


def _estimate_first_limit_time(code: str, trade_date: str, limit_type: str) -> str:
    """估算首板涨停时间。

    逻辑:
    - 一字板（开盘即封死）→ 返回 "09:30"
    - 换手板 → 尝试从K线推断，失败则返回默认 "10:00"

    数据源: mootdx K线
    """
    if limit_type == "一字":
        return "09:30"

    try:
        code = _normalize_ticker(code)
        df = _load_ohlcv_astock(code, trade_date)
        if df is None or df.empty or len(df) < 1:
            return "10:00"

        # 如果开盘价接近涨停价，说明开盘即封板（一字板但K线形态不完全匹配）
        row = df.iloc[-1]
        curr_open = float(row["Open"])
        curr_close = float(row["Close"])
        curr_high = float(row["High"])

        # 涨停价估算（前收盘 * 1.1）
        if len(df) >= 2:
            prev_close = float(df.iloc[-2]["Close"])
            limit_price = round(prev_close * 1.1, 2)
            if abs(curr_open - limit_price) < 0.01:
                return "09:30"

        return "10:00"  # 默认盘中涨停

    except Exception:
        return "10:00"


# ---------------------------------------------------------------------------
# P4-02: 封单信息获取
# ---------------------------------------------------------------------------

def _get_stock_seal_info(stock: dict) -> dict:
    """获取个股封单信息（简化版，基于可用数据估算）。

    数据限制说明:
    - 封单金额（seal_amount）不可直接获取，改用换手率/封板类型估算
    - 封单稳定性（seal_stability）需要分时K线，此处返回 None

    返回:
        {"seal_strength_score": float (0-100),
         "seal_ratio": float (估算值),
         "board_type": str}

    数据源: 复用已有涨停数据
    """
    turnover_rate = stock.get("turnover_rate", 0)
    limit_type = stock.get("limit_type", "换手")
    amount = stock.get("amount", 0)
    circulation_mv = stock.get("circulation_mv", 0)

    # 封单强度评分（0-100）
    # 核心逻辑: 低换手 + 涨停 = 强封板
    score = 50  # 基准分

    # 换手率调整（换手率越低，封单越强）
    if turnover_rate <= 0.01:
        score += 30  # 极低换手（一字板级别）
    elif turnover_rate <= 0.03:
        score += 20  # 低换手
    elif turnover_rate <= 0.05:
        score += 10  # 适度换手
    elif turnover_rate <= 0.10:
        score += 0   # 正常换手
    elif turnover_rate <= 0.15:
        score -= 10  # 偏高换手
    else:
        score -= 20  # 高换手（封单弱）

    # 板型调整
    if limit_type == "一字":
        score += 15  # 一字板封单最强
    elif limit_type == "T字":
        score += 5   # T字板次之

    # 封单/流通盘比估算（用成交额/流通市值近似）
    seal_ratio = 0.0
    if circulation_mv > 0:
        seal_ratio = round(amount / circulation_mv * 100, 2)

    return {
        "seal_strength_score": max(0, min(100, score)),
        "seal_ratio": seal_ratio,
        "board_type": limit_type,
        "seal_stability": None,  # 需要分时K线，暂不可获取
    }


# ---------------------------------------------------------------------------
# P4-03: 历史股性评分
# ---------------------------------------------------------------------------

def _get_historical_activity(code: str, lookback_days: int = 240) -> float:
    """获取历史股性评分（近1年涨停次数）。

    逻辑:
    - 近1年涨停次数 >=5 → 活跃（80-100分）
    - 近1年涨停次数 2-4 → 一般（40-70分）
    - 近1年涨停次数 0-1 → 僵尸股（0-30分）

    返回: 0-100 评分

    数据源: mootdx K线
    """
    try:
        code = _normalize_ticker(code)
        df = _load_ohlcv_astock(code, datetime.now().strftime("%Y-%m-%d"))
        if df is None or df.empty or len(df) < 2:
            return 30.0  # 默认一般股性

        # 统计近 lookback_days 内的涨停次数
        limitup_count = 0
        start_idx = max(0, len(df) - lookback_days)
        for i in range(start_idx + 1, len(df)):
            prev_close = float(df.iloc[i - 1]["Close"])
            curr_close = float(df.iloc[i]["Close"])
            limit_price = round(prev_close * 1.1, 2)
            if abs(curr_close - limit_price) < 0.01:
                limitup_count += 1

        # 评分映射
        if limitup_count >= 5:
            return float(min(100, 80 + (limitup_count - 5) * 4))
        elif limitup_count >= 2:
            return float(40 + (limitup_count - 2) * 10)
        else:
            return float(limitup_count * 15)

    except Exception as e:
        logger.warning("_get_historical_activity failed for %s: %s", code, e)
        return 30.0


# ---------------------------------------------------------------------------
# P4-04: 题材纯正度评分
# ---------------------------------------------------------------------------

def _calculate_theme_purity(
    code: str,
    theme_name: str,
    theme_stocks: list[dict],
    theme_map: dict[str, list[dict]],
) -> float:
    """计算题材纯正度（0-100分）。

    评分维度:
    1. 是否为题材内连板最高的票 → +30分
    2. 涨停原因是否直接匹配题材名 → +30分
    3. 题材涨停家数>=10 → +20分（5-9只 → +10分）
    4. 有梯队支撑（同题材有2板以上）→ +20分

    返回: 0-100 评分

    数据源: 复用已有涨停数据
    """
    score = 0

    # 1. 是否为题材内连板最高
    my_board_num = next(
        (s.get("board_num", 0) for s in theme_stocks if s["code"] == code), 0
    )
    max_board = max((s.get("board_num", 0) for s in theme_stocks), default=0)
    if my_board_num == max_board and my_board_num > 0:
        score += 30

    # 2. 涨停原因匹配题材名（简化: 检查原始原因是否包含题材关键词）
    raw_reason = next(
        (s.get("raw_reason", "") for s in theme_stocks if s["code"] == code), ""
    )
    if theme_name and theme_name in raw_reason:
        score += 30
    elif raw_reason and any(
        kw in raw_reason for kw in theme_name.replace("概念", "").split()
    ):
        score += 15  # 部分匹配

    # 3. 题材涨停家数
    stock_count = len(theme_stocks)
    if stock_count >= 10:
        score += 20
    elif stock_count >= 5:
        score += 10

    # 4. 梯队支撑（同题材有2板以上）
    has_ladder = any(s.get("board_num", 0) >= 2 for s in theme_stocks)
    if has_ladder:
        score += 20

    return min(100, score)


# ---------------------------------------------------------------------------
# P4-05: 量价配合评分
# ---------------------------------------------------------------------------

def _calculate_volume_match_score(
    turnover_rate: float,
    amount: float,
    volume_ratio: float = 1.0,
) -> float:
    """量价配合评分（0-100分）。

    评分逻辑:
    - 换手率 5-15%: 最佳区间 → 高分
    - 换手率 <5%: 缩量板，流动性差 → 中分
    - 换手率 >15%: 放量板，抛压大 → 中低分
    - 成交额: 越大流动性越好（但需要适度）
    - 量比: 相对前日，>1.5 放量，<0.5 缩量

    返回: 0-100 评分

    数据源: 复用已有行情数据
    """
    score = 50  # 基准分

    # 换手率评分
    turnover_pct = turnover_rate * 100  # 转为百分比
    if 5 <= turnover_pct <= 15:
        score += 20  # 最佳区间
    elif 3 <= turnover_pct < 5:
        score += 10  # 偏低但可接受
    elif 15 < turnover_pct <= 20:
        score += 5   # 偏高
    elif turnover_pct < 3:
        score -= 5   # 过低（流动性差）
    else:
        score -= 15  # 过高（抛压大）

    # 量比评分
    if 1.0 <= volume_ratio <= 2.0:
        score += 15  # 温和放量
    elif 0.8 <= volume_ratio < 1.0:
        score += 10  # 略缩量
    elif volume_ratio > 2.0:
        score += 0   # 放量过大
    else:
        score -= 10  # 严重缩量

    # 成交额评分（绝对值，亿元）
    amount_yi = amount / 1e8
    if 1 <= amount_yi <= 10:
        score += 15  # 适中成交额
    elif amount_yi > 10:
        score += 10  # 大成交额
    elif amount_yi >= 0.5:
        score += 5   # 偏小
    else:
        score -= 5   # 过小（流动性不足）

    return max(0, min(100, score))


# ---------------------------------------------------------------------------
# P4-06: 二板预期评分
# ---------------------------------------------------------------------------

def _market_emotion_score(emotion: str) -> float:
    """将情绪周期转换为评分（0-100）。"""
    mapping = {
        "高潮": 90, "升温": 75, "修复": 55,
        "分歧": 45, "退潮": 30, "低迷": 20, "冰点": 10,
        "冰点（已确认）": 5,
    }
    return mapping.get(emotion, 50)


def _first_limit_time_score(time_str: str) -> float:
    """将首板时间转换为评分（0-100）。"""
    if not time_str:
        return 50
    if time_str < "09:45":
        return 90  # 极早盘
    elif time_str < "10:00":
        return 80  # 早盘
    elif time_str < "10:30":
        return 65  # 上午中段
    elif time_str < "13:00":
        return 50  # 午盘
    elif time_str < "14:00":
        return 35  # 下午
    else:
        return 20  # 尾盘偷袭


def calculate_second_board_score(
    seal_strength: float,
    volume_match: float,
    theme_heat: float,
    board_type: str,
    market_emotion: str = "",
    circulation_mv: float = 0,
    first_limit_time: str = "",
    theme_purity: float = 0,
    historical_activity: float = 0,
) -> float:
    """二板预期评分（七因子模型）。

    核心因子及权重:
    1. 封单强度: 25%
    2. 量价配合: 15%
    3. 题材热度: 20%
    4. 市场情绪: 20%
    5. 首板时间: 10%
    6. 题材纯正度: 5%
    7. 历史股性: 5%

    特殊调整:
    - 一字板: -10分（开板风险高）
    - T字板: +0分
    - 换手板: +5分（换手充分）

    市场情绪调整:
    - 情绪好（高潮/升温）: +10分
    - 情绪一般（修复/分歧）: +0分
    - 情绪差（冰点/低迷）: -10分

    流通市值调整:
    - <50亿: +5分（小盘股弹性大）
    - 50-200亿: +0分（最佳区间）
    - >200亿: -5分（大盘股难封）

    首板时间调整:
    - 9:30-10:00: +5分（早盘优势）
    - 10:00-13:00: +0分
    - 13:00-15:00: -5分（尾盘偷袭）

    返回: 0-100 评分

    数据源: 纯计算函数
    """
    score = (
        seal_strength * 0.25 +
        volume_match * 0.15 +
        theme_heat * 0.20 +
        _market_emotion_score(market_emotion) * 0.20 +
        _first_limit_time_score(first_limit_time) * 0.10 +
        theme_purity * 0.05 +
        historical_activity * 0.05
    )

    # 板型调整
    if board_type == "一字":
        score -= 10
    elif board_type == "换手":
        score += 5

    # 市场情绪调整
    if market_emotion in ("高潮", "升温"):
        score += 10
    elif market_emotion in ("冰点", "低迷", "冰点（已确认）"):
        score -= 10

    # 流通市值调整（阈值: 50亿/200亿）
    if 0 < circulation_mv < 5e9:
        score += 5
    elif circulation_mv > 2e10:
        score -= 5

    # 首板时间调整
    if first_limit_time and first_limit_time < "10:00":
        score += 5
    elif first_limit_time and first_limit_time > "13:00":
        score -= 5

    return round(max(0, min(100, score)), 1)


# ---------------------------------------------------------------------------
# P4-07: 主接口 - 首板筛选 + 二板预期
# ---------------------------------------------------------------------------

def get_first_board_screen(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
    min_score: Annotated[int, "最低二板预期评分, 默认60"] = 60,
) -> str:
    """首板筛选 + 二板预期评估。

    返回内容:
    1. 今日首板票列表（按二板预期评分排序）
    2. 每只票的封单强度、量价配合、题材热度
    3. 二板预期评分（0-100）
    4. 标注高评分标的

    数据源: 同花顺 + mootdx + 东财 + 腾讯财经
    限流: _em_get()（仅东财部分）

    数据限制说明:
    - 封单峰值不可获取，改用换手率/封板类型估算封单强度
    - 封单稳定性不可获取，返回 None
    """
    if not trade_date or trade_date.strip() == "":
        trade_date = datetime.now().strftime("%Y-%m-%d")

    try:
        # 1. 获取首板股票
        first_boards = _get_first_board_stocks(trade_date)
        if not first_boards:
            return f"无首板数据（非交易日或盘后未更新）| {trade_date}"

        # 2. 获取市场情绪（复用情绪量化）
        emotion_metrics = _calculate_emotion_metrics(
            _get_limitup_stocks(trade_date),
            _get_limitdown_stocks(trade_date),
            _get_yesterday_limitup_performance(trade_date),
            _get_market_breadth(trade_date),
            _get_northbound_flow_signal(trade_date),
        )
        market_emotion = emotion_metrics.get("emotion_phase", "修复")

        # 3. 获取题材数据（用于热度和纯正度）
        theme_map = _get_limitup_by_theme(trade_date)

        # 4. 构建题材热度查找表
        theme_heat_map: dict[str, float] = {}
        for theme_name, theme_stocks in theme_map.items():
            stock_count = len(theme_stocks)
            highest_board = max((s.get("board_num", 0) for s in theme_stocks), default=0)
            heat = min(100, stock_count * 8 + highest_board * 15)
            theme_heat_map[theme_name] = heat

        # 5. 逐票计算二板预期评分
        scored_stocks: list[dict] = []
        for stock in first_boards:
            code = stock["code"]

            # 封单信息
            seal_info = _get_stock_seal_info(stock)

            # 量价配合
            volume_score = _calculate_volume_match_score(
                turnover_rate=stock.get("turnover_rate", 0),
                amount=stock.get("amount", 0),
            )

            # 题材热度（取最高热度）
            raw_reason = stock.get("reason", "")
            reasons = [r.strip() for r in raw_reason.replace("，", "+").split("+") if r.strip()]
            max_theme_heat = 0
            best_theme = ""
            for reason in reasons:
                normalized = _normalize_theme_name(reason)
                heat = theme_heat_map.get(normalized, 0)
                if heat > max_theme_heat:
                    max_theme_heat = heat
                    best_theme = normalized

            # 题材纯正度
            theme_stocks = theme_map.get(best_theme, [])
            purity = _calculate_theme_purity(code, best_theme, theme_stocks, theme_map)

            # 历史股性
            activity = _get_historical_activity(code)

            # 二板预期评分
            second_board_score = calculate_second_board_score(
                seal_strength=seal_info["seal_strength_score"],
                volume_match=volume_score,
                theme_heat=max_theme_heat,
                board_type=seal_info["board_type"],
                market_emotion=market_emotion,
                circulation_mv=stock.get("circulation_mv", 0),
                first_limit_time=stock.get("first_limit_time", ""),
                theme_purity=purity,
                historical_activity=activity,
            )

            scored_stocks.append({
                **stock,
                "seal_info": seal_info,
                "volume_score": volume_score,
                "theme_heat": max_theme_heat,
                "best_theme": best_theme,
                "theme_purity": purity,
                "historical_activity": activity,
                "second_board_score": second_board_score,
            })

        # 6. 按二板预期评分排序
        scored_stocks.sort(key=lambda x: x["second_board_score"], reverse=True)

        # 7. 格式化输出
        return _format_first_board_screen(
            scored_stocks, trade_date, min_score, market_emotion, emotion_metrics
        )

    except Exception as e:
        return f"首板筛选失败 ({trade_date}): {str(e)}"


def _format_first_board_screen(
    scored_stocks: list[dict],
    trade_date: str,
    min_score: int,
    market_emotion: str,
    emotion_metrics: dict,
) -> str:
    """格式化首板筛选输出。"""
    lines = [
        f"# 首板筛选 + 二板预期 | {trade_date}",
        f"# Source: 同花顺 + mootdx + 东财 + 腾讯财经",
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # 总览
    total = len(scored_stocks)
    high_score = sum(1 for s in scored_stocks if s["second_board_score"] >= min_score)
    lines.append("## 总览")
    lines.append(f"  首板总数: {total}只")
    lines.append(f"  二板预期>={min_score}分: {high_score}只")
    lines.append(f"  市场情绪: {market_emotion}")
    lines.append(f"  情绪评分: {emotion_metrics.get('emotion_score', 0)}")
    lines.append("")

    # 高评分标的
    if high_score > 0:
        lines.append(f"## 高评分标的 (>= {min_score}分)")
        lines.append("  排名 | 代码 | 名称 | 题材 | 封单 | 量价 | 题材热 | 纯正度 | 股性 | 评分")
        lines.append("  --- | --- | --- | --- | --- | --- | --- | --- | --- | ---")

        for i, s in enumerate(scored_stocks):
            if s["second_board_score"] < min_score:
                break
            lines.append(
                f"  {i+1}. {s['code']} {s.get('name', '')} "
                f"| {s.get('best_theme', '')} "
                f"| {s['seal_info']['seal_strength_score']:.0f} "
                f"| {s['volume_score']:.0f} "
                f"| {s['theme_heat']:.0f} "
                f"| {s['theme_purity']:.0f} "
                f"| {s['historical_activity']:.0f} "
                f"| **{s['second_board_score']}**"
            )
        lines.append("")

    # 评分分布
    lines.append("## 评分分布")
    ranges = [(80, 100), (60, 80), (40, 60), (0, 40)]
    for low, high in ranges:
        count = sum(1 for s in scored_stocks if low <= s["second_board_score"] < high)
        if count > 0:
            lines.append(f"  {low}-{high}分: {count}只")
    lines.append("")

    # 全部首板概览
    lines.append("## 全部首板")
    for i, s in enumerate(scored_stocks[:20]):  # 最多显示20只
        seal = s["seal_info"]
        lines.append(
            f"  {i+1}. {s['code']} {s.get('name', '')} "
            f"{s.get('limit_type', '')} "
            f"题材:{s.get('best_theme', '无')} "
            f"封单:{seal['seal_strength_score']:.0f} "
            f"量价:{s['volume_score']:.0f} "
            f"评分:{s['second_board_score']}"
        )

    if total > 20:
        lines.append(f"  ... 共{total}只，仅显示前20只")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# P1-06: 个股行情获取
# ---------------------------------------------------------------------------

def _get_stock_realtime_quote(code: str) -> dict:
    """获取个股实时行情（复用腾讯财经接口）。

    返回:
        {"code": "000001", "name": "平安银行", "price": 15.2,
         "change_pct": 2.5, "volume": ..., "limit_up": ..., "limit_down": ...}

    数据源: 腾讯财经 qt.gtimg.cn
    """
    try:
        code = _normalize_ticker(code)
        quotes = _tencent_quote([code])
        data = quotes.get(code, {})
        if not data:
            return {}
        return {
            "code": code,
            "name": data.get("name", ""),
            "price": data.get("price", 0),
            "last_close": data.get("last_close", 0),
            "open": data.get("open", 0),
            "change_pct": data.get("change_pct", 0),
            "high": data.get("high", 0),
            "low": data.get("low", 0),
            "turnover_pct": data.get("turnover_pct", 0),
            "limit_up": data.get("limit_up", 0),
            "limit_down": data.get("limit_down", 0),
            "mcap_yi": data.get("mcap_yi", 0),
            "float_mcap_yi": data.get("float_mcap_yi", 0),
        }
    except Exception as e:
        logger.warning("_get_stock_realtime_quote failed for %s: %s", code, e)
        return {}


# ---------------------------------------------------------------------------
# P1-07: 市场涨跌家数
# ---------------------------------------------------------------------------

_BREADTH_EMPTY = {"up_count": 0, "down_count": 0, "flat_count": 0, "ad_ratio": 0, "breadth_signal": "无数据"}


def _classify_breadth_signal(ad_ratio: float) -> str:
    """根据涨跌家数比判断市场强度。"""
    if ad_ratio >= 3:
        return "强势"
    if ad_ratio >= 1:
        return "正常"
    return "弱势"


def _get_market_breadth(trade_date: str) -> dict:
    """获取市场涨跌家数比。

    通过东财push2全市场行情统计涨跌家数。

    返回:
        {"up_count": int, "down_count": int, "flat_count": int,
         "ad_ratio": float, "breadth_signal": "强势"|"正常"|"弱势"}

    数据源: 东财 push2 全市场行情统计
    限流: _em_get()
    """
    cache_key = ("market_breadth", trade_date)
    if cache_key in _session_cache:
        return _session_cache[cache_key]

    empty = dict(_BREADTH_EMPTY)
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "1", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": "f3",
        }
        r = _em_get(url, params=params, timeout=15)
        if r is None:
            _session_cache[cache_key] = empty
            return empty
        try:
            d = r.json()
        except Exception:
            _session_cache[cache_key] = empty
            return empty
        if not isinstance(d, dict):
            _session_cache[cache_key] = empty
            return empty

        total = (d.get("data") or {}).get("total", 0)
        if total == 0:
            _session_cache[cache_key] = empty
            return empty

        up_count = _count_by_change_range("f3>0")
        down_count = _count_by_change_range("f3<0")
        flat_count = max(total - up_count - down_count, 0)
        ad_ratio = round(up_count / max(down_count, 1), 2)

        result = {
            "up_count": up_count,
            "down_count": down_count,
            "flat_count": flat_count,
            "ad_ratio": ad_ratio,
            "breadth_signal": _classify_breadth_signal(ad_ratio),
        }
        _session_cache[cache_key] = result
        return result

    except Exception as e:
        logger.warning("_get_market_breadth failed for %s: %s", trade_date, e)
        _session_cache[cache_key] = empty
        return dict(_BREADTH_EMPTY)


def _count_by_change_range(filter_expr: str) -> int:
    """东财push2按涨跌幅区间统计家数。"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "1",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f3",
        "filter": filter_expr,
    }
    r = _em_get(url, params=params, timeout=15)
    if r is None:
        return 0
    try:
        d = r.json()
    except Exception:
        return 0
    if not isinstance(d, dict):
        return 0
    return (d.get("data") or {}).get("total", 0)


# ---------------------------------------------------------------------------
# P1-08: 北向资金信号
# ---------------------------------------------------------------------------
_NORTHBOUND_LARGE_FLOW_YI = 30  # 亿元，大幅流入/流出阈值

_NORTHBOUND_EMPTY = {
    "net_inflow": 0, "direction": "无数据",
    "is_confirming_strength": False, "is_confirming_weakness": False,
}


def _classify_northbound_direction(total_yi: float) -> str:
    """根据北向资金净流入（亿元）判断方向。"""
    if total_yi > _NORTHBOUND_LARGE_FLOW_YI:
        return "大幅流入"
    if total_yi > 0:
        return "小幅流入"
    if total_yi > -_NORTHBOUND_LARGE_FLOW_YI:
        return "小幅流出"
    return "大幅流出"


def _get_northbound_flow_signal(trade_date: str) -> dict:
    """获取北向资金情绪信号。

    复用现有 get_northbound_flow 的底层逻辑，提取关键信号。

    返回:
        {"net_inflow": float (亿元), "direction": str,
         "is_confirming_strength": bool, "is_confirming_weakness": bool}

    数据源: 同花顺 hsgtApi（已有 get_northbound_flow）
    """
    cache_key = ("northbound_signal", trade_date)
    if cache_key in _session_cache:
        return _session_cache[cache_key]

    try:
        url = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "Chrome/117.0.0.0 Safari/537.36"
            ),
            "Host": "data.hexin.cn",
            "Referer": "https://data.hexin.cn/",
        }
        r = _requests.get(url, headers=headers, timeout=10)
        d = r.json()

        times = d.get("time", [])
        hgt = d.get("hgt", [])
        sgt = d.get("sgt", [])

        if not times:
            return dict(_NORTHBOUND_EMPTY)

        hgt_close = float(hgt[-1]) if hgt else 0
        sgt_close = float(sgt[-1]) if sgt else 0
        total = hgt_close + sgt_close
        direction = _classify_northbound_direction(total)

        result = {
            "net_inflow": round(total, 2),
            "direction": direction,
            "is_confirming_strength": direction in ("大幅流入", "小幅流入"),
            "is_confirming_weakness": direction in ("大幅流出", "小幅流出"),
        }
        _session_cache[cache_key] = result
        return result

    except Exception as e:
        logger.warning("_get_northbound_flow_signal failed: %s", e)
        empty = dict(_NORTHBOUND_EMPTY)
        _session_cache[cache_key] = empty
        return empty


# ===========================================================================
# Phase 2: 连板梯队统计 + 情绪量化 (P2-01 ~ P2-08)
# ===========================================================================

def _get_previous_trading_date(trade_date: str) -> str:
    """获取上一个交易日日期（简单回退，跳过周末）。

    注意: 不处理节假日，仅跳过周末。非精确交易日历。
    """
    from datetime import timedelta

    try:
        dt = datetime.strptime(trade_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        dt = datetime.now()

    dt = dt - timedelta(days=1)
    # 跳过周末
    while dt.weekday() >= 5:  # 5=Saturday, 6=Sunday
        dt = dt - timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# P2-01: 昨日涨停今日表现
# ---------------------------------------------------------------------------

def _get_yesterday_limitup_performance(trade_date: str) -> dict:
    """获取昨日涨停股票今日表现。

    逻辑:
    1. 获取昨日涨停列表
    2. 批量获取今日行情（通过 _tencent_quote）
    3. 返回每只股票的今日涨幅、是否晋级等

    返回:
        {"stocks": [...], "total": int}

    数据源: 同花顺 getharden（昨日）+ 腾讯财经（今日行情）
    """
    if not trade_date or trade_date.strip() == "":
        trade_date = datetime.now().strftime("%Y-%m-%d")

    cache_key = ("yesterday_limitup_perf", trade_date)
    if cache_key in _session_cache:
        return _session_cache[cache_key]

    yesterday = _get_previous_trading_date(trade_date)

    try:
        # 获取昨日涨停列表
        yesterday_limitup = _get_limitup_stocks(yesterday)
        if not yesterday_limitup:
            return {"stocks": [], "total": 0}

        # 批量获取今日行情
        codes = [s["code"] for s in yesterday_limitup]
        today_quotes = _tencent_quote(codes)

        # 获取今日涨停列表（判断是否晋级）
        today_limitup = _get_limitup_stocks(trade_date)
        today_board_map = {
            s["code"]: s["consecutive_days"]
            for s in today_limitup
        }

        stocks = []
        for stock in yesterday_limitup:
            code = stock["code"]
            quote = today_quotes.get(code, {})
            today_change = quote.get("change_pct", 0)
            today_board = today_board_map.get(code, 0)
            yesterday_board = stock.get("consecutive_days", 1)

            stocks.append({
                "code": code,
                "name": stock.get("name", ""),
                "yesterday_board_num": yesterday_board,
                "today_return": today_change,
                "today_board_num": today_board,
                "is_promoted": today_board > yesterday_board,
                "is_muffled": today_change < -5,
                "is_light_muffled": today_change < -3,
                "is_heavy_muffled": today_change < -7,
                "high_open": quote.get("open", 0) > quote.get("last_close", 0) if quote.get("last_close") else False,
            })

        result = {"stocks": stocks, "total": len(stocks)}
        _session_cache[cache_key] = result
        return result

    except Exception as e:
        logger.warning("_get_yesterday_limitup_performance failed for %s: %s", trade_date, e)
        empty = {"stocks": [], "total": 0}
        _session_cache[cache_key] = empty
        return empty


# ---------------------------------------------------------------------------
# P2-02: 连板梯队分布统计
# ---------------------------------------------------------------------------

def _get_board_distribution(limitup_stocks: list[dict]) -> dict:
    """从涨停股票列表计算连板梯队分布。

    返回:
        {"highest_board": int, "distribution": {板数: 股票数量}, "total": int}

    示例:
        {"highest_board": 5, "distribution": {5: 1, 4: 2, 3: 5, 2: 10, 1: 30}, "total": 48}
    """
    if not limitup_stocks:
        return {"highest_board": 0, "distribution": {}, "total": 0}

    dist: dict[int, int] = {}
    for stock in limitup_stocks:
        board = stock.get("consecutive_days", 1)
        dist[board] = dist.get(board, 0) + 1

    highest = max(dist.keys()) if dist else 0
    return {"highest_board": highest, "distribution": dist, "total": len(limitup_stocks)}


# ---------------------------------------------------------------------------
# P2-03: 封板质量评估
# ---------------------------------------------------------------------------

def _calculate_seal_quality(limitup_stocks: list[dict]) -> dict:
    """封板质量综合评估（拆分一字板/换手板）。

    返回:
        {
            "yizi_count": int,            # 一字板数量
            "huan_shou_count": int,       # 换手板数量
            "total_limitup": int,         # 涨停总数
            "effective_seal_rate": float, # 有效封板率（换手板中早盘封板占比）
            "seal_success_rate": float,   # 封板成功率
            "seal_strength_median": float,# 封单强度中位数
        }

    数据限制:
    - 缺少封单金额/峰值数据，封板成功率简化为 换手板数/总数
    - 缺少分时数据，无法精确计算早盘封板时间
    """
    if not limitup_stocks:
        return {
            "yizi_count": 0, "huan_shou_count": 0, "total_limitup": 0,
            "effective_seal_rate": 0, "seal_success_rate": 0,
            "seal_strength_median": 0,
        }

    yizi = sum(1 for s in limitup_stocks if s.get("limit_type") == "一字")
    huanshou = sum(1 for s in limitup_stocks if s.get("limit_type") == "换手")
    total = len(limitup_stocks)

    # 有效封板率: 换手板占比（简化版，缺少分时数据无法精确计算早盘封板）
    effective_seal_rate = round(huanshou / max(total, 1) * 100, 1)

    # 封板成功率: 换手板数/总数（简化版，缺少炸板数据）
    seal_success_rate = round(huanshou / max(total, 1) * 100, 1)

    # 封单强度中位数: 使用换手率作为代理指标（缺少封单金额数据）
    turnover_rates = [
        s.get("turnover_rate", 0) * 100
        for s in limitup_stocks
        if s.get("limit_type") == "换手" and s.get("turnover_rate")
    ]
    seal_strength_median = (
        sorted(turnover_rates)[len(turnover_rates) // 2]
        if turnover_rates else 0
    )

    return {
        "yizi_count": yizi,
        "huan_shou_count": huanshou,
        "total_limitup": total,
        "effective_seal_rate": effective_seal_rate,
        "seal_success_rate": seal_success_rate,
        "seal_strength_median": round(seal_strength_median, 2),
    }


# ---------------------------------------------------------------------------
# P2-04: 昨日涨停表现计算
# ---------------------------------------------------------------------------

def _calculate_yesterday_performance(today_data: dict) -> dict:
    """昨日涨停今日表现计算（精细化，含闷杀率分级）。

    参数:
        today_data: _get_yesterday_limitup_performance() 的返回值

    返回:
        {
            "avg_return": float,          # 整体平均涨幅
            "continuous_premium": float,  # 连板股溢价率
            "first_board_premium": float, # 首板股溢价率
            "high_open_rate": float,      # 高开率
            "median_return": float,       # 收盘涨幅中位数
            "muffled_rate": float,        # 闷杀率（>5%跌幅）
            "light_muffled_rate": float,  # 轻度闷杀率（>3%跌幅）
            "heavy_muffled_rate": float,  # 重度闷杀率（>7%跌幅）
            "promotion_rates": dict,      # 各板数晋级率
        }
    """
    stocks = today_data.get("stocks", [])
    total = today_data.get("total", 0)

    if total == 0:
        return {
            "avg_return": 0, "continuous_premium": 0, "first_board_premium": 0,
            "high_open_rate": 0, "median_return": 0,
            "muffled_rate": 0, "light_muffled_rate": 0, "heavy_muffled_rate": 0,
            "promotion_rates": {},
        }

    returns = [s["today_return"] for s in stocks]
    avg_return = round(sum(returns) / total, 2) if total else 0
    median_return = round(sorted(returns)[total // 2], 2) if total else 0

    # 连板股溢价率（昨日连板>=2的股票今日平均涨幅）
    continuous_stocks = [s for s in stocks if s["yesterday_board_num"] >= 2]
    continuous_premium = (
        round(sum(s["today_return"] for s in continuous_stocks) / len(continuous_stocks), 2)
        if continuous_stocks else 0
    )

    # 首板股溢价率
    first_board_stocks = [s for s in stocks if s["yesterday_board_num"] == 1]
    first_board_premium = (
        round(sum(s["today_return"] for s in first_board_stocks) / len(first_board_stocks), 2)
        if first_board_stocks else 0
    )

    # 高开率
    high_open_count = sum(1 for s in stocks if s.get("high_open"))
    high_open_rate = round(high_open_count / total * 100, 1) if total else 0

    # 闷杀率分级
    light_muffled = sum(1 for s in stocks if s.get("is_light_muffled"))
    muffled = sum(1 for s in stocks if s.get("is_muffled"))
    heavy_muffled = sum(1 for s in stocks if s.get("is_heavy_muffled"))

    # 晋级率
    promotion_rates: dict[int, float] = {}
    for board_num in range(1, 10):
        candidates = [s for s in stocks if s["yesterday_board_num"] == board_num]
        if not candidates:
            continue
        promoted = sum(1 for s in candidates if s["today_board_num"] > board_num)
        promotion_rates[board_num] = round(promoted / len(candidates) * 100, 1)

    return {
        "avg_return": avg_return,
        "continuous_premium": continuous_premium,
        "first_board_premium": first_board_premium,
        "high_open_rate": high_open_rate,
        "median_return": median_return,
        "muffled_rate": round(muffled / total * 100, 1) if total else 0,
        "light_muffled_rate": round(light_muffled / total * 100, 1) if total else 0,
        "heavy_muffled_rate": round(heavy_muffled / total * 100, 1) if total else 0,
        "promotion_rates": promotion_rates,
    }


# ---------------------------------------------------------------------------
# P2-05: 梯队健康度评分
# ---------------------------------------------------------------------------

def _calculate_board_health(board_dist: dict) -> float:
    """梯队健康度评分（0-100）。

    逻辑:
    - 完整梯队（5-4-3-2-1都有）: 高分
    - 有断层（缺少某个板数）: 扣分
    - 只有高位没有低位: 低分
    - 梯队越高分越多: 额外加分

    参数:
        board_dist: {"highest_board": int, "distribution": {板数: 数量}, "total": int}

    返回:
        0-100 的健康度评分
    """
    dist = board_dist.get("distribution", {})
    highest = board_dist.get("highest_board", 0)
    total = board_dist.get("total", 0)

    if total == 0 or highest == 0:
        return 0

    score = 0

    # 1. 完整性评分（40分）: 检查梯队是否有断层
    expected_boards = list(range(1, highest + 1))
    present_boards = [b for b in expected_boards if dist.get(b, 0) > 0]
    completeness = len(present_boards) / max(len(expected_boards), 1)
    score += completeness * 40

    # 2. 高度评分（25分）: 梯队越高越好
    height_score = min(highest / 7, 1.0) * 25
    score += height_score

    # 3. 密度评分（20分）: 低位梯队数量充足
    low_count = dist.get(1, 0) + dist.get(2, 0)
    density = min(low_count / 20, 1.0) * 20
    score += density

    # 4. 均匀度评分（15分）: 各板数数量递减
    if highest >= 3:
        counts = [dist.get(b, 0) for b in range(1, highest + 1)]
        # 理想情况: 低位多高位少（递减序列）
        is_decreasing = all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1))
        if is_decreasing:
            score += 15
        else:
            # 部分递减也给分
            decreasing_pairs = sum(
                1 for i in range(len(counts) - 1) if counts[i] >= counts[i + 1]
            )
            score += (decreasing_pairs / max(len(counts) - 1, 1)) * 15

    return round(min(score, 100), 1)


# ---------------------------------------------------------------------------
# P2-06: 情绪周期判断
# ---------------------------------------------------------------------------

def _judge_emotion_phase(
    seal_quality: dict,
    yesterday_performance: dict,
    board_dist: dict,
    market_breadth: dict,
    northbound_signal: dict,
    recent_2day_data: list[dict] | None = None,
) -> str:
    """情绪周期判断（含冰点确认机制）。

    核心逻辑:
    1. 高标股状态是第一判断依据
    2. 连板梯队健康度
    3. 赚钱效应 + 亏钱效应
    4. 北向资金方向
    5. 市场宽度（涨跌家数比）

    冰点确认机制:
    - 单日冰点信号: 高标断板 + 梯队崩塌 + 重度闷杀率>30%
    - 确认冰点: 需要连续2天满足以下任意2条
      * 高标断板或降级
      * 闷杀率>25%
      * 晋级率<20%
      * 北向资金连续流出

    返回: "冰点" | "冰点（已确认）" | "低迷" | "修复" | "升温" | "高潮" | "退潮"
    """
    highest = board_dist.get("highest_board", 0)
    total = board_dist.get("total", 0)
    dist = board_dist.get("distribution", {})
    avg_return = yesterday_performance.get("avg_return", 0)
    heavy_muffled = yesterday_performance.get("heavy_muffled_rate", 0)
    muffled = yesterday_performance.get("muffled_rate", 0)
    continuous_premium = yesterday_performance.get("continuous_premium", 0)
    promotion_rates = yesterday_performance.get("promotion_rates", {})
    ad_ratio = market_breadth.get("ad_ratio", 1)
    northbound_dir = northbound_signal.get("direction", "无数据")

    # 冰点确认机制
    if recent_2day_data and len(recent_2day_data) >= 2:
        confirm_count = 0
        for day_data in recent_2day_data:
            conditions_met = 0
            if day_data.get("highest_board_dropped"):
                conditions_met += 1
            if day_data.get("heavy_muffled_rate", 0) > 25:
                conditions_met += 1
            avg_promo = day_data.get("avg_promotion_rate", 100)
            if avg_promo < 20:
                conditions_met += 1
            if day_data.get("northbound_direction") in ("小幅流出", "大幅流出"):
                conditions_met += 1
            if conditions_met >= 2:
                confirm_count += 1

        if confirm_count >= 2:
            return "冰点（已确认）"

    # 单日判断
    # 冰点: 高标断板 + 梯队崩塌 + 重度闷杀率高
    if highest <= 2 and heavy_muffled > 30 and total < 15:
        return "冰点"

    # 退潮: 高标开始分歧 + 低位晋级率下降
    avg_promotion = (
        sum(promotion_rates.values()) / len(promotion_rates)
        if promotion_rates else 0
    )
    if highest >= 3 and heavy_muffled > 20 and avg_promotion < 30:
        return "退潮"

    # 高潮: 高标持续封板 + 梯队完整 + 赚钱效应强
    board_health = _calculate_board_health(board_dist)
    if (highest >= 5 and board_health > 70 and avg_return > 2
            and heavy_muffled < 10 and ad_ratio > 2):
        return "高潮"

    # 升温: 连板梯队恢复 + 赚钱效应回升
    if highest >= 3 and board_health > 50 and avg_return > 0 and muffled < 20:
        return "升温"

    # 修复: 高标断板后有新龙接力 + 闷杀率下降
    if highest >= 2 and avg_return > -1 and muffled < 25:
        return "修复"

    # 低迷
    if heavy_muffled > 15 or avg_return < -2:
        return "低迷"

    return "修复"


# ---------------------------------------------------------------------------
# P2-07: 情绪指标汇总
# ---------------------------------------------------------------------------

def _calculate_emotion_metrics(
    limitup_stocks: list[dict],
    limitdown_stocks: list[dict],
    yesterday_performance: dict,
    market_breadth: dict,
    northbound_signal: dict,
    recent_2day_data: list[dict] | None = None,
) -> dict:
    """计算情绪量化指标汇总。

    参数:
        limitup_stocks: 涨停股票列表（_get_limitup_stocks 返回值）
        limitdown_stocks: 跌停股票列表（_get_limitdown_stocks 返回值）
        yesterday_performance: 昨日涨停表现（_calculate_yesterday_performance 返回值）
        market_breadth: 市场涨跌家数（_get_market_breadth 返回值）
        northbound_signal: 北向资金信号（_get_northbound_flow_signal 返回值）
        recent_2day_data: 近2天数据（冰点确认用）

    返回:
        {
            "highest_board": int,
            "board_distribution": dict,
            "limitup_count": int,
            "limitdown_count": int,
            "yizi_count": int,
            "huan_shou_count": int,
            "seal_quality": dict,
            "yesterday_performance": dict,
            "board_health_score": float,
            "emotion_phase": str,
            "emotion_score": float,
            "market_breadth": dict,
            "northbound_signal": dict,
        }
    """
    board_dist = _get_board_distribution(limitup_stocks)
    seal_quality = _calculate_seal_quality(limitup_stocks)
    board_health = _calculate_board_health(board_dist)

    emotion_phase = _judge_emotion_phase(
        seal_quality, yesterday_performance, board_dist,
        market_breadth, northbound_signal, recent_2day_data,
    )

    # 情绪综合评分 (0-100)
    emotion_score = _compute_emotion_score(
        board_dist, seal_quality, yesterday_performance,
        board_health, market_breadth, northbound_signal,
    )

    return {
        "highest_board": board_dist["highest_board"],
        "board_distribution": board_dist["distribution"],
        "limitup_count": len(limitup_stocks),
        "limitdown_count": len(limitdown_stocks),
        "yizi_count": seal_quality["yizi_count"],
        "huan_shou_count": seal_quality["huan_shou_count"],
        "seal_quality": seal_quality,
        "yesterday_performance": yesterday_performance,
        "board_health_score": board_health,
        "emotion_phase": emotion_phase,
        "emotion_score": emotion_score,
        "market_breadth": market_breadth,
        "northbound_signal": northbound_signal,
    }


def _compute_emotion_score(
    board_dist: dict,
    seal_quality: dict,
    yesterday_performance: dict,
    board_health: float,
    market_breadth: dict,
    northbound_signal: dict,
) -> float:
    """计算情绪综合评分 (0-100)。

    权重分配:
    - 梯队健康度: 25%
    - 封板质量: 20%
    - 赚钱效应: 25%
    - 市场宽度: 15%
    - 北向资金: 15%
    """
    score = 0

    # 1. 梯队健康度 (25分)
    score += board_health * 0.25

    # 2. 封板质量 (20分)
    seal_rate = seal_quality.get("effective_seal_rate", 0)
    score += min(seal_rate / 100, 1.0) * 20

    # 3. 赚钱效应 (25分)
    avg_return = yesterday_performance.get("avg_return", 0)
    muffled_rate = yesterday_performance.get("muffled_rate", 0)
    # 涨幅转评分: -5% -> 0, 0% -> 50, 5% -> 100
    return_score = max(0, min((avg_return + 5) / 10 * 100, 100))
    # 闷杀率扣分: 0% -> 0扣, 30% -> 全扣
    muffled_penalty = min(muffled_rate / 30, 1.0) * 50
    score += (return_score * 0.5 + (100 - muffled_penalty) * 0.5) * 0.25

    # 4. 市场宽度 (15分)
    ad_ratio = market_breadth.get("ad_ratio", 1)
    # ad_ratio: 0 -> 0分, 1 -> 50分, 3+ -> 100分
    breadth_score = min(ad_ratio / 3, 1.0) * 100
    score += breadth_score * 0.15

    # 5. 北向资金 (15分)
    direction = northbound_signal.get("direction", "无数据")
    direction_scores = {
        "大幅流入": 100, "小幅流入": 70,
        "小幅流出": 30, "大幅流出": 0, "无数据": 50,
    }
    score += direction_scores.get(direction, 50) * 0.15

    return round(min(score, 100), 1)


# ---------------------------------------------------------------------------
# P2-08: 主接口 - 连板梯队统计 + 情绪量化
# ---------------------------------------------------------------------------

def get_consecutive_limit_stats(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
) -> str:
    """连板梯队统计 + 情绪量化。

    返回内容:
    1. 连板梯队分布（高度标、各板数股票数量）
    2. 赚钱效应指标（昨日涨停今日表现）
    3. 封板强度指标（一字板/换手板拆分）
    4. 情绪周期判断（冰点/低迷/修复/升温/高潮/退潮）
    5. 梯队健康度评分
    6. 市场宽度（涨跌家数比）
    7. 北向资金信号

    数据源: 同花顺 getharden + mootdx K线 + 东财选股/ push2 + 腾讯财经
    限流: _em_get()（仅东财部分）
    """
    if not trade_date or trade_date.strip() == "":
        trade_date = datetime.now().strftime("%Y-%m-%d")

    try:
        # 1. 获取当日涨停/跌停
        limitup_stocks = _get_limitup_stocks(trade_date)
        limitdown_stocks = _get_limitdown_stocks(trade_date)

        # 2. 昨日涨停今日表现
        yesterday_data = _get_yesterday_limitup_performance(trade_date)
        yesterday_perf = _calculate_yesterday_performance(yesterday_data)

        # 3. 市场宽度 + 北向资金
        market_breadth = _get_market_breadth(trade_date)
        northbound_signal = _get_northbound_flow_signal(trade_date)

        # 4. 汇总情绪指标
        metrics = _calculate_emotion_metrics(
            limitup_stocks, limitdown_stocks, yesterday_perf,
            market_breadth, northbound_signal,
        )

        # 5. 格式化输出
        return _format_consecutive_limit_stats(metrics, limitup_stocks, trade_date)

    except Exception as e:
        return f"连板梯队统计获取失败 ({trade_date}): {str(e)}"


def _format_consecutive_limit_stats(
    metrics: dict,
    limitup_stocks: list[dict],
    trade_date: str,
) -> str:
    """格式化连板梯队统计输出。"""
    lines = [
        f"# 连板梯队统计 + 情绪量化 | {trade_date}",
        f"# Source: 同花顺 + mootdx + 东财 + 腾讯财经",
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # 情绪总览
    lines.append("## 情绪总览")
    lines.append(f"  情绪周期: {metrics['emotion_phase']}")
    lines.append(f"  情绪评分: {metrics['emotion_score']}/100")
    lines.append(f"  最高连板: {metrics['highest_board']}板")
    lines.append(f"  涨停家数: {metrics['limitup_count']} | 跌停家数: {metrics['limitdown_count']}")
    lines.append(f"  一字板: {metrics['yizi_count']} | 换手板: {metrics['huan_shou_count']}")
    lines.append("")

    # 连板梯队分布
    lines.append("## 连板梯队分布")
    dist = metrics.get("board_distribution", {})
    for board in sorted(dist.keys(), reverse=True):
        count = dist[board]
        bar = "█" * min(count, 30)
        lines.append(f"  {board}板: {count:>3}只 {bar}")
    lines.append(f"  梯队健康度: {metrics['board_health_score']}/100")
    lines.append("")

    # 封板质量
    sq = metrics.get("seal_quality", {})
    lines.append("## 封板质量")
    lines.append(f"  有效封板率: {sq.get('effective_seal_rate', 0)}%")
    lines.append(f"  封板成功率: {sq.get('seal_success_rate', 0)}%")
    lines.append(f"  封单强度中位数: {sq.get('seal_strength_median', 0)}")
    lines.append("")

    # 赚钱效应
    yp = metrics.get("yesterday_performance", {})
    lines.append("## 赚钱效应（昨日涨停今日表现）")
    lines.append(f"  平均涨幅: {yp.get('avg_return', 0)}%")
    lines.append(f"  连板股溢价率: {yp.get('continuous_premium', 0)}%")
    lines.append(f"  首板股溢价率: {yp.get('first_board_premium', 0)}%")
    lines.append(f"  高开率: {yp.get('high_open_rate', 0)}%")
    lines.append(f"  涨幅中位数: {yp.get('median_return', 0)}%")
    lines.append(f"  闷杀率(>5%): {yp.get('muffled_rate', 0)}%")
    lines.append(f"  轻度闷杀(>3%): {yp.get('light_muffled_rate', 0)}%")
    lines.append(f"  重度闷杀(>7%): {yp.get('heavy_muffled_rate', 0)}%")
    promo = yp.get("promotion_rates", {})
    if promo:
        lines.append("  晋级率:")
        for board_num in sorted(promo.keys()):
            lines.append(f"    {board_num}板→{board_num + 1}板: {promo[board_num]}%")
    lines.append("")

    # 市场宽度
    mb = metrics.get("market_breadth", {})
    lines.append("## 市场宽度")
    lines.append(f"  上涨: {mb.get('up_count', 0)} | 下跌: {mb.get('down_count', 0)} | 平盘: {mb.get('flat_count', 0)}")
    lines.append(f"  涨跌家数比: {mb.get('ad_ratio', 0)} ({mb.get('breadth_signal', '无数据')})")
    lines.append("")

    # 北向资金
    ns = metrics.get("northbound_signal", {})
    lines.append("## 北向资金")
    lines.append(f"  净流入: {ns.get('net_inflow', 0)}亿元 ({ns.get('direction', '无数据')})")
    lines.append("")

    # 涨停股明细（前20只）
    if limitup_stocks:
        lines.append("## 涨停股明细（前20只）")
        lines.append("  代码 | 名称 | 连板 | 类型 | 原因")
        lines.append("  --- | --- | --- | --- | ---")
        sorted_stocks = sorted(limitup_stocks, key=lambda x: x.get("consecutive_days", 0), reverse=True)
        for s in sorted_stocks[:20]:
            lines.append(
                f"  {s['code']} | {s.get('name', '')} | "
                f"{s.get('consecutive_days', 1)}板 | "
                f"{s.get('limit_type', '')} | "
                f"{s.get('reason', '')[:30]}"
            )

    return "\n".join(lines)


# 巨潮 股票→orgId 映射（模块级缓存，首次调用时拉取一次，全程复用）
_CNINFO_ORGID_MAP: dict[str, str] = {}


def _cninfo_orgid(code: str) -> str:
    """查股票真实 orgId。

    巨潮 orgId 并非统一 `gssx0{code}` 格式（如 601318→9900002221、
    601398→jjxt0000019、688017→9900041602），硬编码会导致大量股票（尤其 601xxx 段）
    返回 totalAnnouncement=0、查不到公告。
    优先动态查官方映射表，查不到再回退硬编码。
    """
    global _CNINFO_ORGID_MAP
    if not _CNINFO_ORGID_MAP:
        try:
            r = _requests.get(
                "http://www.cninfo.com.cn/new/data/szse_stock.json",
                headers={"User-Agent": _UA},
                timeout=15,
            )
            _CNINFO_ORGID_MAP = {
                s["code"]: s["orgId"]
                for s in r.json().get("stockList", [])
            }
        except Exception as e:
            logger.warning("巨潮 orgId 映射表拉取失败，回退硬编码规则: %s", e)

    org = _CNINFO_ORGID_MAP.get(code)
    if org:
        return org

    # fallback：老格式（仅部分老股票如 600519/600036 适用）
    if code.startswith("6"):
        return f"gssh0{code}"
    elif code.startswith("8") or code.startswith("4"):
        return f"gsbj0{code}"
    return f"gssz0{code}"


def _cninfo_ts_to_date(ts) -> str:
    """巨潮 announcementTime 返回 Unix 毫秒整数，需转换为日期字符串。"""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
    return str(ts)[:10] if ts else ""


def get_cninfo_announcements(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
    page_size: Annotated[int, "Number of announcements (default 30)"] = 30,
) -> str:
    """Get official company announcements from cninfo (巨潮公告).

    Returns announcement title, type, date, and detail URL.
    cninfo is the legally binding disclosure channel in China.
    Many material events appear here 1-3 days before news articles:
    - 股权质押公告 (equity pledge)
    - 关联交易公告 (related-party transaction)
    - 年报/季报 (financial reports)
    - 股东减持计划 (shareholder reduction plans)

    Data source: cninfo.com.cn (巨潮资讯).
    """
    code = _normalize_ticker(ticker)

    try:
        org_id = _cninfo_orgid(code)

        url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
        payload = {
            "stock": f"{code},{org_id}",
            "tabName": "fulltext",
            "pageSize": str(page_size),
            "pageNum": "1",
            "column": "",
            "category": "",
            "plate": "",
            "seDate": "",
            "searchkey": "",
            "secid": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        headers = {
            "User-Agent": _UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.cninfo.com.cn/new/disclosure",
            "Origin": "https://www.cninfo.com.cn",
        }
        r = _requests.post(url, data=payload, headers=headers, timeout=15)
        d = r.json()

        announcements = d.get("announcements") or []
        if not announcements:
            return f"No announcements found for {code}"

        lines = [
            f"# 巨潮公告 | {code}",
            f"# Source: cninfo.com.cn (巨潮资讯)",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# 共 {len(announcements)} 条公告",
            "",
            "日期 | 类型 | 标题",
            "--- | --- | ---",
        ]

        # 按类型统计
        type_counts: dict[str, int] = {}
        risk_keywords = ["质押", "减持", "担保", "诉讼", "处罚", "违规", "风险"]
        risk_announcements = []

        for ann in announcements:
            date_str = _cninfo_ts_to_date(ann.get("announcementTime"))
            ann_type = ann.get("announcementTypeName", "")
            title = (ann.get("announcementTitle", "") or "").replace("<em>", "").replace("</em>", "")
            ann_id = ann.get("announcementId", "")

            type_counts[ann_type] = type_counts.get(ann_type, 0) + 1

            lines.append(f"  {date_str} | {ann_type} | {title[:60]}")

            # 检测风险公告
            if any(kw in title for kw in risk_keywords):
                risk_announcements.append({
                    "date": date_str,
                    "type": ann_type,
                    "title": title[:80],
                })

        # 类型分布
        lines.append("")
        lines.append("## 公告类型分布")
        for ann_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            if ann_type:
                lines.append(f"  {ann_type}: {count} 条")

        # 风险公告预警
        if risk_announcements:
            lines.append("")
            lines.append("## ⚠️ 风险相关公告")
            for ra in risk_announcements[:5]:
                lines.append(f"  {ra['date']} | {ra['type']} | {ra['title']}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error fetching cninfo announcements for {code}: {str(e)}"


# ===========================================================================
# Phase 3: 题材热度追踪 (P3-01 ~ P3-09)
# 涨停按题材聚合、题材历史热度、题材阶段判断、辨识度评分、热度评分
# ===========================================================================


# ---------------------------------------------------------------------------
# P3-01: 涨停按题材聚合
# ---------------------------------------------------------------------------

def _get_limitup_by_theme(trade_date: str) -> dict[str, list[dict]]:
    """获取涨停股票按题材聚合（归一化后）。

    逻辑:
    1. 获取当日涨停列表（含涨停原因）
    2. 对涨停原因做归一化
    3. 按归一化后的题材聚合（同一股票可能出现在多个题材中）

    返回:
        {"AI概念": [{"code": "000001", "name": "股票A", "board_num": 3, ...}], ...}

    数据源: _get_limitup_stocks (同花顺 getharden + mootdx + 东财)
    """
    cache_key = ("limitup_by_theme", trade_date)
    if cache_key in _session_cache:
        return _session_cache[cache_key]

    limitup_stocks = _get_limitup_stocks(trade_date)
    if not limitup_stocks:
        return {}

    theme_map: dict[str, list[dict]] = {}
    for stock in limitup_stocks:
        raw_reason = stock.get("reason", "")
        if not raw_reason:
            continue

        # 涨停原因可能是 "+" 分隔的多个原因（如"AI概念+大模型"）
        reasons = [r.strip() for r in raw_reason.replace("，", "+").split("+") if r.strip()]
        for reason in reasons:
            normalized = _normalize_theme_name(reason)
            if not normalized:
                continue
            if normalized not in theme_map:
                theme_map[normalized] = []
            theme_map[normalized].append({
                "code": stock["code"],
                "name": stock.get("name", ""),
                "board_num": stock.get("consecutive_days", 1),
                "limit_type": stock.get("limit_type", ""),
                "raw_reason": reason,
                "circulation_mv": stock.get("circulation_mv", 0),
                "turnover_rate": stock.get("turnover_rate", 0),
            })

    _session_cache[cache_key] = theme_map
    return theme_map


# ---------------------------------------------------------------------------
# P3-02: 题材历史热度
# ---------------------------------------------------------------------------

def _get_theme_history(theme_name: str, days: int = 7) -> list[dict]:
    """获取某题材近N日涨停情况。

    返回:
        [{"date": "2026-06-13", "count": 12, "highest_board": 5}, ...]

    注意:
    - 返回所有日期（包括count=0的日期），用于计算"活跃天数"
    - 通过回溯N天的涨停数据并按归一化题材聚合
    """
    from datetime import timedelta

    history: list[dict] = []
    for i in range(days):
        dt = datetime.now() - timedelta(days=i)
        date_str = dt.strftime("%Y-%m-%d")
        # 跳过周末
        if dt.weekday() >= 5:
            continue

        try:
            theme_map = _get_limitup_by_theme(date_str)
            theme_stocks = theme_map.get(theme_name, [])
            count = len(theme_stocks)
            highest_board = max((s.get("board_num", 0) for s in theme_stocks), default=0)
        except Exception:
            count = 0
            highest_board = 0

        history.append({
            "date": date_str,
            "count": count,
            "highest_board": highest_board,
        })

    return history


# ---------------------------------------------------------------------------
# P3-03: 题材龙头状态
# ---------------------------------------------------------------------------

def _get_theme_leader_status(theme_name: str, theme_stocks: list[dict]) -> dict:
    """获取题材龙头状态。

    参数:
        theme_name: 归一化后的题材名称
        theme_stocks: 该题材下的涨停股票列表（从 _get_limitup_by_theme 获取）

    返回:
        {
            "leader_code": "000001",
            "leader_name": "股票A",
            "leader_board_num": 5,
            "leader_seal_status": "封板",  # 封板/分歧/断板
            "has_deputy": True,            # 是否有补涨龙
            "deputy_count": 2,             # 补涨龙数量（2-3板）
        }

    数据源: 腾讯财经（实时行情判断封板状态）
    """
    if not theme_stocks:
        return {
            "leader_code": "", "leader_name": "", "leader_board_num": 0,
            "leader_seal_status": "无", "has_deputy": False, "deputy_count": 0,
        }

    # 找最高连板的股票作为龙头
    sorted_stocks = sorted(theme_stocks, key=lambda x: x.get("board_num", 0), reverse=True)
    leader = sorted_stocks[0]
    leader_code = leader["code"]
    leader_board = leader.get("board_num", 1)

    # 通过实时行情判断封板状态
    seal_status = "封板"  # 默认涨停列表中的股票都是封板状态
    try:
        quote = _get_stock_realtime_quote(leader_code)
        if quote:
            # 如果当前价低于涨停价，说明已分歧
            last_close = quote.get("last_close", 0)
            price = quote.get("price", 0)
            limit_up = quote.get("limit_up", 0)
            if last_close > 0 and limit_up > 0:
                limit_price = round(last_close * 1.1, 2)
                if price < limit_price - 0.01:
                    seal_status = "分歧"
    except Exception:
        pass

    # 统计补涨龙数量（2-3板）
    deputy_stocks = [s for s in theme_stocks if 2 <= s.get("board_num", 0) <= 3]
    deputy_count = len(deputy_stocks)

    return {
        "leader_code": leader_code,
        "leader_name": leader.get("name", ""),
        "leader_board_num": leader_board,
        "leader_seal_status": seal_status,
        "has_deputy": deputy_count > 0,
        "deputy_count": deputy_count,
    }


# ---------------------------------------------------------------------------
# P3-04: 活跃天数计算
# ---------------------------------------------------------------------------

def _get_theme_active_days(theme_history: list[dict]) -> int:
    """计算题材活跃天数。

    逻辑: 近N日内有涨停的天数（不要求连续）
    例: 近7天有5天出现涨停 → 活跃天数=5
    """
    return sum(1 for day in theme_history if day.get("count", 0) > 0)


# ---------------------------------------------------------------------------
# P3-05: 题材阶段判断
# ---------------------------------------------------------------------------

_THEME_PHASES = ("试探期", "发酵期", "主升期", "高潮期", "退潮期", "冰点期")


def _get_theme_phase(
    theme_stocks: list[dict],
    theme_history: list[dict],
    leader_status: dict,
) -> dict:
    """题材阶段判断（实战版）。

    阶段定义:
    1. 试探期（1-2天）：涨停家数2-5只，无连板
    2. 发酵期（2-3天）：涨停家数5-10只，出现2板
    3. 主升期（3-5天）：涨停家数>10只，连板梯队完整
    4. 高潮期（1-2天）：涨停家数达到峰值，后排也开始涨停
    5. 退潮期（2-3天）：涨停家数锐减，龙头开始分歧
    6. 冰点期：涨停家数<3只，龙头断板

    返回:
        {"phase": str, "reason": str, "duration": int}
    """
    stock_count = len(theme_stocks)
    highest_board = leader_status.get("leader_board_num", 0)
    leader_seal = leader_status.get("leader_seal_status", "无")
    active_days = _get_theme_active_days(theme_history)

    # 计算趋势方向（看近3天涨停数变化）
    recent_counts = [d["count"] for d in theme_history[:3] if d["date"] <= datetime.now().strftime("%Y-%m-%d")]
    trend_up = len(recent_counts) >= 2 and recent_counts[0] > recent_counts[-1]
    trend_down = len(recent_counts) >= 2 and recent_counts[0] < recent_counts[-1]

    # 冰点期: 涨停家数<3 且 (龙头断板 或 最高板<=1且封板数少)
    if stock_count < 3 and leader_seal == "断板":
        return {"phase": "冰点期", "reason": "涨停家数<3且龙头断板", "duration": active_days}
    if stock_count < 2 and highest_board <= 1:
        return {"phase": "冰点期", "reason": "涨停极少且无连板", "duration": active_days}

    # 退潮期: 涨停数锐减 + 龙头分歧
    if trend_down and leader_seal == "分歧":
        return {"phase": "退潮期", "reason": "涨停数减少且龙头分歧", "duration": active_days}

    # 高潮期: 涨停数达到峰值
    if len(theme_history) >= 2 and recent_counts:
        max_count = max(d["count"] for d in theme_history)
        if recent_counts[0] >= max_count * 0.9 and stock_count >= 10:
            return {"phase": "高潮期", "reason": "涨停数达到峰值", "duration": active_days}

    # 主升期: 涨停家数>10只，连板梯队完整
    if stock_count > 10 and highest_board >= 3:
        return {"phase": "主升期", "reason": "涨停数>10且连板梯队完整", "duration": active_days}

    # 发酵期: 涨停家数5-10只，出现2板
    if 5 <= stock_count <= 10 and highest_board >= 2:
        return {"phase": "发酵期", "reason": "涨停数5-10只且出现连板", "duration": active_days}

    # 试探期: 涨停家数2-5只，无连板
    if 2 <= stock_count <= 5 and highest_board <= 1:
        return {"phase": "试探期", "reason": "涨停数2-5只且无连板", "duration": active_days}

    # 默认: 根据涨停数粗判
    if stock_count > 10:
        return {"phase": "主升期", "reason": "涨停数较多", "duration": active_days}
    if stock_count >= 5:
        return {"phase": "发酵期", "reason": "涨停数中等", "duration": active_days}
    return {"phase": "试探期", "reason": "涨停数较少", "duration": active_days}


# ---------------------------------------------------------------------------
# P3-06: 题材趋势判断
# ---------------------------------------------------------------------------

def _calculate_theme_trend(
    theme_history: list[dict],
    leader_seal_status: str,
) -> str:
    """题材热度趋势判断（实战版）。

    核心逻辑:
    1. 看3日趋势，不是2日
    2. 结合龙头状态
    3. 特殊情况处理（周末/节假日效应）

    返回: "升温" | "高潮" | "退潮" | "震荡"
    """
    if not theme_history or len(theme_history) < 2:
        return "震荡"

    counts = [d["count"] for d in theme_history]

    # 只看近3天有效数据（count>0或最近3天）
    recent = counts[:3]
    if len(recent) < 2:
        return "震荡"

    # 计算趋势
    increasing = sum(1 for i in range(len(recent) - 1) if recent[i] >= recent[i + 1])
    decreasing = sum(1 for i in range(len(recent) - 1) if recent[i] <= recent[i + 1])

    # 结合龙头状态修正
    if leader_seal_status == "分歧" or leader_seal_status == "断板":
        if recent[0] < recent[-1]:
            return "退潮"

    if increasing >= 2 and recent[0] > recent[-1]:
        return "升温"

    if decreasing >= 2 and recent[0] < recent[-1]:
        return "退潮"

    # 先增后减: 高潮转退潮
    if len(recent) >= 3 and recent[0] < recent[1] and recent[1] > recent[2]:
        return "高潮"

    return "震荡"


# ---------------------------------------------------------------------------
# P3-07: 辨识度评分
# ---------------------------------------------------------------------------

def _calculate_theme_recognition_score(
    stock_count: int,
    highest_board: int,
    leader_seal_status: str,
    seal_concentration: float,
    northbound_inflow: bool,
) -> dict:
    """题材辨识度评分（五维度量化）。

    评分维度:
    1. 涨停家数 >=10 → +30分
    2. 有连板梯队（>=3板）→ +25分
    3. 龙头封板状态 → +20分
    4. 封单集中度 → +15分
    5. 北向资金流入 → +10分

    返回:
        {"score": float (0-100), "level": str, "breakdown": dict}
    """
    score = 0
    breakdown: dict[str, int] = {}

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


# ---------------------------------------------------------------------------
# P3-08: 热度评分
# ---------------------------------------------------------------------------

def _calculate_heat_score(
    stock_count: int,
    highest_board: int,
    active_days: int,
    phase: str,
    leader_seal_status: str,
    northbound_direction: str,
) -> float:
    """热度评分计算（权重已调整）。

    权重（修正后）:
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


# ---------------------------------------------------------------------------
# P3-09: 主接口 - 题材热度排名 + 周期评估
# ---------------------------------------------------------------------------

def get_theme_heat(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
    top_n: Annotated[int, "返回前N个题材, 默认10"] = 10,
) -> str:
    """题材热度排名 + 周期评估。

    返回内容:
    1. 按涨停家数排名的概念板块（涨停原因归一化后）
    2. 每个板块内涨停股票列表
    3. 板块活跃天数（近N日内有涨停的天数）
    4. 板块热度趋势（升温/高潮/退潮）
    5. 题材辨识度评分
    6. 龙头状态

    数据源: 同花顺 getharden + mootdx K线 + 东财选股 + 腾讯财经 + 同花顺北向
    限流: _em_get()（仅东财部分）
    """
    if not trade_date or trade_date.strip() == "":
        trade_date = datetime.now().strftime("%Y-%m-%d")

    try:
        # 1. 获取当日涨停按题材聚合
        theme_map = _get_limitup_by_theme(trade_date)
        if not theme_map:
            return f"无涨停数据（非交易日或盘后未更新）| {trade_date}"

        # 2. 获取北向资金信号（全局复用）
        northbound_signal = _get_northbound_flow_signal(trade_date)
        northbound_direction = northbound_signal.get("direction", "无数据")

        # 3. 逐题材计算指标
        theme_reports: list[dict] = []
        for theme_name, theme_stocks in theme_map.items():
            stock_count = len(theme_stocks)
            highest_board = max((s.get("board_num", 0) for s in theme_stocks), default=0)

            # 龙头状态
            leader_status = _get_theme_leader_status(theme_name, theme_stocks)

            # 历史热度（近7天）
            theme_history = _get_theme_history(theme_name, days=7)

            # 活跃天数
            active_days = _get_theme_active_days(theme_history)

            # 题材阶段
            phase_info = _get_theme_phase(theme_stocks, theme_history, leader_status)

            # 题材趋势
            trend = _calculate_theme_trend(theme_history, leader_status.get("leader_seal_status", "无"))

            # 辨识度评分
            recognition = _calculate_theme_recognition_score(
                stock_count=stock_count,
                highest_board=highest_board,
                leader_seal_status=leader_status.get("leader_seal_status", "无"),
                seal_concentration=0.5,  # 简化: 缺少封单集中度数据
                northbound_inflow=northbound_direction in ("大幅流入", "小幅流入"),
            )

            # 热度评分
            heat_score = _calculate_heat_score(
                stock_count=stock_count,
                highest_board=highest_board,
                active_days=active_days,
                phase=phase_info["phase"],
                leader_seal_status=leader_status.get("leader_seal_status", "无"),
                northbound_direction=northbound_direction,
            )

            theme_reports.append({
                "theme_name": theme_name,
                "stock_count": stock_count,
                "stocks": theme_stocks,
                "highest_board": highest_board,
                "active_days": active_days,
                "phase": phase_info["phase"],
                "phase_reason": phase_info.get("reason", ""),
                "trend": trend,
                "heat_score": heat_score,
                "recognition": recognition,
                "leader_status": leader_status,
            })

        # 4. 按热度评分排序
        theme_reports.sort(key=lambda x: x["heat_score"], reverse=True)

        # 5. 格式化输出
        return _format_theme_heat(theme_reports, trade_date, top_n, northbound_signal)

    except Exception as e:
        return f"题材热度获取失败 ({trade_date}): {str(e)}"


def _format_theme_heat(
    theme_reports: list[dict],
    trade_date: str,
    top_n: int,
    northbound_signal: dict,
) -> str:
    """格式化题材热度输出。"""
    lines = [
        f"# 题材热度排名 | {trade_date}",
        f"# Source: 同花顺 + mootdx + 东财 + 腾讯财经",
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # 总览
    total_themes = len(theme_reports)
    total_stocks = sum(r["stock_count"] for r in theme_reports)
    lines.append("## 总览")
    lines.append(f"  活跃题材数: {total_themes}")
    lines.append(f"  涨停总家数: {total_stocks}")
    lines.append("")

    # 排名
    lines.append("## 题材热度排名")
    lines.append("  排名 | 题材 | 涨停数 | 最高板 | 活跃天 | 阶段 | 趋势 | 热度分 | 辨识度")
    lines.append("  --- | --- | --- | --- | --- | --- | --- | --- | ---")

    for i, report in enumerate(theme_reports[:top_n]):
        rec = report["recognition"]
        lines.append(
            f"  {i+1}. {report['theme_name']} "
            f"| {report['stock_count']}只 "
            f"| {report['highest_board']}板 "
            f"| {report['active_days']}天 "
            f"| {report['phase']} "
            f"| {report['trend']} "
            f"| {report['heat_score']} "
            f"| {rec['level']}"
        )
    lines.append("")

    # 各题材详情
    for i, report in enumerate(theme_reports[:min(top_n, 5)]):
        lines.append(f"### {i+1}. {report['theme_name']} (热度 {report['heat_score']})")

        # 龙头信息
        leader = report["leader_status"]
        if leader.get("leader_code"):
            lines.append(
                f"  龙头: {leader['leader_code']} {leader.get('leader_name', '')} "
                f"{leader['leader_board_num']}板 [{leader['leader_seal_status']}]"
            )
            if leader.get("has_deputy"):
                lines.append(f"  补涨龙: {leader['deputy_count']}只")

        # 辨识度评分
        rec = report["recognition"]
        lines.append(
            f"  辨识度: {rec['score']}分 ({rec['level']})"
        )
        breakdown = rec.get("breakdown", {})
        parts = [f"{k}={v}" for k, v in breakdown.items()]
        lines.append(f"    明细: {' + '.join(parts)}")

        # 涨停股票
        stocks = report["stocks"]
        lines.append(f"  涨停股 ({len(stocks)}只):")
        for s in sorted(stocks, key=lambda x: x.get("board_num", 0), reverse=True)[:10]:
            lines.append(
                f"    {s['code']} {s.get('name', '')} "
                f"{s.get('board_num', 1)}板 "
                f"{s.get('limit_type', '')} "
                f"({s.get('raw_reason', '')})"
            )
        lines.append("")

    # 北向资金
    ns = northbound_signal
    lines.append("## 北向资金")
    lines.append(f"  净流入: {ns.get('net_inflow', 0)}亿元 ({ns.get('direction', '无数据')})")

    return "\n".join(lines)


# ===========================================================================
# Phase 5: 高标股状态监控
# ===========================================================================


def _get_high_board_stocks(trade_date: str) -> list[dict]:
    """获取市场最高板股票。

    从涨停股中找出连板天数最高的股票，可能有多只同板。

    返回:
        [{"code": "000001", "name": "股票A", "reason": "AI概念",
          "consecutive_days": 5, "limit_type": "换手",
          "circulation_mv": 5e9, "turnover_rate": 0.08,
          "amount": 2e8}, ...]

    数据源: _get_limitup_stocks (同花顺 + mootdx + 东财)
    """
    try:
        limitup_stocks = _get_limitup_stocks(trade_date)
        if not limitup_stocks:
            return []

        max_board = max(
            (s.get("consecutive_days", 0) for s in limitup_stocks), default=0
        )
        if max_board <= 0:
            return []

        return [
            s for s in limitup_stocks
            if s.get("consecutive_days", 0) == max_board
        ]

    except Exception as e:
        logger.warning("_get_high_board_stocks failed for %s: %s", trade_date, e)
        return []


def _get_high_board_detail(
    stock: dict,
    trade_date: str,
    theme_map: dict[str, list[dict]],
) -> dict:
    """获取高标股详细信息。

    返回:
        {
            "code": "000001",
            "name": "股票A",
            "board_num": 5,
            "theme": "人工智能",
            "seal_amount": 100000000,
            "circulation_mv": 5000000000,
            "seal_ratio": 0.02,
            "turnover_rate": 0.05,
            "amount": 500000000,
            "open_count": 0,
            "is_yizi": False,
            "seal_status": "封板",
        }

    数据源: 腾讯财经(行情) + K线(涨停/一字判断)
    """
    code = stock["code"]
    board_num = stock.get("consecutive_days", 0)

    # 获取实时行情
    quote = _get_stock_realtime_quote(code)

    # 获取封单信息（复用已有函数）
    seal_info = _get_stock_seal_info(stock)

    # 判断是否一字板
    kline_info = _detect_limitup_from_kline(code, trade_date)
    is_yizi = kline_info.get("is_yizi", False)

    # 封板状态判断
    change_pct = quote.get("change_pct", 0)
    if change_pct < 9.9:
        seal_status = "断板"
    elif seal_info.get("seal_strength_score", 0) < 30:
        seal_status = "分歧"
    else:
        seal_status = "封板"

    # 封单/流通盘比
    circulation_mv = stock.get("circulation_mv", 0)
    amount = stock.get("amount", 0)
    seal_ratio = 0.0
    if circulation_mv > 0:
        seal_ratio = round(amount / circulation_mv * 100, 2)

    # 开板次数估算（基于换手率和封板类型）
    open_count = 0
    if not is_yizi and seal_status != "封板":
        turnover = stock.get("turnover_rate", 0)
        if turnover > 0.15:
            open_count = 3
        elif turnover > 0.10:
            open_count = 2
        elif turnover > 0.05:
            open_count = 1

    # 找出最高热度题材
    raw_reason = stock.get("reason", "")
    reasons = [r.strip() for r in raw_reason.replace("，", "+").split("+") if r.strip()]
    best_theme = ""
    max_heat = 0
    for reason in reasons:
        normalized = _normalize_theme_name(reason)
        theme_stocks = theme_map.get(normalized, [])
        heat = min(100, len(theme_stocks) * 8 + board_num * 15)
        if heat > max_heat:
            max_heat = heat
            best_theme = normalized

    return {
        "code": code,
        "name": stock.get("name", ""),
        "board_num": board_num,
        "theme": best_theme,
        "circulation_mv": circulation_mv,
        "seal_ratio": seal_ratio,
        "turnover_rate": stock.get("turnover_rate", 0),
        "amount": amount,
        "open_count": open_count,
        "is_yizi": is_yizi,
        "seal_status": seal_status,
        "seal_strength_score": seal_info.get("seal_strength_score", 50),
        "change_pct": change_pct,
        "price": quote.get("price", 0),
    }


def _get_yizi_cumulative_turnover(code: str, yizi_days: int) -> float:
    """计算一字板期间累计换手率。

    逻辑:
    1. 获取近N+1天（一字板天数+当日）的K线数据
    2. 累加每天的换手率

    返回:
        float: 累计换手率（%）

    用途:
        - 缩量一字（累计<5%）→ 开板风险中等
        - 放量一字（累计>10%）→ 开板风险高
    """
    if yizi_days <= 0:
        return 0.0

    try:
        code = _normalize_ticker(code)
        df = _load_ohlcv_astock(code, "")
        if df is None or df.empty or len(df) < 2:
            return 0.0

        # 取最近 yizi_days+1 天的数据
        recent = df.tail(yizi_days + 1)
        if len(recent) < 2:
            return 0.0

        # 计算每天的换手率（Volume / 估算流通股）
        # 简化处理：使用 Volume 变化率作为换手率代理
        total_turnover = 0.0
        for i in range(1, len(recent)):
            prev_vol = float(recent.iloc[i - 1]["Volume"]) if recent.iloc[i - 1]["Volume"] > 0 else 1
            curr_vol = float(recent.iloc[i]["Volume"])
            # 换手率代理 = 当日成交量 / 前日成交量 * 基准换手率
            vol_ratio = curr_vol / prev_vol if prev_vol > 0 else 0
            # 一字板通常缩量，用成交量占比估算换手率
            total_turnover += min(vol_ratio * 2, 5.0)  # 单日上限5%

        return round(total_turnover, 2)

    except Exception as e:
        logger.warning("_get_yizi_cumulative_turnover failed for %s: %s", code, e)
        return 0.0


def _calculate_divergence_score(
    seal_stable: bool,
    open_count: int,
    seal_ratio: float,
) -> dict:
    """分歧程度评估（简化版，2核心因子）。

    核心因子:
    1. 封单稳定性（权重50%）
    2. 开板次数（权重50%）

    返回:
        {
            "divergence_score": float,  # 0-100
            "level": str,               # 一致/轻度分歧/中度分歧/重度分歧
            "can_do_high_board": bool,  # 是否可以做高位接力
        }
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


def _calculate_break_risk_level(
    board_num: int,
    seal_status: str,
    open_count: int,
    divergence_score: float,
    same_theme_performance: float,
    market_emotion: str,
    consecutive_yizi_days: int,
    yizi_cumulative_turnover: float,
    card_position_exists: bool,
) -> dict:
    """断板风险评估（细化版，含一字板累计换手率）。

    高风险信号（命中任意一个→高风险）:
    1. 连续一字板>=3天，今日开板（放量一字风险更高）
    2. 封板状态异常
    3. 分歧度>70

    中风险信号:
    1. 分歧度50-70
    2. 同题材走弱
    3. 市场情绪转差
    4. 有卡位威胁

    返回:
        {
            "risk_level": str,           # 高/中/中低/低
            "risk_signals": list[str],   # 风险信号列表
            "consecutive_yizi_days": int,
            "yizi_cumulative_turnover": float,
        }
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
    has_high_risk = any(
        kw in signal for kw in high_risk_keywords for signal in risk_signals
    )

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


def _get_theme_effect_for_high_board(
    code: str,
    theme_map: dict[str, list[dict]],
) -> dict:
    """获取高标股所属板块的效应。

    逻辑:
    1. 通过 get_concept_blocks(code) 获取概念板块
    2. 匹配涨停题材数据
    3. 判断板块是否强势

    返回:
        {
            "themes": ["AI", "算力"],       # 所属概念板块
            "theme_performance": 2.5,       # 板块平均涨跌幅
            "is_theme_strong": True,        # 板块是否强势
            "other_stocks_in_theme": 8,     # 板块内其他涨停股数
        }

    数据源: 东财 slist (concept blocks) + 涨停题材数据
    """
    try:
        # 获取概念板块文本
        blocks_text = get_concept_blocks(code)

        # 解析概念板块名称
        themes: list[str] = []
        if isinstance(blocks_text, str) and "Concept tags:" in blocks_text:
            tags_line = blocks_text.split("Concept tags:")[-1].strip()
            themes = [t.strip() for t in tags_line.split("/") if t.strip()]

        # 匹配涨停题材数据
        other_stocks_count = 0
        matched_themes_perf: list[float] = []
        for theme_name in themes:
            normalized = _normalize_theme_name(theme_name)
            theme_stocks = theme_map.get(normalized, [])
            other_stocks_count += len(theme_stocks)
            # 用涨停家数估算板块强度
            if theme_stocks:
                avg_board = sum(s.get("board_num", 1) for s in theme_stocks) / len(theme_stocks)
                matched_themes_perf.append(avg_board * 2)

        theme_performance = (
            round(sum(matched_themes_perf) / len(matched_themes_perf), 2)
            if matched_themes_perf else 0
        )
        is_theme_strong = theme_performance > 2.0 or other_stocks_count >= 5

        return {
            "themes": themes[:5],  # 最多返回5个
            "theme_performance": theme_performance,
            "is_theme_strong": is_theme_strong,
            "other_stocks_in_theme": other_stocks_count,
        }

    except Exception as e:
        logger.warning("_get_theme_effect_for_high_board failed for %s: %s", code, e)
        return {
            "themes": [],
            "theme_performance": 0,
            "is_theme_strong": False,
            "other_stocks_in_theme": 0,
        }


def get_high_board_status(
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
) -> str:
    """高标股状态监控。

    返回内容:
    1. 市场最高板股票信息
    2. 封单状态（封死/分歧/断板）
    3. 分歧程度评估（简化版：封单稳定性+开板次数）
    4. 断板风险等级（高/中/低）
    5. 板块效应
    6. 明日操作建议

    数据源: 同花顺 + mootdx + 东财 + 腾讯财经
    限流: _em_get()（仅东财部分）
    """
    if not trade_date or trade_date.strip() == "":
        trade_date = datetime.now().strftime("%Y-%m-%d")

    try:
        # 1. 获取最高板股票
        high_board_stocks = _get_high_board_stocks(trade_date)
        if not high_board_stocks:
            return f"无涨停数据（非交易日或盘后未更新）| {trade_date}"

        max_board = high_board_stocks[0].get("consecutive_days", 0)

        # 2. 获取市场情绪（复用情绪量化）
        all_limitup = _get_limitup_stocks(trade_date)
        limitdown = _get_limitdown_stocks(trade_date)
        breadth = _get_market_breadth(trade_date)
        northbound = _get_northbound_flow_signal(trade_date)
        emotion_metrics = _calculate_emotion_metrics(
            all_limitup, limitdown, {}, breadth, northbound
        )
        market_emotion = emotion_metrics.get("emotion_phase", "修复")

        # 3. 获取题材数据
        theme_map = _get_limitup_by_theme(trade_date)

        # 4. 获取卡位股（同板数的其他股票）
        card_position_codes = set()
        for s in all_limitup:
            if (s.get("consecutive_days", 0) == max_board
                    and s["code"] not in {hs["code"] for hs in high_board_stocks}):
                card_position_codes.add(s["code"])

        # 5. 逐票构建详情
        reports: list[dict] = []
        for stock in high_board_stocks:
            code = stock["code"]

            # 高标股详情
            detail = _get_high_board_detail(stock, trade_date, theme_map)

            # 一字板累计换手率
            yizi_turnover = _get_yizi_cumulative_turnover(
                code, detail["board_num"]
            ) if detail["is_yizi"] else 0.0

            # 分歧度评估
            seal_stable = detail["seal_status"] == "封板"
            divergence = _calculate_divergence_score(
                seal_stable=seal_stable,
                open_count=detail["open_count"],
                seal_ratio=detail["seal_ratio"],
            )

            # 同题材表现
            theme_name = detail.get("theme", "")
            theme_stocks = theme_map.get(theme_name, [])
            theme_perf = 0.0
            if theme_stocks:
                avg_board = sum(s.get("board_num", 1) for s in theme_stocks) / len(theme_stocks)
                theme_perf = round(avg_board * 2 - 3, 2)  # 简化估算

            # 断板风险评估
            break_risk = _calculate_break_risk_level(
                board_num=detail["board_num"],
                seal_status=detail["seal_status"],
                open_count=detail["open_count"],
                divergence_score=divergence["divergence_score"],
                same_theme_performance=theme_perf,
                market_emotion=market_emotion,
                consecutive_yizi_days=detail["board_num"] if detail["is_yizi"] else 0,
                yizi_cumulative_turnover=yizi_turnover,
                card_position_exists=len(card_position_codes) > 0,
            )

            # 板块效应
            theme_effect = _get_theme_effect_for_high_board(code, theme_map)

            reports.append({
                "detail": detail,
                "divergence": divergence,
                "break_risk": break_risk,
                "theme_effect": theme_effect,
            })

        # 6. 格式化输出
        return _format_high_board_status(
            reports, trade_date, max_board, market_emotion,
            emotion_metrics, card_position_codes,
        )

    except Exception as e:
        return f"高标股状态获取失败 ({trade_date}): {str(e)}"


def _format_high_board_status(
    reports: list[dict],
    trade_date: str,
    max_board: int,
    market_emotion: str,
    emotion_metrics: dict,
    card_position_codes: set[str],
) -> str:
    """格式化高标股状态输出。"""
    lines = [
        f"# 高标股状态监控 | {trade_date}",
        f"# Source: 同花顺 + mootdx + 东财 + 腾讯财经",
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # 总览
    lines.append("## 总览")
    lines.append(f"  最高连板: {max_board}板")
    lines.append(f"  最高板股票数: {len(reports)}只")
    lines.append(f"  市场情绪: {market_emotion}")
    lines.append(f"  情绪评分: {emotion_metrics.get('emotion_score', 0)}")
    lines.append(f"  卡位竞争者: {len(card_position_codes)}只")
    lines.append("")

    # 逐票详情
    for i, report in enumerate(reports):
        d = report["detail"]
        div = report["divergence"]
        risk = report["break_risk"]
        te = report["theme_effect"]

        lines.append(f"## #{i+1} {d['code']} {d['name']} ({d['board_num']}板)")
        lines.append(f"  封板状态: {d['seal_status']}")
        lines.append(f"  当前价格: {d['price']}")
        lines.append(f"  涨跌幅: {d['change_pct']}%")
        lines.append(f"  流通市值: {d['circulation_mv'] / 1e8:.1f}亿" if d['circulation_mv'] else "  流通市值: N/A")
        lines.append(f"  换手率: {d['turnover_rate'] * 100:.2f}%" if d['turnover_rate'] else "  换手率: N/A")
        lines.append(f"  成交额: {d['amount'] / 1e8:.2f}亿" if d['amount'] else "  成交额: N/A")
        lines.append(f"  封单/流通盘比: {d['seal_ratio']:.2f}%")
        lines.append(f"  一字板: {'是' if d['is_yizi'] else '否'}")
        lines.append(f"  开板次数: {d['open_count']}次")

        # 分歧度
        lines.append(f"  --- 分歧度 ---")
        lines.append(f"  评分: {div['divergence_score']} ({div['level']})")
        lines.append(f"  可做高位接力: {'是' if div['can_do_high_board'] else '否'}")

        # 断板风险
        lines.append(f"  --- 断板风险 ---")
        lines.append(f"  风险等级: {risk['risk_level']}")
        if risk["risk_signals"]:
            for signal in risk["risk_signals"]:
                lines.append(f"    ⚠ {signal}")
        if risk["consecutive_yizi_days"] > 0:
            lines.append(
                f"  一字板天数: {risk['consecutive_yizi_days']}天, "
                f"累计换手率: {risk['yizi_cumulative_turnover']:.1f}%"
            )

        # 板块效应
        lines.append(f"  --- 板块效应 ---")
        if te["themes"]:
            lines.append(f"  所属题材: {' / '.join(te['themes'])}")
        lines.append(f"  板块涨停股数: {te['other_stocks_in_theme']}只")
        lines.append(f"  板块强度: {'强势' if te['is_theme_strong'] else '一般'}")
        lines.append("")

    # 操作建议
    lines.append("## 操作建议")
    if not reports:
        lines.append("  无高标股数据")
    else:
        for i, report in enumerate(reports):
            d = report["detail"]
            div = report["divergence"]
            risk = report["break_risk"]

            if risk["risk_level"] == "高":
                advice = "回避高位接力，等待新龙头"
            elif risk["risk_level"] == "中":
                advice = "谨慎参与，控制仓位"
            elif div["can_do_high_board"]:
                advice = "可以高位接力"
            else:
                advice = "观望为主"

            lines.append(f"  {d['code']} {d['name']}: {advice}")

    # 卡位竞争
    if card_position_codes:
        lines.append("")
        lines.append("## 卡位竞争")
        lines.append(f"  卡位股数量: {len(card_position_codes)}只")
        lines.append(f"  卡位股代码: {', '.join(sorted(card_position_codes))}")

    return "\n".join(lines)


# ===========================================================================
# Phase 6: 龙头识别 + 卡位分析
# ===========================================================================


def _get_same_theme_stocks(
    code: str,
    trade_date: str,
) -> list[dict]:
    """获取与目标股票同题材的涨停股票列表。

    逻辑:
    1. 通过 get_concept_blocks(code) 获取目标股票的概念板块
    2. 获取当日全部涨停股，按题材归一化聚合
    3. 匹配目标股票的概念板块，返回同题材涨停股

    返回:
        [{"code": "000002", "name": "股票B", "board_num": 3,
          "seal_strength": 0.05, "circulation_mv": 3e9, ...}, ...]

    数据源: 东财 slist (concept blocks) + _get_limitup_by_theme
    """
    try:
        # 1. 获取目标股票的概念板块
        blocks_text = get_concept_blocks(code)
        themes: list[str] = []
        if isinstance(blocks_text, str) and "Concept tags:" in blocks_text:
            tags_line = blocks_text.split("Concept tags:")[-1].strip()
            themes = [t.strip() for t in tags_line.split("/") if t.strip()]

        if not themes:
            return []

        # 2. 获取当日涨停题材聚合
        theme_map = _get_limitup_by_theme(trade_date)

        # 3. 匹配同题材涨停股（去重）
        seen_codes: set[str] = set()
        result: list[dict] = []
        for theme_name in themes:
            normalized = _normalize_theme_name(theme_name)
            theme_stocks = theme_map.get(normalized, [])
            for stock in theme_stocks:
                if stock["code"] not in seen_codes and stock["code"] != code:
                    seen_codes.add(stock["code"])
                    result.append(stock)

        # 按连板天数降序、涨停时间升序排列
        result.sort(key=lambda s: (-s.get("board_num", 1), s.get("first_limit_time", "99:99")))
        return result

    except Exception as e:
        logger.warning("_get_same_theme_stocks failed for %s: %s", code, e)
        return []


def _get_leader_candidates(
    trade_date: str,
) -> list[dict]:
    """获取龙头候选列表（按题材分组，各题材取最高板）。

    逻辑:
    1. 获取所有涨停股
    2. 按题材归一化聚合
    3. 每个题材取连板数最高的股票作为龙头候选

    返回:
        [{"theme": "AI概念", "leader": {"code": "000001", ...},
          "theme_stock_count": 10, "stocks": [...]}, ...]

    数据源: _get_limitup_by_theme
    """
    try:
        theme_map = _get_limitup_by_theme(trade_date)
        if not theme_map:
            return []

        candidates: list[dict] = []
        for theme_name, stocks in theme_map.items():
            if not stocks:
                continue
            # 按连板天数降序排列
            sorted_stocks = sorted(stocks, key=lambda s: -s.get("board_num", 1))
            leader = sorted_stocks[0]
            candidates.append({
                "theme": theme_name,
                "leader": leader,
                "theme_stock_count": len(stocks),
                "stocks": sorted_stocks,
            })

        # 按题材涨停家数降序排列（题材越大越重要）
        candidates.sort(key=lambda c: -c["theme_stock_count"])
        return candidates

    except Exception as e:
        logger.warning("_get_leader_candidates failed for %s: %s", trade_date, e)
        return []


def _calculate_leader_score(
    board_num: int,
    first_limit_time: str,
    seal_strength: float,
    theme_purity: float,
    theme_stocks_count: int,
    rank_in_theme: int,
    circulation_mv: float,
    is_market_highest: bool,
    is_earliest_in_board: bool,
    is_yizi: bool,
    historical_broken_count: int,
) -> dict:
    """龙头评分（超龙头视角，5因子+特殊加成/扣分）。

    核心因子及权重:
    1. 连板高度: 35% — 最高板=龙头（绝对高度）
    2. 首板时间: 15% — 同板数内比较
    3. 封单强度: 25% — 封单/流通盘比
    4. 题材纯正度: 15% — 主营业务与题材关联度
    5. 市场认可度: 10% — 同题材涨停家数+排名

    特殊加成:
    - 市场最高板: +10分
    - 首板时间最早（同板数内）: +5分
    - 连续一字板: +5分

    特殊扣分:
    - 流通市值>200亿: -5分
    - 历史经常炸板: -5分

    返回:
        {"total_score": float, "breakdown": {...}, "bonuses": [...], "penalties": [...]}
    """
    breakdown = {}

    # Factor 1: 连板高度 (35%) — 标准化到0-100
    # 假设最高常见高度为8板
    height_score = min(board_num / 8, 1.0) * 100
    breakdown["board_height"] = round(height_score, 1)

    # Factor 2: 首板时间 (15%)
    time_score = _calculate_time_score(first_limit_time)
    breakdown["first_limit_time"] = round(time_score, 1)

    # Factor 3: 封单强度 (25%) — 封单/流通盘比
    # seal_strength 已经是百分比（如 5.0 表示5%）
    seal_score = min(seal_strength / 10, 1.0) * 100
    breakdown["seal_strength"] = round(seal_score, 1)

    # Factor 4: 题材纯正度 (15%)
    purity_score = min(theme_purity / 100, 1.0) * 100
    breakdown["theme_purity"] = round(purity_score, 1)

    # Factor 5: 市场认可度 (10%)
    # 涨停家数 + 排名
    count_component = min(theme_stocks_count / 15, 1.0) * 60  # 最多60分
    rank_component = max(0, (1 - (rank_in_theme - 1) / max(theme_stocks_count, 1))) * 40  # 最多40分
    recognition_score = count_component + rank_component
    breakdown["market_recognition"] = round(recognition_score, 1)

    # 加权总分
    total = (
        height_score * 0.35
        + time_score * 0.15
        + seal_score * 0.25
        + purity_score * 0.15
        + recognition_score * 0.10
    )

    bonuses: list[str] = []
    penalties: list[str] = []

    # 特殊加成
    if is_market_highest:
        total += 10
        bonuses.append("市场最高板 +10")

    if is_earliest_in_board:
        total += 5
        bonuses.append("同板数内首板最早 +5")

    if is_yizi:
        total += 5
        bonuses.append("连续一字板 +5")

    # 特殊扣分
    if circulation_mv > 2e10:  # >200亿
        total -= 5
        penalties.append("流通市值>200亿 -5")

    if historical_broken_count >= 3:
        total -= 5
        penalties.append("历史经常炸板 -5")

    total = max(0, min(100, total))

    return {
        "total_score": round(total, 1),
        "breakdown": breakdown,
        "bonuses": bonuses,
        "penalties": penalties,
    }


def _calculate_time_score(limit_time: str) -> float:
    """计算涨停时间评分。

    评分标准:
    - 9:30-9:35 涨停: 100分（秒板）
    - 9:35-9:45 涨停: 90分
    - 9:45-10:00 涨停: 80分
    - 10:00-10:30 涨停: 70分
    - 10:30-13:00 涨停: 60分
    - 13:00后涨停: 50分

    返回: float (0-100)
    """
    if not limit_time:
        return 50.0

    t = limit_time.strip()
    if t <= "09:35":
        return 100.0
    if t <= "09:45":
        return 90.0
    if t <= "10:00":
        return 80.0
    if t <= "10:30":
        return 70.0
    if t <= "13:00":
        return 60.0
    return 50.0


def _identify_card_position(
    leader_code: str,
    leader_board_num: int,
    leader_seal_strength: float,
    leader_seal_status: str,
    same_theme_stocks: list[dict],
    market_emotion: str,
) -> list[dict]:
    """识别卡位关系（修正版，阈值随龙头封板状态动态调整）。

    卡位定义:
    同题材、同板数或低一板的股票，封单强度超过龙头，或分时走势强于龙头。

    卡位类型:
    - 强卡位（高威胁）
    - 中卡位
    - 弱卡位（低威胁/跟风）

    卡位强度评估:
    - 龙头封板状态好时: >1.5 强卡位, 1-1.5 中卡位, <1 弱卡位
    - 龙头分歧时: >1.2 强卡位, 0.8-1.2 中卡位, <0.8 弱卡位

    返回:
        [{"code": "000002", "name": "股票B", "board_num": 3,
          "seal_ratio_to_leader": 1.6, "card_type": "强卡位"}, ...]
    """
    results: list[dict] = []

    for stock in same_theme_stocks:
        if stock["code"] == leader_code:
            continue

        stock_board = stock.get("board_num", 1)
        # 只看同板数或低一板的
        if stock_board < leader_board_num - 1:
            continue

        stock_seal = stock.get("seal_strength", 0)
        seal_ratio = stock_seal / leader_seal_strength if leader_seal_strength > 0 else 0

        # 根据龙头封板状态调整阈值
        if leader_seal_status == "封板":
            if seal_ratio > 1.5:
                card_type = "强卡位"
            elif seal_ratio > 1.0:
                card_type = "中卡位"
            else:
                card_type = "弱卡位"
        else:
            # 龙头分歧/断板，阈值降低
            if seal_ratio > 1.2:
                card_type = "强卡位"
            elif seal_ratio > 0.8:
                card_type = "中卡位"
            else:
                card_type = "弱卡位"

        results.append({
            "code": stock["code"],
            "name": stock.get("name", ""),
            "board_num": stock_board,
            "seal_strength": stock_seal,
            "seal_ratio_to_leader": round(seal_ratio, 2),
            "card_type": card_type,
        })

    results.sort(key=lambda r: -r["seal_ratio_to_leader"])
    return results


def _identify_deputy_leader(
    leader_code: str,
    leader_board_num: int,
    leader_seal_status: str,
    leader_circulation_mv: float,
    same_theme_stocks: list[dict],
    market_emotion: str,
) -> list[dict]:
    """识别补涨龙（修正版，条件放宽）。

    补涨龙条件:
    1. 龙头连板数 >=4（从5下调）
    2. 龙头处于分歧状态（新增条件）
    3. 同题材
    4. 连板数 1-2板（低位）
    5. 封单强度高（>3%）
    6. 流通市值 < 龙头（小盘更容易封）

    补涨龙空间评估:
    - 补涨龙理论高度 = 龙头高度 - 2

    返回:
        [{"code": "000002", "name": "股票B", "board_num": 1,
          "seal_strength": 0.04, "theoretical_height": 3}, ...]
    """
    results: list[dict] = []

    # 条件1：龙头连板数>=4
    if leader_board_num < 4:
        return results

    # 条件2：龙头处于分歧状态
    if leader_seal_status == "封板":
        return results

    for stock in same_theme_stocks:
        if stock["code"] == leader_code:
            continue

        stock_board = stock.get("board_num", 1)
        stock_seal = stock.get("seal_strength", 0)
        stock_mv = stock.get("circulation_mv", 0)

        # 条件3-6
        if (stock_board <= 2
                and stock_seal > 3
                and stock_mv < leader_circulation_mv):
            results.append({
                "code": stock["code"],
                "name": stock.get("name", ""),
                "board_num": stock_board,
                "seal_strength": stock_seal,
                "circulation_mv": stock_mv,
                "theoretical_height": leader_board_num - 2,
                "is_possible_new_leader": False,
            })

    results.sort(key=lambda r: -r["seal_strength"])
    return results


def _distinguish_deputy_vs_new_leader(
    leader_code: str,
    leader_board_num: int,
    leader_seal_status: str,
    candidate_code: str,
    candidate_board_num: int,
    candidate_theme: str,
    leader_theme: str,
) -> dict:
    """区分补涨龙 vs 新龙头。

    补涨龙特征（同时满足）:
    - 龙头还在（未断板，可能分歧）
    - 低位票在龙头分歧时启动
    - 低位票连板数 <= 龙头 - 2
    - 低位票与龙头同题材

    新龙头特征（同时满足）:
    - 龙头已断板
    - 新票在龙头断板后启动
    - 新票连板数 >= 龙头 - 1
    - 新票可能是不同题材（新方向）

    返回:
        {"type": "deputy_leader" | "new_leader" | "uncertain",
         "confidence": float, "reason": str}
    """
    # 新龙头特征
    if leader_seal_status == "断板":
        if candidate_board_num >= leader_board_num - 1:
            return {
                "type": "new_leader",
                "confidence": 0.8,
                "reason": (
                    f"龙头断板后，{candidate_code}连板数{candidate_board_num}板，"
                    f"可能是新龙头"
                ),
            }

    # 补涨龙特征
    if leader_seal_status in ("分歧", "封板"):
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
    """强看好龙头判断（超龙头硬核逻辑）。

    核心逻辑: 必须是"市场公认龙头"

    条件1: 高度最高（连板数>=4）
    条件2: 封单最强（封单/流通盘>5%）
    条件3: 时间最早（10:00前涨停）
    条件4: 题材支撑（涨停家数>=10，活跃天数>=3）

    返回: {"strong_bullish": bool, "reason": str, "action": str, "target": str}
    """
    if board_num < 4:
        return {"strong_bullish": False, "reason": "高度不够（需>=4板）"}

    if seal_strength < 5:
        return {"strong_bullish": False, "reason": "封单不够强（需>5%）"}

    if first_limit_time >= "10:00":
        return {"strong_bullish": False, "reason": "涨停时间太晚（需10:00前）"}

    if theme_stock_count < 10:
        return {"strong_bullish": False, "reason": "题材不够强（涨停家数需>=10）"}

    if theme_active_days < 3:
        return {"strong_bullish": False, "reason": "题材持续性不足（活跃天数需>=3）"}

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
    """强看空龙头判断（超龙头硬核逻辑）。

    看空信号:
    1. 龙头断板（最强看空信号）
    2. 龙头分歧 + 卡位出现
    3. 题材崩塌（涨停家数<5）
    4. 封单崩溃（封单<1%）

    返回: {"strong_bearish": bool, "reason": str, "action": str}
    """
    reasons: list[str] = []

    if seal_status == "断板":
        reasons.append("龙头断板（最强看空信号）")

    if (seal_status == "分歧"
            and card_position_code
            and card_position_seal_status == "封板"):
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
    """卡位结果判断（超龙头硬核逻辑）。

    强看好卡位（卡位成功）:
      - 龙头断板
      - 卡位股封板
      - 卡位股连板数 >= 龙头 - 1
      - 卡位股封单 > 龙头

    强看空卡位（卡位失败）:
      - 龙头回封
      - 卡位股炸板
      - 卡位股连板数 < 龙头 - 2

    返回: {"card_success": bool, "reason": str, "action": str}
    """
    # 卡位成功条件
    if leader_seal_status == "断板" and card_seal_status == "封板":
        if (card_board_num >= leader_board_num - 1
                and card_seal_strength > leader_seal_strength):
            return {
                "card_success": True,
                "reason": "龙头断板 + 卡位股封板 + 连板数够",
                "action": "跟随新龙头",
                "new_leader": card_board_num,
            }

    # 卡位失败条件：龙头回封 + 卡位股断板
    if leader_seal_status == "封板" and card_seal_status == "断板":
        return {
            "card_success": False,
            "reason": "龙头回封 + 卡位股断板",
            "action": "继续跟随原龙头",
        }

    # 双龙断板
    if leader_seal_status == "断板" and card_seal_status == "断板":
        return {
            "card_success": False,
            "reason": "双龙断板，情绪崩塌",
            "action": "空仓观望",
        }

    return {"card_success": False, "reason": "卡位进行中，等待结果", "action": "观望"}


def get_leader_identification(
    ticker: Annotated[str, "A-stock code (e.g. 000001)"] = "",
    trade_date: Annotated[str, "YYYY-MM-DD, 默认今日"] = "",
    theme: Annotated[str, "Theme name to analyze (empty for all themes)"] = "",
) -> str:
    """龙头识别 + 卡位分析。

    两种调用方式:
    1. get_leader_identification(ticker, trade_date) — 分析指定个股的龙头地位
    2. get_leader_identification(trade_date=xxx, theme=xxx) — 分析指定题材的龙头格局

    返回内容:
    1. 该股是否为龙头判断
    2. 同题材竞争者列表
    3. 卡位风险评估（含龙头封板状态对阈值的影响）
    4. 补涨龙候选列表（含补涨龙vs新龙头区分）
    5. 强看好/强看空判断

    数据源: 东财 slist + 同花顺 + mootdx + 腾讯财经
    限流: _em_get()（仅东财部分）
    """
    if not trade_date or trade_date.strip() == "":
        trade_date = datetime.now().strftime("%Y-%m-%d")

    # 如果只传了 theme 没传 ticker，从题材中取最高板股票作为分析对象
    if not ticker and theme:
        theme_map = _get_limitup_by_theme(trade_date)
        normalized = _normalize_theme_name(theme)
        theme_stocks = theme_map.get(normalized, [])
        if not theme_stocks:
            return f"题材 '{theme}' 在 {trade_date} 无涨停数据"
        # 取连板天数最高的股票
        best = max(theme_stocks, key=lambda s: s.get("consecutive_days", 0))
        ticker = best["code"]
    elif not ticker:
        return "请指定 ticker 或 theme 参数"

    code = safe_ticker_component(ticker)

    try:
        # 1. 获取目标股票信息
        quote = _get_stock_realtime_quote(code)
        if not quote or quote.get("price", 0) == 0:
            return f"无法获取股票 {code} 行情数据（非交易日或代码错误）| {trade_date}"

        # 2. 获取目标股票的概念板块
        blocks_text = get_concept_blocks(code)
        target_themes: list[str] = []
        if isinstance(blocks_text, str) and "Concept tags:" in blocks_text:
            tags_line = blocks_text.split("Concept tags:")[-1].strip()
            target_themes = [t.strip() for t in tags_line.split("/") if t.strip()]

        # 3. 获取同题材涨停股
        same_theme_stocks = _get_same_theme_stocks(code, trade_date)

        # 4. 获取当日涨停数据
        all_limitup = _get_limitup_stocks(trade_date)
        theme_map = _get_limitup_by_theme(trade_date)

        # 5. 目标股票的连板天数
        target_kline = _detect_limitup_from_kline(code, trade_date)
        target_board_num = target_kline.get("consecutive_days", 0)

        # 6. 封单信息
        target_stock_dict = {"code": code, "consecutive_days": target_board_num}
        seal_info = _get_stock_seal_info(target_stock_dict)
        target_seal_strength = seal_info.get("seal_ratio", 0)

        # 7. 判断目标股票的封板状态
        change_pct = quote.get("change_pct", 0)
        if change_pct >= 9.9:
            target_seal_status = "封板"
        elif change_pct >= 5:
            target_seal_status = "分歧"
        else:
            target_seal_status = "断板"

        # 8. 目标股票题材纯正度
        target_theme_name = target_themes[0] if target_themes else ""
        target_theme_stocks = theme_map.get(
            _normalize_theme_name(target_theme_name), []
        ) if target_theme_name else []
        theme_purity = _calculate_theme_purity(
            code, target_theme_name, target_theme_stocks, theme_map
        )

        # 9. 龙头评分
        # 判断是否市场最高板
        max_board = max((s.get("consecutive_days", 0) for s in all_limitup), default=0)
        is_market_highest = target_board_num >= max_board and target_board_num > 0

        # 判断同板数内是否首板最早
        same_board_stocks = [
            s for s in all_limitup
            if s.get("consecutive_days", 0) == target_board_num
        ]
        earliest_time = min(
            (s.get("first_limit_time", "99:99") for s in same_board_stocks),
            default="99:99",
        )
        is_earliest = (
            target_kline.get("first_limit_time", "99:99") <= earliest_time
            if same_board_stocks else False
        )

        # 题材内排名
        rank_in_theme = 1
        for i, s in enumerate(target_theme_stocks):
            if s["code"] == code:
                rank_in_theme = i + 1
                break

        leader_score = _calculate_leader_score(
            board_num=target_board_num,
            first_limit_time=target_kline.get("first_limit_time", ""),
            seal_strength=target_seal_strength,
            theme_purity=theme_purity,
            theme_stocks_count=len(target_theme_stocks),
            rank_in_theme=rank_in_theme,
            circulation_mv=quote.get("circulation_mv", 0),
            is_market_highest=is_market_highest,
            is_earliest_in_board=is_earliest,
            is_yizi=target_kline.get("is_yizi", False),
            historical_broken_count=0,  # 简化：暂无历史炸板数据
        )

        # 10. 卡位分析
        card_positions = _identify_card_position(
            leader_code=code,
            leader_board_num=target_board_num,
            leader_seal_strength=target_seal_strength,
            leader_seal_status=target_seal_status,
            same_theme_stocks=same_theme_stocks,
            market_emotion="修复",  # 简化
        )

        # 11. 补涨龙识别
        deputy_leaders = _identify_deputy_leader(
            leader_code=code,
            leader_board_num=target_board_num,
            leader_seal_status=target_seal_status,
            leader_circulation_mv=quote.get("circulation_mv", 0),
            same_theme_stocks=same_theme_stocks,
            market_emotion="修复",
        )

        # 12. 补涨龙vs新龙头区分
        for deputy in deputy_leaders:
            distinction = _distinguish_deputy_vs_new_leader(
                leader_code=code,
                leader_board_num=target_board_num,
                leader_seal_status=target_seal_status,
                candidate_code=deputy["code"],
                candidate_board_num=deputy["board_num"],
                candidate_theme=target_theme_name,
                leader_theme=target_theme_name,
            )
            deputy["distinction_type"] = distinction["type"]
            deputy["distinction_confidence"] = distinction["confidence"]
            deputy["distinction_reason"] = distinction["reason"]

        # 13. 强看好/强看空判断
        theme_active_days = _get_theme_active_days(
            _get_theme_history(target_theme_name)
        ) if target_theme_name else 0

        strong_bullish = judge_strong_bullish_leader(
            board_num=target_board_num,
            first_limit_time=target_kline.get("first_limit_time", ""),
            seal_strength=target_seal_strength,
            theme_stock_count=len(target_theme_stocks),
            theme_active_days=theme_active_days,
            is_market_highest=is_market_highest,
        )

        # 强看空判断
        first_card = card_positions[0] if card_positions else None
        strong_bearish = judge_strong_bearish_leader(
            board_num=target_board_num,
            seal_status=target_seal_status,
            seal_strength=target_seal_strength,
            theme_stock_count=len(target_theme_stocks),
            card_position_code=first_card["code"] if first_card else "",
            card_position_seal_status="封板" if first_card and first_card.get("seal_ratio_to_leader", 0) > 1 else "断板",
        )

        # 14. 格式化输出
        return _format_leader_identification(
            code=code,
            quote=quote,
            target_themes=target_themes,
            target_board_num=target_board_num,
            target_seal_status=target_seal_status,
            target_seal_strength=target_seal_strength,
            leader_score=leader_score,
            same_theme_stocks=same_theme_stocks,
            card_positions=card_positions,
            deputy_leaders=deputy_leaders,
            strong_bullish=strong_bullish,
            strong_bearish=strong_bearish,
            trade_date=trade_date,
            theme_purity=theme_purity,
            is_market_highest=is_market_highest,
        )

    except Exception as e:
        return f"龙头识别失败 ({code}, {trade_date}): {str(e)}"


def _format_leader_identification(
    code: str,
    quote: dict,
    target_themes: list[str],
    target_board_num: int,
    target_seal_status: str,
    target_seal_strength: float,
    leader_score: dict,
    same_theme_stocks: list[dict],
    card_positions: list[dict],
    deputy_leaders: list[dict],
    strong_bullish: dict,
    strong_bearish: dict,
    trade_date: str,
    theme_purity: float,
    is_market_highest: bool,
) -> str:
    """格式化龙头识别输出。"""
    lines = [
        f"# 龙头识别 + 卡位分析 | {code} | {trade_date}",
        f"# Source: 东财 slist + 同花顺 + mootdx + 腾讯财经",
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # 1. 目标股票概览
    lines.append("## 目标股票概览")
    lines.append(f"  代码: {code}")
    lines.append(f"  名称: {quote.get('name', 'N/A')}")
    lines.append(f"  连板数: {target_board_num}板")
    lines.append(f"  封板状态: {target_seal_status}")
    lines.append(f"  封单/流通盘比: {target_seal_strength:.2f}%")
    lines.append(f"  流通市值: {quote.get('circulation_mv', 0) / 1e8:.1f}亿" if quote.get('circulation_mv') else "  流通市值: N/A")
    if target_themes:
        lines.append(f"  所属题材: {' / '.join(target_themes[:5])}")
    lines.append(f"  题材纯正度: {theme_purity:.0f}分")
    lines.append(f"  市场最高板: {'是' if is_market_highest else '否'}")
    lines.append("")

    # 2. 龙头评分
    lines.append("## 龙头评分")
    lines.append(f"  总分: {leader_score['total_score']}分")
    lines.append(f"  --- 因子明细 ---")
    for factor, score in leader_score["breakdown"].items():
        lines.append(f"    {factor}: {score}")
    if leader_score["bonuses"]:
        lines.append(f"  --- 加成 ---")
        for b in leader_score["bonuses"]:
            lines.append(f"    ✦ {b}")
    if leader_score["penalties"]:
        lines.append(f"  --- 扣分 ---")
        for p in leader_score["penalties"]:
            lines.append(f"    ✗ {p}")
    lines.append("")

    # 3. 龙头判断结论
    lines.append("## 龙头判断")
    if leader_score["total_score"] >= 70:
        lines.append(f"  结论: ✅ 高概率龙头（{leader_score['total_score']}分）")
    elif leader_score["total_score"] >= 50:
        lines.append(f"  结论: ⚠️ 有可能是龙头（{leader_score['total_score']}分）")
    else:
        lines.append(f"  结论: ❌ 不太可能是龙头（{leader_score['total_score']}分）")
    lines.append("")

    # 4. 同题材竞争者
    lines.append(f"## 同题材竞争者（共{len(same_theme_stocks)}只）")
    if same_theme_stocks:
        for i, s in enumerate(same_theme_stocks[:10]):
            board = s.get("board_num", 1)
            seal = s.get("seal_strength", 0)
            lines.append(
                f"  #{i+1} {s['code']} {s.get('name', '')} "
                f"{board}板 封单{seal:.2f}%"
            )
    else:
        lines.append("  无同题材涨停股")
    lines.append("")

    # 5. 卡位分析
    lines.append(f"## 卡位分析（共{len(card_positions)}只）")
    if card_positions:
        for cp in card_positions:
            emoji = "🔴" if cp["card_type"] == "强卡位" else "🟡" if cp["card_type"] == "中卡位" else "🟢"
            lines.append(
                f"  {emoji} {cp['code']} {cp['name']} "
                f"{cp['board_num']}板 封单比{cp['seal_ratio_to_leader']:.2f}x "
                f"→ {cp['card_type']}"
            )
    else:
        lines.append("  无卡位竞争者")
    lines.append("")

    # 6. 补涨龙
    lines.append(f"## 补涨龙候选（共{len(deputy_leaders)}只）")
    if deputy_leaders:
        for dl in deputy_leaders:
            dtype = dl.get("distinction_type", "uncertain")
            dtype_label = {
                "deputy_leader": "补涨龙",
                "new_leader": "可能新龙头",
                "uncertain": "待定",
            }.get(dtype, "待定")
            lines.append(
                f"  {dl['code']} {dl.get('name', '')} "
                f"{dl['board_num']}板 封单{dl['seal_strength']:.2f}% "
                f"理论高度{dl['theoretical_height']}板 "
                f"→ {dtype_label}（{dl.get('distinction_reason', '')}）"
            )
    else:
        lines.append("  无补涨龙候选")
    lines.append("")

    # 7. 强看好/强看空信号
    lines.append("## 信号判断")
    if strong_bullish.get("strong_bullish"):
        lines.append(f"  🟢 强看好: {strong_bullish['reason']}")
        lines.append(f"    操作: {strong_bullish.get('action', '')}")
        lines.append(f"    目标: {strong_bullish.get('target', '')}")
    else:
        lines.append(f"  ⚪ 非强看好: {strong_bullish['reason']}")

    if strong_bearish.get("strong_bearish"):
        lines.append(f"  🔴 强看空: {strong_bearish['reason']}")
        lines.append(f"    操作: {strong_bearish.get('action', '')}")
    else:
        lines.append(f"  ⚪ 非强看空: {strong_bearish['reason']}")
    lines.append("")

    # 8. 操作建议
    lines.append("## 操作建议")
    if strong_bullish.get("strong_bullish"):
        lines.append("  龙头确认，可重仓参与")
    elif leader_score["total_score"] >= 70:
        lines.append("  龙头概率高，可参与但控制仓位")
    elif leader_score["total_score"] >= 50:
        lines.append("  有可能是龙头，轻仓试探")
    else:
        lines.append("  龙头概率低，观望为主")

    if strong_bearish.get("strong_bearish"):
        lines.append(f"  ⚠ {strong_bearish['action']}")

    if card_positions:
        strong_cards = [cp for cp in card_positions if cp["card_type"] == "强卡位"]
        if strong_cards:
            lines.append(f"  ⚠ 有{len(strong_cards)}只强卡位股，注意龙头地位动摇")

    if deputy_leaders:
        new_leader_candidates = [
            dl for dl in deputy_leaders
            if dl.get("distinction_type") == "new_leader"
        ]
        if new_leader_candidates:
            lines.append(
                f"  ⚠ 发现{len(new_leader_candidates)}只可能的新龙头，"
                f"关注题材切换"
            )

    return "\n".join(lines)
