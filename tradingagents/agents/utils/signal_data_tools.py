from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_profit_forecast(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
) -> str:
    """
    Retrieve consensus EPS forecasts with forward valuation metrics.
    Returns analyst coverage count, EPS range, forward PE, PEG, and PE digestion time.
    Uses the configured signal_data vendor.
    Args:
        ticker (str): A-stock code
    Returns:
        str: Consensus forecast report with valuation metrics
    """
    return route_to_vendor("get_profit_forecast", ticker)


@tool
def get_hot_stocks(
    curr_date: Annotated[str, "Date in YYYY-MM-DD format, empty for today"] = "",
) -> str:
    """
    Retrieve today's strong stocks with topic attribution reason tags.
    Shows WHY stocks surged (e.g. '算力租赁+AI政务'), curated by 同花顺 editorial team.
    Includes theme frequency analysis.
    Uses the configured signal_data vendor.
    Args:
        curr_date (str): Date in YYYY-MM-DD format, empty string for today
    Returns:
        str: Hot stocks list with reason tags and theme frequency
    """
    return route_to_vendor("get_hot_stocks", curr_date)


@tool
def get_northbound_flow(
    curr_date: Annotated[str, "Date in YYYY-MM-DD format"],
    include_history: Annotated[
        bool, "Include historical daily data (last 20 trading days)"
    ] = False,
) -> str:
    """
    Retrieve northbound capital flow (沪深股通) data.
    Realtime: minute-level cumulative net buying for HGT + SGT.
    History (optional): daily-level data for trend analysis.
    Uses the configured signal_data vendor.
    Args:
        curr_date (str): Date in YYYY-MM-DD format
        include_history (bool): Whether to include historical daily data
    Returns:
        str: Northbound capital flow report with bullish/bearish signal
    """
    return route_to_vendor("get_northbound_flow", curr_date, include_history)


@tool
def get_concept_blocks(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
) -> str:
    """
    Retrieve concept/sector/region blocks that a stock belongs to.
    Shows industry (申万), concept themes (e.g. 机器人概念, 减速器), and region.
    Each block includes current day's change percentage.
    Uses the configured signal_data vendor.
    Args:
        ticker (str): A-stock code
    Returns:
        str: Concept and sector block membership with daily changes
    """
    return route_to_vendor("get_concept_blocks", ticker)


@tool
def get_fund_flow(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "Date in YYYY-MM-DD format"],
    include_history: Annotated[
        bool, "Include historical daily fund flow (last 20 days)"
    ] = True,
) -> str:
    """
    Retrieve individual stock fund flow (main force vs retail investor).
    Realtime: minute-level super/large/medium/small order flow.
    History: daily net inflow by order size for 20 trading days.
    Uses the configured signal_data vendor.
    Args:
        ticker (str): A-stock code
        curr_date (str): Date in YYYY-MM-DD format
        include_history (bool): Include 20-day historical daily flow
    Returns:
        str: Fund flow report with main force signal
    """
    return route_to_vendor("get_fund_flow", ticker, curr_date, include_history)


@tool
def get_dragon_tiger_board(
    ticker: Annotated[str, "A-stock code (e.g. 000858)"],
    curr_date: Annotated[str, "Date in YYYY-MM-DD format"],
    look_back_days: Annotated[int, "Days to look back (default 30)"] = 30,
) -> str:
    """
    Retrieve dragon-tiger board (龙虎榜) data for a stock.
    Shows recent LHB appearances, top buyer/seller seats (营业部),
    and institutional involvement. Key signal for hot money tracking.
    Args:
        ticker (str): A-stock code
        curr_date (str): Date in YYYY-MM-DD format
        look_back_days (int): How many days back to search
    Returns:
        str: LHB appearances with seat details and institutional activity
    """
    return route_to_vendor("get_dragon_tiger_board", ticker, curr_date, look_back_days)


@tool
def get_lockup_expiry(
    ticker: Annotated[str, "A-stock code (e.g. 000858)"],
    curr_date: Annotated[str, "Date in YYYY-MM-DD format"],
    forward_days: Annotated[int, "Days forward to check (default 90)"] = 90,
) -> str:
    """
    Retrieve lockup expiry (限售解禁) schedule for a stock.
    Shows historical unlock records and upcoming expiry calendar
    with impact metrics (unlock quantity, market cap ratio).
    Args:
        ticker (str): A-stock code
        curr_date (str): Date in YYYY-MM-DD format
        forward_days (int): How many days forward to check
    Returns:
        str: Lockup expiry schedule with impact assessment
    """
    return route_to_vendor("get_lockup_expiry", ticker, curr_date, forward_days)


