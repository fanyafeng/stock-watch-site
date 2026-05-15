#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCES_DIR = ROOT / "data" / "sources"
DATA_OUT = ROOT / "data" / "source_stock_tracks.json"
ASTRO_OUT = ROOT / "src" / "data" / "source_stock_tracks.json"

STOCK_RE = re.compile(r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{2,12})[（(](?P<code>\d{6})[）)]")
TIME_RE = re.compile(r"(?P<time>\d{2}:\d{2})")

SELL_RE = re.compile(r"(走了|卖了|减仓|减一点|不符合.{0,8}减|去弱留强|弱了就是弱了|清仓|出局|割了|跑了)")
BUY_RE = re.compile(r"(试错|加仓|买入|我买|能买|重拳出击|低吸)")
HOLD_RE = re.compile(r"(没动|不动|持股|耐心持股|不要乱动|拿住|拿着|继续拿)")
BUY_NEGATIVE_RE = re.compile(r"(不会.{0,6}买|不要.{0,6}买|买卖自由)")


class SourceTrackError(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate source-level stock tracking summary for the Sources tab.")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="统计截至日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--source", action="append", help="来源 id，可重复；默认先生成 yege")
    parser.add_argument("--all", action="store_true", help="尝试生成所有来源")
    parser.add_argument("--mode", choices=["strict", "loose"], default="loose", help="strict 行情失败报错；loose 显示待行情")
    parser.add_argument("--skip-price", action="store_true", help="跳过东方财富行情拉取")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(file_obj)
            if any((value or "").strip() for value in row.values())
        ]


