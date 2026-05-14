#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MARKET_FIELDS = ["section", "value", "note"]
EASTMONEY_FLOW_HOSTS = [
    "push2.eastmoney.com",
    "push2delay.eastmoney.com",
]
INDEXES = [
    ("1.000001", "上证指数"),
    ("0.399001", "深证成指"),
    ("0.399006", "创业板指"),
]


class FlowFetchError(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch index intraday main-money-flow series for market.csv")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="交易日期，格式 YYYY-MM-DD，默认今天")
    parser.add_argument("--source", choices=["auto", "ths", "eastmoney"], default="auto", help="数据源，默认 auto")
    parser.add_argument("--mode", choices=["strict", "loose"], default="loose", help="strict 失败退出；loose 失败只提示")
    parser.add_argument("--force", action="store_true", help="即使本地已有 index_money_flow_series 也重新拉取")
    return parser.parse_args()


def request_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            **(headers or {}),
        },
    )
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=12, context=context) as response:
            return json.loads(response.read().decode("utf-8"))
    except (ssl.SSLError, urllib.error.URLError) as error:
        if not isinstance(error, ssl.SSLError) and "CERTIFICATE_VERIFY_FAILED" not in str(error):
            raise
        with urllib.request.urlopen(req, timeout=12, context=ssl._create_unverified_context()) as response:
            return json.loads(response.read().decode("utf-8"))


def fetch_ths_index_money_flow(_date_text: str) -> list[tuple[str, float]]:
    """Reserved for a stable THS money-flow endpoint.

    同花顺公开分时价量接口可访问，但主力净流分时通常属于商业/Level-2 数据。
    这里保留扩展点，避免页面用无法复核的数据。
    """

    raise FlowFetchError("未找到稳定可公开访问的同花顺指数主力净流分时接口")


def eastmoney_urls(secid: str) -> list[str]:
    query = (
        "lmt=0&klt=1"
        "&fields1=f1,f2,f3,f7"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
        f"&secid={secid}"
    )
    return [f"https://{host}/api/qt/stock/fflow/kline/get?{query}" for host in EASTMONEY_FLOW_HOSTS]


def parse_eastmoney_kline(row: str) -> tuple[str, float] | None:
    parts = row.split(",")
    if len(parts) < 2:
        return None
    timestamp = parts[0].strip()
    try:
        amount = float(parts[1])
    except ValueError:
        return None
    time_text = timestamp[-5:]
    return time_text, amount / 100000000


def fetch_eastmoney_index_money_flow(date_text: str) -> list[tuple[str, float]]:
    target_date = date_text.replace("-", "")
    merged: dict[str, float] = {}
    for secid, name in INDEXES:
        errors: list[str] = []
        payload: dict[str, Any] | None = None
        for url in eastmoney_urls(secid):
            try:
                payload = request_json(url, {"Referer": "https://quote.eastmoney.com/"})
                break
            except Exception as error:
                errors.append(f"{url.split('/')[2]}: {error}")
        if payload is None:
            raise FlowFetchError(f"东方财富未返回 {name} 主力净流分时：{'; '.join(errors)}")
        data = payload.get("data") or {}
        rows = data.get("klines") or []
        if not rows:
            raise FlowFetchError(f"东方财富未返回 {name} 主力净流分时")
        matched = [row for row in rows if str(row).startswith(date_text)]
        if not matched:
            matched = [row for row in rows if str(row).startswith(target_date)]
        for row in matched:
            parsed = parse_eastmoney_kline(row)
            if not parsed:
                continue
            time_text, amount_yi = parsed
            merged[time_text] = merged.get(time_text, 0.0) + amount_yi
    if not merged:
        raise FlowFetchError(f"东方财富未返回 {date_text} 的指数主力净流分时")
    return sorted(merged.items())


def serialize_series(series: list[tuple[str, float]], target_points: int = 48) -> str:
    if not series:
        return ""
    step = max(1, len(series) // target_points)
    sampled = series[::step]
    if sampled[-1][0] != series[-1][0]:
        sampled.append(series[-1])
    return ";".join(f"{time}={value:.2f}" for time, value in sampled)


def market_path(date_text: str) -> Path:
    return ROOT / "data" / "daily" / date_text / "market.csv"


def read_market_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def read_market_value(path: Path, section: str) -> str:
    for row in read_market_rows(path):
        if row.get("section") == section:
            return (row.get("value") or "").strip()
    return ""


def write_market_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=MARKET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def upsert_market_row(path: Path, section: str, value: str, note: str) -> None:
    rows = read_market_rows(path)
    found = False
    for row in rows:
        if row.get("section") == section:
            row["value"] = value
            row["note"] = note
            found = True
            break
    if not found:
        rows.append({"section": section, "value": value, "note": note})
    write_market_rows(path, rows)


def fetch_series(date_text: str, source: str) -> tuple[list[tuple[str, float]], str]:
    errors: list[str] = []
    if source in {"auto", "ths"}:
        try:
            return fetch_ths_index_money_flow(date_text), "同花顺"
        except Exception as error:
            errors.append(f"同花顺：{error}")
            if source == "ths":
                raise FlowFetchError("; ".join(errors))
    if source in {"auto", "eastmoney"}:
        try:
            return fetch_eastmoney_index_money_flow(date_text), "东方财富"
        except Exception as error:
            errors.append(f"东方财富：{error}")
    raise FlowFetchError("; ".join(errors))


def main() -> int:
    args = parse_args()
    path = market_path(args.date)
    existing = read_market_value(path, "index_money_flow_series")
    if existing and not args.force:
        print(f"kept: {path} index_money_flow_series already exists ({len(existing.split(';'))} points)")
        return 0

    try:
        series, source_name = fetch_series(args.date, args.source)
        value = serialize_series(series)
        if not value:
            raise FlowFetchError("指数主力净流分时为空")
        upsert_market_row(
            path,
            "index_money_flow_series",
            value,
            f"{source_name}逐分钟主力净流，单位：亿元；核心三指数合计",
        )
        print(f"updated: {path} index_money_flow_series ({source_name}, {len(series)} points)")
        return 0
    except Exception as error:
        message = f"指数主力净流分时拉取失败：{error}"
        print(message, file=sys.stderr)
        return 1 if args.mode == "strict" else 0


if __name__ == "__main__":
    raise SystemExit(main())