@tool
def get_industry_comparison(
    ticker: Annotated[str, "A-stock code (e.g. 000858)"],
    curr_date: Annotated[str, "Date in YYYY-MM-DD format"],
) -> str:
    """
    Retrieve industry sector performance comparison (行业横向对比).
    Shows all 90 THS industries ranked by performance with turnover,
    net capital flow, and leading stocks. Useful for sector rotation analysis.
    Args:
        ticker (str): A-stock code (used to identify relevant sector)
        curr_date (str): Date in YYYY-MM-DD format
    Returns:
        str: Industry performance ranking with key metrics
    """
    return route_to_vendor("get_industry_comparison", ticker, curr_date)


@tool
def get_margin_trading(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
    page_size: Annotated[int, "Number of days (default 30)"] = 30,
) -> str:
    """
    Retrieve margin trading data (融资融券明细).
    Shows daily margin balance (融资余额), margin buying (融资买入),
    short selling (融券余额), and trends.
    Rising margin balance = bullish leveraged conviction.
    Rising short selling = direct bearish bet.
    Args:
        ticker (str): A-stock code
        page_size (int): Number of days to fetch
    Returns:
        str: Margin trading report with leverage sentiment signal
    """
    return route_to_vendor("get_margin_trading", ticker, page_size)


@tool
def get_block_trade(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
    page_size: Annotated[int, "Number of records (default 20)"] = 20,
) -> str:
    """
    Retrieve block trade records (大宗交易).
    Shows deal price, volume, buyer/seller broker names, premium/discount %.
    Premium (溢价) = motivated buyer; Discount (折价) = motivated seller.
    Large block trades often precede significant price moves by 1-5 days.
    Args:
        ticker (str): A-stock code
        page_size (int): Number of records to fetch
    Returns:
        str: Block trade report with institutional intent signal
    """
    return route_to_vendor("get_block_trade", ticker, page_size)


@tool
def get_shareholder_count(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
    page_size: Annotated[int, "Number of quarters (default 10)"] = 10,
) -> str:
    """
    Retrieve shareholder count changes (股东户数变化).
    Shows quarterly shareholder count, change ratio, avg shares per holder.
    Key signal: declining count + rising avg shares = chip concentration (筹码集中)
    = classic institutional accumulation pattern.
    Args:
        ticker (str): A-stock code
        page_size (int): Number of quarters to fetch
    Returns:
        str: Shareholder count report with chip concentration signal
    """
    return route_to_vendor("get_shareholder_count", ticker, page_size)


@tool
def get_research_reports(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
    max_pages: Annotated[int, "Max pages (default 2)"] = 2,
) -> str:
    """
    Retrieve broker research reports with ratings and EPS forecasts.
    Shows title, institution, rating (买入/增持/中性/减持), EPS forecasts.
    Rating distribution reveals institutional consensus direction.
    Recent rating downgrades are bearish signals.
    Args:
        ticker (str): A-stock code
        max_pages (int): Max pages to fetch
    Returns:
        str: Research report list with rating distribution and EPS consensus
    """
    return route_to_vendor("get_research_reports", ticker, max_pages)


@tool
def get_dividend_history(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
    page_size: Annotated[int, "Number of records (default 10)"] = 10,
) -> str:
    """
    Retrieve dividend and bonus share history (分红送转历史).
    Shows per-share cash dividend, bonus shares, transfer shares.
    Enables dividend yield calculation and high bonus/transfer catalyst detection.
    Args:
        ticker (str): A-stock code
        page_size (int): Number of records to fetch
    Returns:
        str: Dividend history with yield and bonus/transfer events
    """
    return route_to_vendor("get_dividend_history", ticker, page_size)


@tool
def get_daily_dragon_tiger(
    trade_date: Annotated[str, "YYYY-MM-DD (default today)"] = "",
    min_net_buy: Annotated[float, "Min net buy in 万 (default 0)"] = 0,
) -> str:
    """
    Retrieve daily full-market dragon tiger board (全市场龙虎榜).
    Shows all stocks that hit LHB on a given day with reasons,
    net buy amounts, and turnover rates. Useful for sector-wide hot money context.
    Args:
        trade_date (str): YYYY-MM-DD, empty for today
        min_net_buy (float): Minimum net buy amount in 万 to filter
    Returns:
        str: Full market LHB summary with top net buyers
    """
    return route_to_vendor("get_daily_dragon_tiger", trade_date, min_net_buy)


@tool
def get_northbound_stock_holdings(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
) -> str:
    """
    Retrieve northbound capital holdings for individual stock (北向个股持仓).
    Shows how much HK-SH/SZ capital holds in a specific stock.
    Rising holdings = foreign institutional buying = bullish signal.
    Args:
        ticker (str): A-stock code
    Returns:
        str: Northbound holdings report with trend signal
    """
    return route_to_vendor("get_northbound_stock_holdings", ticker)


