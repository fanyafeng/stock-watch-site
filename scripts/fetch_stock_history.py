#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/newfqkline/get"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
ADJUSTMENT = "qfq"

CSV_FIELDS = [
    "date",
    "code",
    "name",
    "exchange",
    "adjustment",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_change",
    "amplitude_pct",
    "volume_lot",
    "volume_shares",
    "amount_wan",
    "amount_yuan",
    "turnover_rate_pct",
    "ma5",
    "ma10",
    "ma20",
    "ma60",
    "vol_ma5_lot",
    "vol_ma10_lot",
    "vol_ma20_lot",
    "high_20",
    "low_20",
    "high_60",
    "low_60",
    "bar_status",
    "quote_time",
    "source",
]


class FetchError(Exception):
    pass


def exchange_for_code(code: str) -> str:
    return "SH" if code.startswith(("6", "9")) else "SZ"


def symbol_for_code(code: str) -> str:
    return exchange_for_code(code).lower() + code


def fetch_bytes(url: str, *, referer: str | None = None, timeout: int = 30) -> bytes:
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.read()


def fetch_text(url: str, *, encoding: str = "utf-8", referer: str | None = None, timeout: int = 30) -> str:
    return fetch_bytes(url, referer=referer, timeout=timeout).decode(encoding, errors="ignore")


def to_float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, dict):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def round_or_empty(value: float | None, digits: int = 3) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def int_or_empty(value: float | None) -> str:
    return "" if value is None else str(int(round(value)))


def rolling_average(values: list[float | None], end_index: int, window: int) -> float | None:
    start = max(0, end_index - window + 1)
    window_values = [value for value in values[start : end_index + 1] if value is not None]
    return sum(window_values) / window if len(window_values) >= window else None


def rolling_max(values: list[float | None], end_index: int, window: int) -> float | None:
    start = max(0, end_index - window + 1)
    window_values = [value for value in values[start : end_index + 1] if value is not None]
    return max(window_values) if window_values else None


def rolling_min(values: list[float | None], end_index: int, window: int) -> float | None:
    start = max(0, end_index - window + 1)
    window_values = [value for value in values[start : end_index + 1] if value is not None]
    return min(window_values) if window_values else None


def fetch_tencent_kline(symbol: str, period: str, count: int, adjustment: str) -> list[list[Any]]:
    params = urllib.parse.urlencode({"param": f"{symbol},{period},,,{count},{adjustment}"})
    url = f"{TENCENT_KLINE_URL}?{params}"
    payload = json.loads(fetch_text(url, referer="https://gu.qq.com/"))
    if payload.get("code") != 0:
        raise FetchError(f"腾讯 K 线接口返回异常：{payload.get('msg') or payload.get('code')}")
    key = f"{adjustment}{period}" if adjustment in {"qfq", "hfq"} else period
    rows = payload.get("data", {}).get(symbol, {}).get(key, [])
    if not rows:
        raise FetchError(f"腾讯 K 线接口未返回 {symbol} {period}/{adjustment} 数据")
    return rows


