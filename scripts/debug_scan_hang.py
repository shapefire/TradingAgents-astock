"""Debug script for scan-short-term hang investigation."""
import time

from tradingagents.dataflows.a_stock import (
    _calculate_consecutive_days,
    _enrich_limitup_stock,
    _get_em_xuangu_quotes,
    _get_limitup_stocks_em,
    _get_limitup_stocks_ths,
    _load_ohlcv_astock,
    clear_session_cache,
)

TRADE_DATE = "2026-06-18"


def main() -> None:
    clear_session_cache()
    em_pool = _get_limitup_stocks_em(TRADE_DATE)
    ths_stocks = _get_limitup_stocks_ths(TRADE_DATE)
    ths_by_code = {s["code"]: s for s in ths_stocks}
    all_codes = list(dict.fromkeys(list(em_pool.keys()) + list(ths_by_code.keys())))
    em_quotes = _get_em_xuangu_quotes(all_codes[:50])
    if len(all_codes) > 50:
        em_quotes.update(_get_em_xuangu_quotes(all_codes[50:100]))

    print(f"total codes: {len(all_codes)}")
    for idx in range(88, min(101, len(all_codes))):
        code = all_codes[idx]
        em = em_pool.get(code, {})
        print(
            f"idx={idx} code={code} em_days={em.get('consecutive_days', 0)} "
            f"name={ths_by_code.get(code, {}).get('name', '')}"
        )

    print("\n--- test enrich from idx 90 ---")
    for idx in range(90, len(all_codes)):
        code = all_codes[idx]
        ths = ths_by_code.get(code, {})
        em = em_pool.get(code, {})
        stock = {
            "code": code,
            "name": ths.get("name") or em.get("name", ""),
            "reason": ths.get("reason", ""),
        }
        t0 = time.perf_counter()
        _enrich_limitup_stock(stock, TRADE_DATE, em_pool, em_quotes)
        print(f"enriched idx={idx} code={code} in {time.perf_counter() - t0:.1f}s")

    print("\n--- test kline fallback ST stocks ---")
    for code in all_codes:
        em = em_pool.get(code, {})
        if em.get("consecutive_days", 0) > 0:
            continue
        t0 = time.perf_counter()
        try:
            df = _load_ohlcv_astock(code, TRADE_DATE)
            rows = 0 if df is None else len(df)
            days = _calculate_consecutive_days(code, TRADE_DATE)
            print(
                f"code={code} ohlcv_rows={rows} consecutive={days} "
                f"in {time.perf_counter() - t0:.1f}s"
            )
        except Exception as exc:
            print(f"code={code} FAILED in {time.perf_counter() - t0:.1f}s: {exc}")


if __name__ == "__main__":
    main()