@tool
def get_cninfo_announcements(
    ticker: Annotated[str, "A-stock code (e.g. 688017)"],
    page_size: Annotated[int, "Number of announcements (default 30)"] = 30,
) -> str:
    """
    Retrieve official company announcements from cninfo (巨潮公告).
    cninfo is the legally binding disclosure channel in China.
    Many material events appear here 1-3 days before news articles:
    - 股权质押公告 (equity pledge)
    - 关联交易公告 (related-party transaction)
    - 年报/季报 (financial reports)
    - 股东减持计划 (shareholder reduction plans)
    Risk announcements (质押/减持/担保/诉讼/处罚) are highlighted.
    Args:
        ticker (str): A-stock code
        page_size (int): Number of announcements to fetch
    Returns:
        str: Announcement list with type distribution and risk alerts
    """
    return route_to_vendor("get_cninfo_announcements", ticker, page_size)


@tool
def get_consecutive_limit_stats(
    trade_date: Annotated[str, "Date in YYYY-MM-DD format"],
) -> str:
    """
    Retrieve consecutive limit-up board statistics and market emotion metrics.
    Returns board distribution (连板梯队), seal quality, yesterday's limit-up performance,
    emotion phase judgment (冰点/回暖/升温/高潮/退潮), and overall emotion score.
    Key for short-term traders to gauge market temperature.
    Args:
        trade_date (str): Date in YYYY-MM-DD format
    Returns:
        str: Consecutive limit-up stats with emotion phase and health score
    """
    return route_to_vendor("get_consecutive_limit_stats", trade_date)


@tool
def get_theme_heat(
    trade_date: Annotated[str, "Date in YYYY-MM-DD format"],
    top_n: Annotated[int, "Number of top themes to return, default 10"] = 10,
) -> str:
    """
    Retrieve theme/sector heat tracking with trend and phase analysis.
    Returns top themes ranked by heat score, each with: heat score, trend direction,
    lifecycle phase (启动/加速/分歧/退潮), recognition score, and leader status.
    Critical for identifying which themes are gaining momentum.
    Args:
        trade_date (str): Date in YYYY-MM-DD format
        top_n (int): Number of top themes to return (default 10)
    Returns:
        str: Theme heat ranking with trend, phase, and leader analysis
    """
    return route_to_vendor("get_theme_heat", trade_date, top_n)


@tool
def get_first_board_screen(
    trade_date: Annotated[str, "Date in YYYY-MM-DD format"],
    min_score: Annotated[int, "Minimum second-board expectation score, default 60"] = 60,
) -> str:
    """
    Retrieve first-board (首板) stock screening with second-board probability scoring.
    Returns today's first limit-up stocks ranked by second-board expectation score.
    Each stock includes: seal quality, theme purity, volume-price match, and composite score.
    Useful for identifying high-probability breakout candidates.
    Args:
        trade_date (str): Date in YYYY-MM-DD format
        min_score (int): Minimum second-board expectation score (default 60)
    Returns:
        str: First-board screening report with second-board expectation scores
    """
    return route_to_vendor("get_first_board_screen", trade_date, min_score)


@tool
def get_high_board_status(
    trade_date: Annotated[str, "Date in YYYY-MM-DD format"],
) -> str:
    """
    Retrieve high-board (高标股) status monitoring for market leaders.
    Returns the highest consecutive limit-up stocks with: divergence score,
    break-board risk level, cumulative turnover, and sector effect analysis.
    Key for tracking whether market height is expanding or contracting.
    Args:
        trade_date (str): Date in YYYY-MM-DD format
    Returns:
        str: High-board status report with risk assessment and sector effects
    """
    return route_to_vendor("get_high_board_status", trade_date)


@tool
def get_leader_identification(
    ticker: Annotated[str, "A-stock code (e.g. 000001), empty to use theme-only mode"] = "",
    trade_date: Annotated[str, "Date in YYYY-MM-DD format"] = "",
    theme: Annotated[str, "Theme name to analyze when ticker is empty"] = "",
) -> str:
    """
    Retrieve leader (龙头) identification and card-position (卡位) analysis.
    Returns leader candidates ranked by leader score, card-position detection,
    deputy leader (补涨龙) identification, and new leader vs deputy distinction.
    Essential for understanding intra-theme hierarchy and rotation.
    Args:
        ticker (str): Target stock code; pass company_of_interest for per-stock analysis
        trade_date (str): Date in YYYY-MM-DD format
        theme (str): Specific theme to analyze when ticker is empty
    Returns:
        str: Leader identification report with scoring and position analysis
    """
    return route_to_vendor("get_leader_identification", ticker, trade_date, theme)