def parse_tencent_quote(code: str, fallback_name: str) -> dict[str, Any]:
    symbol = symbol_for_code(code)
    text = fetch_text(TENCENT_QUOTE_URL + symbol, encoding="gbk", referer="https://gu.qq.com/", timeout=12)
    if '="' not in text:
        raise FetchError("腾讯报价接口格式异常")
    fields = text.split('="', 1)[1].rsplit('"', 1)[0].split("~")

    def pick(index: int) -> str:
        return fields[index] if index < len(fields) else ""

    quote_time = pick(30)
    quote_time_text = ""
    if len(quote_time) == 14:
        try:
            quote_time_text = dt.datetime.strptime(quote_time, "%Y%m%d%H%M%S").isoformat(sep=" ")
        except ValueError:
            quote_time_text = quote_time

    quote = {
        "source": "tencent_realtime_quote",
        "symbol": symbol,
        "code": pick(2) or code,
        "name": pick(1) or fallback_name,
        "quote_time": quote_time_text or quote_time,
        "current_price": to_float(pick(3)),
        "previous_close": to_float(pick(4)),
        "open": to_float(pick(5)),
        "high": to_float(pick(33)),
        "low": to_float(pick(34)),
        "change": to_float(pick(31)),
        "pct_change": to_float(pick(32)),
        "volume_lot": to_float(pick(36)),
        "amount_wan": to_float(pick(37)),
        "turnover_rate_pct": to_float(pick(38)),
        "amplitude_pct": to_float(pick(43)),
        "limit_up": to_float(pick(47)),
        "limit_down": to_float(pick(48)),
        "year_high": to_float(pick(67)),
        "year_low": to_float(pick(68)),
        "raw": text.strip(),
    }
    quote["volume_shares"] = quote["volume_lot"] * 100 if quote["volume_lot"] is not None else None
    quote["amount_yuan"] = quote["amount_wan"] * 10000 if quote["amount_wan"] is not None else None
    return quote


def build_daily_rows(
    *,
    raw_rows: list[list[Any]],
    code: str,
    name: str,
    exchange: str,
    start: dt.date,
    end: dt.date,
    quote: dict[str, Any],
    adjustment: str,
) -> list[dict[str, str]]:
    parsed: list[dict[str, Any]] = []
    for raw in raw_rows:
        if len(raw) < 6:
            continue
        try:
            row_date = dt.date.fromisoformat(str(raw[0]))
        except ValueError:
            continue
        parsed.append(
            {
                "date": row_date,
                "open": to_float(raw[1]),
                "close": to_float(raw[2]),
                "high": to_float(raw[3]),
                "low": to_float(raw[4]),
                "volume_lot": to_float(raw[5]),
                "turnover_rate_pct": to_float(raw[7]) if len(raw) > 7 else None,
                "amount_wan": to_float(raw[8]) if len(raw) > 8 else None,
            }
        )

    parsed.sort(key=lambda item: item["date"])
    closes = [item["close"] for item in parsed]
    highs = [item["high"] for item in parsed]
    lows = [item["low"] for item in parsed]
    volumes = [item["volume_lot"] for item in parsed]
    quote_date = str(quote.get("quote_time") or "").split(" ", 1)[0]

    rows: list[dict[str, str]] = []
    for index, item in enumerate(parsed):
        row_date = item["date"]
        if row_date < start or row_date > end:
            continue
        pre_close = closes[index - 1] if index > 0 else None
        close = item["close"]
        high = item["high"]
        low = item["low"]
        volume_lot = item["volume_lot"]
        amount_wan = item["amount_wan"]
        change = close - pre_close if close is not None and pre_close else None
        pct_change = change / pre_close * 100 if change is not None and pre_close else None
        amplitude = (high - low) / pre_close * 100 if high is not None and low is not None and pre_close else None
        rows.append(
            {
                "date": row_date.isoformat(),
                "code": code,
                "name": name,
                "exchange": exchange,
                "adjustment": adjustment,
                "open": round_or_empty(item["open"]),
                "high": round_or_empty(high),
                "low": round_or_empty(low),
                "close": round_or_empty(close),
                "pre_close": round_or_empty(pre_close),
                "change": round_or_empty(change),
                "pct_change": round_or_empty(pct_change, 2),
                "amplitude_pct": round_or_empty(amplitude, 2),
                "volume_lot": int_or_empty(volume_lot),
                "volume_shares": int_or_empty(volume_lot * 100 if volume_lot is not None else None),
                "amount_wan": round_or_empty(amount_wan, 2),
                "amount_yuan": round_or_empty(amount_wan * 10000 if amount_wan is not None else None, 2),
                "turnover_rate_pct": round_or_empty(item["turnover_rate_pct"], 2),
                "ma5": round_or_empty(rolling_average(closes, index, 5)),
                "ma10": round_or_empty(rolling_average(closes, index, 10)),
                "ma20": round_or_empty(rolling_average(closes, index, 20)),
                "ma60": round_or_empty(rolling_average(closes, index, 60)),
                "vol_ma5_lot": round_or_empty(rolling_average(volumes, index, 5), 0),
                "vol_ma10_lot": round_or_empty(rolling_average(volumes, index, 10), 0),
                "vol_ma20_lot": round_or_empty(rolling_average(volumes, index, 20), 0),
                "high_20": round_or_empty(rolling_max(highs, index, 20)),
                "low_20": round_or_empty(rolling_min(lows, index, 20)),
                "high_60": round_or_empty(rolling_max(highs, index, 60)),
                "low_60": round_or_empty(rolling_min(lows, index, 60)),
                "bar_status": "intraday" if row_date.isoformat() == quote_date else "closed",
                "quote_time": str(quote.get("quote_time") or "") if row_date.isoformat() == quote_date else "",
                "source": "tencent_newfqkline",
            }
        )
    return rows