def split_images(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[;；]", value or "") if item.strip()]


def parse_stocks(*values: str) -> list[dict[str, str]]:
    seen: set[str] = set()
    stocks: list[dict[str, str]] = []
    for value in values:
        for match in STOCK_RE.finditer(value or ""):
            code = match.group("code")
            if code in seen:
                continue
            seen.add(code)
            stocks.append({"code": code, "name": match.group("name")})
    return stocks


def parse_time(*values: str) -> str:
    for value in values:
        match = TIME_RE.search(value or "")
        if match:
            return match.group("time")
    return ""


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def stock_url(code: str) -> str:
    return f"https://basic.10jqka.com.cn/{code}/"


def classify_post(text: str) -> tuple[str, str]:
    compact = re.sub(r"\s+", "", text or "")
    if SELL_RE.search(compact):
        return "sell", "卖出/减仓线索"
    if BUY_RE.search(compact) and not BUY_NEGATIVE_RE.search(compact):
        if "加仓" in compact:
            return "buy", "加仓线索"
        if "试错" in compact:
            return "buy", "试错买入线索"
        return "buy", "买入线索"
    if HOLD_RE.search(compact):
        return "hold", "持有线索"
    return "mention", "提及"


def safe_float(value: str) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def event_summary(text: str, limit: int = 92) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def market_id(code: str) -> str:
    if code.startswith(("6", "9")):
        return f"1.{code}"
    return f"0.{code}"


def request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(request, timeout=12, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_daily_closes(code: str, start: dt.date, end: dt.date) -> dict[str, float]:
    params = {
        "secid": market_id(code),
        "klt": "101",
        "fqt": "1",
        "beg": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?{urllib.parse.urlencode(params)}"
    payload = request_json(url)
    rows = (payload.get("data") or {}).get("klines") or []
    closes: dict[str, float] = {}
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 3:
            continue
        close = safe_float(parts[2])
        if close is None:
            continue
        closes[parts[0]] = close
    return closes


def price_on_or_after(closes: dict[str, float], date_text: str) -> tuple[str, float] | None:
    for key in sorted(closes):
        if key >= date_text:
            return key, closes[key]
    return None


def price_on_or_before(closes: dict[str, float], date_text: str) -> tuple[str, float] | None:
    matched = [(key, value) for key, value in closes.items() if key <= date_text]
    if not matched:
        return None
    return sorted(matched)[-1]


def collect_pick_events(source: str, end_date: dt.date) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted((SOURCES_DIR / source / "picks").glob("*.csv")):
        date_text = path.stem
        if parse_date(date_text) > end_date:
            continue
        for row in read_csv(path):
            code = row.get("code", "")
            name = row.get("name", "")
            if not code or not name:
                continue
            entry_low = safe_float(row.get("entry_low", ""))
            entry_high = safe_float(row.get("entry_high", ""))
            entry_mid = None
            if entry_low is not None and entry_high is not None:
                entry_mid = round((entry_low + entry_high) / 2, 3)
            events.append(
                {
                    "code": code,
                    "name": name,
                    "date": date_text,
                    "time": "",
                    "kind": "pick",
                    "action": "选股入池",
                    "summary": event_summary(row.get("logic") or row.get("raw_text") or row.get("pattern")),
                    "pattern": row.get("pattern", ""),
                    "status": row.get("status", ""),
                    "entry_mid": entry_mid,
                    "url": "",
                    "images": [],
                    "source_file": path.relative_to(ROOT).as_posix(),
                }
            )
    return events


def collect_holding_events(source: str, end_date: dt.date) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted((SOURCES_DIR / source / "holdings").glob("*.csv")):
        date_text = path.stem
        if parse_date(date_text) > end_date:
            continue
        for row in read_csv(path):
            code = row.get("code", "")
            name = row.get("name", "")
            if not code or not name:
                continue
            status = row.get("status", "")
            events.append(
                {
                    "code": code,
                    "name": name,
                    "date": row.get("date") or date_text,
                    "time": "",
                    "kind": "hold",
                    "action": f"持仓披露：{status}" if status else "持仓披露",
                    "summary": event_summary(row.get("plan") or row.get("raw_text") or row.get("note") or status),
                    "pattern": row.get("position_type", ""),
                    "status": status,
                    "entry_mid": safe_float(row.get("cost_price", "")),
                    "url": "",
                    "images": [],
                    "source_file": path.relative_to(ROOT).as_posix(),
                }
            )
    return events


def collect_post_events(source: str, end_date: dt.date) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted((SOURCES_DIR / source / "posts").glob("*.csv")):
        date_text = path.stem
        if parse_date(date_text) > end_date:
            continue
        for row in read_csv(path):
            text = " ".join([row.get("title", ""), row.get("summary", ""), row.get("raw_text", ""), row.get("mentioned_stocks", "")])
            stocks = parse_stocks(row.get("mentioned_stocks", ""), row.get("title", ""), row.get("summary", ""), row.get("raw_text", ""))
            if not stocks:
                continue
            kind, action = classify_post(text)
            time_text = parse_time(row.get("title", ""), row.get("raw_text", ""))
            for stock in stocks:
                events.append(
                    {
                        "code": stock["code"],
                        "name": stock["name"],
                        "date": date_text,
                        "time": time_text,
                        "kind": kind,
                        "action": action,
                        "summary": event_summary(row.get("summary") or row.get("raw_text") or row.get("title")),
                        "pattern": "",
                        "status": "",
                        "entry_mid": None,
                        "url": row.get("url", ""),
                        "images": split_images(row.get("image", "")),
                        "source_file": path.relative_to(ROOT).as_posix(),
                    }
                )
    return events


def event_sort_key(event: dict[str, Any]) -> tuple[str, str, str]:
    return (event.get("date", ""), event.get("time", ""), event.get("kind", ""))


def choose_evidence(events: list[dict[str, Any]], *kinds: str) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for event in events:
        if kinds and event.get("kind") not in kinds:
            continue
        for image in event.get("images", []):
            evidence.append(
                {
                    "date": event.get("date", ""),
                    "time": event.get("time", ""),
                    "action": event.get("action", ""),
                    "image": image,
                    "url": event.get("url", ""),
                }
            )
    return evidence[:6]


def build_track_from_events(code: str, name: str, events: list[dict[str, Any]], end_date: dt.date, mode: str, skip_price: bool) -> dict[str, Any]:
    events = sorted(events, key=event_sort_key)
    pick_events = [event for event in events if event["kind"] == "pick"]
    buy_events = [event for event in events if event["kind"] == "buy"]
    sell_events = [event for event in events if event["kind"] == "sell"]
    hold_events = [event for event in events if event["kind"] == "hold"]
    post_events = [event for event in events if event["kind"] in {"buy", "sell", "hold", "mention"}]

    first_event = events[0]
    first_pick = pick_events[0] if pick_events else None
    first_buy = buy_events[0] if buy_events else first_pick or first_event
    latest_event = events[-1]
    latest_sell = sell_events[-1] if sell_events else None
    end_event = latest_sell or latest_event
    end_date_text = min(end_event["date"], end_date.isoformat())

    price_basis = "待行情"
    buy_price = None
    end_price = None
    buy_price_date = ""
    end_price_date = ""
    return_pct = None

    if first_buy:
        if not skip_price:
            try:
                closes = fetch_daily_closes(code, parse_date(first_buy["date"]), end_date)
                buy_quote = price_on_or_after(closes, first_buy["date"])
                end_quote = price_on_or_before(closes, end_date_text)
                if buy_quote and end_quote:
                    buy_price_date, buy_price = buy_quote
                    end_price_date, end_price = end_quote
                    return_pct = round((end_price - buy_price) / buy_price * 100, 2) if buy_price else None
                    price_basis = "东方财富前复权日K收盘价估算"
            except Exception as error:
                if mode == "strict":
                    raise
                price_basis = f"待行情：{error}"

        if buy_price is None and first_buy.get("entry_mid"):
            buy_price = first_buy["entry_mid"]
            buy_price_date = first_buy["date"]
            price_basis = "按选股入场区间中位估算，待行情复核"

    if latest_sell:
        status = "已卖出/减仓"
    elif buy_events or hold_events:
        status = "持有/观察"
    elif pick_events:
        status = "观察中"
    else:
        status = "仅提及"

    return {
        "code": code,
        "name": name,
        "stock_url": stock_url(code),
        "first_seen_date": first_event["date"],
        "first_selected_date": first_pick["date"] if first_pick else "",
        "buy_date": first_buy["date"] if first_buy else "",
        "buy_action": first_buy["action"] if first_buy else "",
        "sell_date": latest_sell["date"] if latest_sell else "",
        "sell_action": latest_sell["action"] if latest_sell else "",
        "latest_date": latest_event["date"],
        "latest_action": latest_event["action"],
        "latest_summary": latest_event["summary"],
        "status": status,
        "return_pct": return_pct,
        "buy_price": buy_price,
        "buy_price_date": buy_price_date,
        "end_price": end_price,
        "end_price_date": end_price_date,
        "price_basis": price_basis,
        "event_count": len(events),
        "post_count": len(post_events),
        "screenshot_count": sum(len(event.get("images", [])) for event in events),
        "buy_evidence": choose_evidence(events, "buy") or choose_evidence(events, "pick", "hold", "mention"),
        "sell_evidence": choose_evidence(events, "sell"),
        "latest_evidence": choose_evidence(list(reversed(events))),
        "events": events[-8:],
    }


def build_source_tracks(source: str, end_date: dt.date, mode: str, skip_price: bool) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for event in [*collect_pick_events(source, end_date), *collect_holding_events(source, end_date), *collect_post_events(source, end_date)]:
        code = event["code"]
        grouped.setdefault(code, {"code": code, "name": event["name"], "events": []})
        grouped[code]["name"] = grouped[code].get("name") or event["name"]
        grouped[code]["events"].append(event)

    tracks = [
        build_track_from_events(code, item["name"], item["events"], end_date, mode, skip_price)
        for code, item in grouped.items()
    ]
    tracks.sort(key=lambda item: (item.get("latest_date", ""), item.get("return_pct") is not None, item.get("return_pct") or -999), reverse=True)

    returns = [item["return_pct"] for item in tracks if item.get("return_pct") is not None]
    return {
        "source": source,
        "generated_date": end_date.isoformat(),
        "stats": {
            "track_count": len(tracks),
            "active_count": sum(1 for item in tracks if item["status"] in {"持有/观察", "观察中"}),
            "sold_count": sum(1 for item in tracks if item["status"] == "已卖出/减仓"),
            "screenshot_count": sum(item.get("screenshot_count", 0) for item in tracks),
            "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
        },
        "tracks": tracks,
    }


def resolve_sources(args: argparse.Namespace) -> list[str]:
    if args.all:
        return sorted(path.name for path in SOURCES_DIR.iterdir() if path.is_dir())
    return args.source or ["yege"]


def write_outputs(payload: dict[str, Any]) -> None:
    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    ASTRO_OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    DATA_OUT.write_text(text, encoding="utf-8")
    ASTRO_OUT.write_text(text, encoding="utf-8")
    print(f"updated: {DATA_OUT.relative_to(ROOT)}")
    print(f"updated: {ASTRO_OUT.relative_to(ROOT)}")


def main() -> int:
    args = parse_args()
    try:
        end_date = dt.date.fromisoformat(args.date)
        source_payload = {
            source: build_source_tracks(source, end_date, args.mode, args.skip_price)
            for source in resolve_sources(args)
        }
        payload = {
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "date": end_date.isoformat(),
            "price_note": "收益为脚本根据公开日K估算；买卖截图与帖子原文仍需人工核对。",
            "sources": source_payload,
        }
        write_outputs(payload)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