def build_period_rows(
    *,
    raw_rows: list[list[Any]],
    code: str,
    name: str,
    exchange: str,
    start: dt.date,
    end: dt.date,
    period: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    previous_close: float | None = None
    for raw in raw_rows:
        if len(raw) < 6:
            continue
        try:
            row_date = dt.date.fromisoformat(str(raw[0]))
        except ValueError:
            continue
        if row_date < start or row_date > end:
            close = to_float(raw[2])
            if close is not None:
                previous_close = close
            continue
        open_price = to_float(raw[1])
        close = to_float(raw[2])
        high = to_float(raw[3])
        low = to_float(raw[4])
        volume_lot = to_float(raw[5])
        turnover_rate = to_float(raw[7]) if len(raw) > 7 else None
        amount_wan = to_float(raw[8]) if len(raw) > 8 else None
        change = close - previous_close if close is not None and previous_close else None
        pct_change = change / previous_close * 100 if change is not None and previous_close else None
        amplitude = (high - low) / previous_close * 100 if high is not None and low is not None and previous_close else None
        rows.append(
            {
                "date": row_date.isoformat(),
                "code": code,
                "name": name,
                "exchange": exchange,
                "period": period,
                "adjustment": ADJUSTMENT,
                "open": round_or_empty(open_price),
                "high": round_or_empty(high),
                "low": round_or_empty(low),
                "close": round_or_empty(close),
                "pre_close": round_or_empty(previous_close),
                "change": round_or_empty(change),
                "pct_change": round_or_empty(pct_change, 2),
                "amplitude_pct": round_or_empty(amplitude, 2),
                "volume_lot": int_or_empty(volume_lot),
                "volume_shares": int_or_empty(volume_lot * 100 if volume_lot is not None else None),
                "amount_wan": round_or_empty(amount_wan, 2),
                "amount_yuan": round_or_empty(amount_wan * 10000 if amount_wan is not None else None, 2),
                "turnover_rate_pct": round_or_empty(turnover_rate, 2),
                "source": "tencent_newfqkline",
            }
        )
        if close is not None:
            previous_close = close
    return rows


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_date(value: str | None) -> dt.date:
    return dt.date.fromisoformat(value) if value else dt.date.today()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch public Tencent history for an A-share stock.")
    parser.add_argument("--code", required=True, help="股票代码，例如 000420")
    parser.add_argument("--name", default="", help="股票名称，留空则使用腾讯报价名称")
    parser.add_argument("--start", help="开始日期 YYYY-MM-DD，默认 end 往前 window-years 年")
    parser.add_argument("--end", help="结束日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--count", type=int, default=780, help="腾讯接口回看 K 线数量")
    parser.add_argument("--window-years", type=int, default=2, choices=[1, 2, 3])
    args = parser.parse_args()

    try:
        code = args.code.zfill(6)
        exchange = exchange_for_code(code)
        symbol = symbol_for_code(code)
        end = parse_date(args.end)
        start = parse_date(args.start) if args.start else end - dt.timedelta(days=365 * args.window_years)
        if start > end:
            raise FetchError("开始日期不能晚于结束日期")
        suffix = f"{args.window_years}y"
        out_dir = ROOT / "data" / "stocks" / code

        quote = parse_tencent_quote(code, args.name or code)
        name = args.name or str(quote.get("name") or code)
        daily_rows = build_daily_rows(
            raw_rows=fetch_tencent_kline(symbol, "day", args.count, ADJUSTMENT),
            code=code,
            name=name,
            exchange=exchange,
            start=start,
            end=end,
            quote=quote,
            adjustment=ADJUSTMENT,
        )
        if not daily_rows:
            raise FetchError(f"未获得 {start} 至 {end} 的日线数据")
        bfq_rows = build_daily_rows(
            raw_rows=fetch_tencent_kline(symbol, "day", args.count, "bfq"),
            code=code,
            name=name,
            exchange=exchange,
            start=start,
            end=end,
            quote=quote,
            adjustment="bfq",
        )
        week_rows = build_period_rows(
            raw_rows=fetch_tencent_kline(symbol, "week", args.count, ADJUSTMENT),
            code=code,
            name=name,
            exchange=exchange,
            start=start,
            end=end,
            period="week",
        )
        month_rows = build_period_rows(
            raw_rows=fetch_tencent_kline(symbol, "month", args.count, ADJUSTMENT),
            code=code,
            name=name,
            exchange=exchange,
            start=start,
            end=end,
            period="month",
        )
        fetched_at = dt.datetime.now().isoformat(timespec="seconds")
        metadata = {
            "code": code,
            "name": name,
            "symbol": symbol,
            "exchange": exchange,
            "adjustment": ADJUSTMENT,
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "first_trading_date": daily_rows[0]["date"],
            "last_trading_date": daily_rows[-1]["date"],
            "row_count": len(daily_rows),
            "fetched_at": fetched_at,
            "primary_source": {
                "name": "Tencent newfqkline public endpoint",
                "url": f"{TENCENT_KLINE_URL}?param={symbol},day,,,{args.count},{ADJUSTMENT}",
            },
            "quote_source": {"name": "Tencent realtime quote public endpoint", "url": TENCENT_QUOTE_URL + symbol},
            "files": {
                "daily_csv": f"daily_qfq_{suffix}.csv",
                "daily_json": f"daily_qfq_{suffix}.json",
                "daily_bfq_csv": f"daily_bfq_{suffix}.csv",
                "weekly_qfq_csv": f"weekly_qfq_{suffix}.csv",
                "monthly_qfq_csv": f"monthly_qfq_{suffix}.csv",
                "latest_quote": "latest_quote.json",
                "metadata": f"metadata_{suffix}.json",
            },
        }

        write_csv(out_dir / f"daily_qfq_{suffix}.csv", daily_rows, CSV_FIELDS)
        write_json(out_dir / f"daily_qfq_{suffix}.json", daily_rows)
        write_csv(out_dir / f"daily_bfq_{suffix}.csv", bfq_rows, CSV_FIELDS)
        write_csv(out_dir / f"weekly_qfq_{suffix}.csv", week_rows)
        write_csv(out_dir / f"monthly_qfq_{suffix}.csv", month_rows)
        write_json(out_dir / "latest_quote.json", quote | {"fetched_at": fetched_at})
        write_json(out_dir / f"metadata_{suffix}.json", metadata)
        write_json(out_dir / "metadata.json", metadata)

        print(f"saved {len(daily_rows)} rows: {out_dir / f'daily_qfq_{suffix}.csv'}")
        print(f"range: {daily_rows[0]['date']} -> {daily_rows[-1]['date']}")
        print(f"latest quote: {quote.get('quote_time')} {quote.get('current_price')}")
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
