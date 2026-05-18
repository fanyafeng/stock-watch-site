#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SRC_DATA_DIR = ROOT / "src" / "data"
OUTPUT = DATA_DIR / "entry_check_index.json"
SRC_OUTPUT = SRC_DATA_DIR / "entry_check_index.json"
SOURCES = {
    "yege": "全能的野人",
    "lihongjuan": "李红娟",
}


class EntryDataError(Exception):
    pass


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.name == ".gitkeep":
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def split_tokens(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[;；、,，]\s*", value or "") if item.strip()]


def normalize_stock_key(code: str, name: str) -> str:
    return f"{code.strip()}::{name.strip()}"


def parse_stock_labels(value: str) -> list[dict[str, str]]:
    stocks: list[dict[str, str]] = []
    for item in split_tokens(value):
        match = re.search(r"(.+?)[(（](\d{6})[)）]", item)
        if match:
            stocks.append({"name": match.group(1).strip(), "code": match.group(2).strip()})
    return stocks


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("%", "")
    if not text or text in {"-", "待补充", "待复核"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_technical_snapshot(text: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "as_of": "",
        "current_price": None,
        "pct_change": None,
        "ma5": None,
        "ma10": None,
        "ma20": None,
        "volume_ratio": None,
        "technical_state": "",
        "source": "picks_logic",
    }
    if not text:
        return snapshot

    close_match = re.search(r"当前\s+(\d{4}-\d{2}-\d{2})\s+收盘\s*([0-9.]+)", text)
    if close_match:
        snapshot["as_of"] = close_match.group(1)
        snapshot["current_price"] = to_float(close_match.group(2))

    pct_match = re.search(r"涨跌幅\s*([+-]?[0-9.]+)%", text)
    if pct_match:
        snapshot["pct_change"] = to_float(pct_match.group(1))

    ma_match = re.search(r"MA5/10/20=([0-9.]+)/([0-9.]+)/([0-9.]+)", text)
    if ma_match:
        snapshot["ma5"] = to_float(ma_match.group(1))
        snapshot["ma10"] = to_float(ma_match.group(2))
        snapshot["ma20"] = to_float(ma_match.group(3))

    volume_match = re.search(r"量比近5日均量\s*([0-9.]+)", text)
    if volume_match:
        snapshot["volume_ratio"] = to_float(volume_match.group(1))

    state_match = re.search(r"状态：([^。；，\s]+)", text)
    if state_match:
        snapshot["technical_state"] = state_match.group(1).strip()

    return snapshot


def merge_market_snapshot(logic: str, price_update: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = parse_technical_snapshot(logic)
    if price_update:
        snapshot["source"] = "price_updates"
        for key in ["current_price", "pct_change", "ma5", "ma10", "ma20", "volume_ratio"]:
            if price_update.get(key) is not None:
                snapshot[key] = price_update[key]
        if price_update.get("technical_state"):
            snapshot["technical_state"] = price_update["technical_state"]
        if price_update.get("as_of"):
            snapshot["as_of"] = price_update["as_of"]
    return snapshot


def latest_dashboard_date() -> str:
    dashboard = DATA_DIR / "dashboard.json"
    if dashboard.exists():
        try:
            value = json.loads(dashboard.read_text(encoding="utf-8")).get("date")
            if value:
                return str(value)
        except Exception:
            pass
    dates = sorted(path.stem for path in (DATA_DIR / "dashboards").glob("*.json"))
    return dates[-1] if dates else dt.date.today().isoformat()


def collect_dates() -> list[str]:
    dates = set()
    for folder in [DATA_DIR / "dashboards", DATA_DIR / "daily"]:
        if folder.exists():
            dates.update(path.stem for path in folder.glob("*") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem))
    for source in SOURCES:
        source_dir = DATA_DIR / "sources" / source
        for sub in ["picks", "posts", "comments", "holdings"]:
            folder = source_dir / sub
            if folder.exists():
                dates.update(path.stem for path in folder.glob("*.csv") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem))
    return sorted(dates)


def load_stock_sector_map() -> dict[str, Any]:
    for path in [DATA_DIR / "stock_sector_map.json", SRC_DATA_DIR / "stock_sector_map.json"]:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


def load_dashboard(date_text: str) -> dict[str, Any]:
    path = DATA_DIR / "dashboards" / f"{date_text}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if (DATA_DIR / "dashboard.json").exists():
        data = json.loads((DATA_DIR / "dashboard.json").read_text(encoding="utf-8"))
        if data.get("date") == date_text:
            return data
    return {"date": date_text}


def source_display_name(source: str) -> str:
    return SOURCES.get(source, source)


def collect_picks(date_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source, source_name in SOURCES.items():
        path = DATA_DIR / "sources" / source / "picks" / f"{date_text}.csv"
        for row in read_csv_rows(path):
            code = row.get("code", "")
            name = row.get("name", "")
            if not code or not name:
                continue
            entry_low = row.get("entry_low") or row.get("entry_range", "").split("-")[0]
            entry_high = row.get("entry_high") or (row.get("entry_range", "").split("-")[-1] if row.get("entry_range") else "")
            rows.append(
                {
                    "date": row.get("date") or date_text,
                    "source": source,
                    "source_name": source_name,
                    "code": code,
                    "name": name,
                    "type": row.get("type", ""),
                    "pattern": row.get("pattern", ""),
                    "logic": row.get("logic", ""),
                    "entry_low": to_float(entry_low),
                    "entry_high": to_float(entry_high),
                    "stop_loss": to_float(row.get("stop_loss")),
                    "take_profit_1": to_float(row.get("take_profit_1")),
                    "take_profit_2": to_float(row.get("take_profit_2")),
                    "risk_reward_score": to_float(row.get("risk_reward_score")),
                    "risk_score": to_float(row.get("risk_score")),
                    "risk": row.get("risk", ""),
                    "status": row.get("status", ""),
                    "raw_text": row.get("raw_text", ""),
                    "note": row.get("note", ""),
                    "trend_score": to_float(row.get("trend_score")),
                    "breakout_score": to_float(row.get("breakout_score")),
                    "pullback_score": to_float(row.get("pullback_score")),
                    "volume_score": to_float(row.get("volume_score")),
                }
            )
    return rows


def collect_posts(date_text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source, source_name in SOURCES.items():
        path = DATA_DIR / "sources" / source / "posts" / f"{date_text}.csv"
        for row in read_csv_rows(path):
            stocks = parse_stock_labels(row.get("mentioned_stocks", ""))
            out.append(
                {
                    "source": source,
                    "source_name": source_name,
                    "date": row.get("date") or date_text,
                    "title": row.get("title", ""),
                    "url": row.get("url", ""),
                    "summary": row.get("summary", ""),
                    "mentioned_stocks": stocks,
                    "mentioned_sectors": split_tokens(row.get("mentioned_sectors", "")),
                    "note": row.get("note", ""),
                }
            )
    return out


def collect_comments(date_text: str) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    candidates = [DATA_DIR / "daily" / date_text / "comments.csv"]
    for source in SOURCES:
        candidates.append(DATA_DIR / "sources" / source / "comments" / f"{date_text}.csv")
    for path in candidates:
        for row in read_csv_rows(path):
            source = row.get("source", "")
            if source not in SOURCES:
                continue
            comments.append(
                {
                    "source": source,
                    "source_name": source_display_name(source),
                    "date": row.get("date") or date_text,
                    "comment_source": row.get("comment_source", ""),
                    "content": row.get("content", ""),
                    "mentioned_stocks": parse_stock_labels(row.get("mentioned_stocks", "")),
                    "mentioned_sectors": split_tokens(row.get("mentioned_sectors", "")),
                    "value_reason": row.get("value_reason", ""),
                    "include_status": row.get("include_status") or row.get("include_in_logic", ""),
                    "sentiment": row.get("sentiment", ""),
                    "value_score": to_float(row.get("value_score")),
                    "is_selected": str(row.get("is_selected", "")).lower() in {"true", "1", "是"},
                    "parent_title": row.get("parent_title", ""),
                    "parent_url": row.get("parent_url", ""),
                    "comment_time": row.get("comment_time") or row.get("time", ""),
                }
            )
    return comments


def collect_my_positions(date_text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for folder in ["positions", "operations"]:
        path = DATA_DIR / "my" / folder / f"{date_text}.csv"
        for row in read_csv_rows(path):
            code = row.get("code", "")
            name = row.get("name", "")
            if code or name:
                out.append(
                    {
                        "kind": folder,
                        "date": row.get("date") or date_text,
                        "code": code,
                        "name": name,
                        "status": row.get("status") or row.get("action") or "",
                        "plan": row.get("plan", ""),
                        "note": row.get("note", ""),
                    }
                )
    return out


def collect_price_updates(date_text: str) -> dict[str, dict[str, Any]]:
    prices: dict[str, dict[str, Any]] = {}
    for path in [
        DATA_DIR / "performance" / "price_updates" / f"{date_text}.csv",
        DATA_DIR / "price_updates" / f"{date_text}.csv",
    ]:
        for row in read_csv_rows(path):
            code = row.get("code", "")
            price = to_float(row.get("current_price") or row.get("price") or row.get("close"))
            if code and price is not None:
                prices[code] = {
                    "as_of": row.get("date") or date_text,
                    "current_price": price,
                    "pct_change": to_float(row.get("pct_change") or row.get("change_pct")),
                    "ma5": to_float(row.get("ma5")),
                    "ma10": to_float(row.get("ma10")),
                    "ma20": to_float(row.get("ma20")),
                    "volume_ratio": to_float(row.get("volume_ratio") or row.get("volume_ratio_5d")),
                    "technical_state": row.get("technical_state") or row.get("state") or "",
                }
    return prices


def market_summary(dashboard: dict[str, Any]) -> dict[str, Any]:
    overview = dashboard.get("overview") or {}
    market = dashboard.get("market") or {}
    main_sectors = overview.get("main_sectors") or []
    if isinstance(main_sectors, str):
        main_sectors = split_tokens(main_sectors)
    hot_sectors = list(main_sectors)
    for key in ["sector_rotation", "accumulation_direction"]:
        value = market.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    hot_sectors.append(str(item.get("sector") or item.get("name") or ""))
                else:
                    hot_sectors.append(str(item))
        elif isinstance(value, str):
            hot_sectors.extend(split_tokens(value))
    return {
        "market_status": overview.get("market_status", "待补充"),
        "main_sectors": [item for item in dict.fromkeys(hot_sectors) if item and item != "暂无数据"][:10],
        "risk_level": overview.get("risk_level", "中"),
        "operation_tone": overview.get("operation_tone", "控制仓位，只等买点"),
    }


def range_text(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "待补充"
    if low == high:
        return f"{low:g}"
    return f"{low:g} - {high:g}"


def risk_reward_text(entry_low: float | None, entry_high: float | None, stop: float | None, tp1: float | None) -> str:
    if entry_low is None or entry_high is None or stop is None or tp1 is None:
        return "待复核"
    entry = (entry_low + entry_high) / 2
    risk = max(entry - stop, 0)
    reward = max(tp1 - entry, 0)
    if risk <= 0 or reward <= 0:
        return "待复核"
    return f"1:{reward / risk:.2f}"


def risk_reward_value(text: str) -> float | None:
    match = re.search(r"1\s*[:：]\s*([0-9.]+)", text or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def stock_sectors(code: str, explicit: list[str], sector_map: dict[str, Any]) -> list[str]:
    mapped = sector_map.get(code, {}).get("sectors", []) if isinstance(sector_map.get(code), dict) else []
    return [item for item in dict.fromkeys([*explicit, *mapped]) if item]


def source_mentions_for(stock: dict[str, str], posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    code = stock["code"]
    out = []
    for post in posts:
        if any(item.get("code") == code for item in post["mentioned_stocks"]):
            out.append(
                {
                    "source": post["source"],
                    "source_name": post["source_name"],
                    "title": post["title"],
                    "summary": post["summary"],
                    "sectors": post["mentioned_sectors"],
                    "url": post["url"],
                }
            )
    return out[:8]


def comments_for(stock: dict[str, str], comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    code = stock["code"]
    out = []
    for comment in comments:
        if any(item.get("code") == code for item in comment["mentioned_stocks"]):
            out.append(
                {
                    "source": comment["source"],
                    "source_name": comment["source_name"],
                    "comment_source": comment["comment_source"],
                    "content": comment["content"],
                    "sectors": comment["mentioned_sectors"],
                    "value_reason": comment["value_reason"],
                    "include_status": comment["include_status"],
                    "sentiment": comment["sentiment"],
                    "value_score": comment["value_score"],
                    "url": comment["parent_url"],
                }
            )
    out.sort(key=lambda item: (item.get("value_score") or 0), reverse=True)
    return out[:12]


def position_for(stock: dict[str, str], positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in positions if item.get("code") == stock["code"] or item.get("name") == stock["name"]][:6]


def analyze_price_position(current_price: float | None, entry_low: float | None, entry_high: float | None, stop_loss: float | None) -> str:
    if current_price is None:
        return "当前价待补充"
    if stop_loss is not None and current_price < stop_loss:
        return "跌破止损位"
    if entry_low is not None and entry_high is not None:
        if entry_low <= current_price <= entry_high:
            return "价格进入入场区间"
        if current_price > entry_high * 1.03:
            return "明显高于入场上沿"
        if current_price < entry_low:
            return "低于入场区间，等待企稳"
    return "价格位置待复核"


def analyze_volume_signal(snapshot: dict[str, Any]) -> str:
    volume_ratio = snapshot.get("volume_ratio")
    pct_change = snapshot.get("pct_change")
    if volume_ratio is None:
        return "量能待补充"
    if pct_change is None:
        return f"量比 {volume_ratio:g}，方向待复核"
    if volume_ratio >= 1.2 and pct_change > 0:
        return f"量增价升，量比 {volume_ratio:g}"
    if volume_ratio >= 1.2 and pct_change < 0:
        return f"量增价跌，量比 {volume_ratio:g}"
    if volume_ratio < 0.8 and pct_change > 0:
        return f"量减价升，量比 {volume_ratio:g}"
    if volume_ratio < 0.8 and pct_change < 0:
        return f"缩量下跌，量比 {volume_ratio:g}"
    return f"量能平稳，量比 {volume_ratio:g}"


def analyze_ma_structure(snapshot: dict[str, Any]) -> str:
    current = snapshot.get("current_price")
    ma5 = snapshot.get("ma5")
    ma10 = snapshot.get("ma10")
    ma20 = snapshot.get("ma20")
    if current is None or ma5 is None or ma10 is None or ma20 is None:
        return "均线待补充"
    if current >= ma5 >= ma10 >= ma20:
        return "多头排列，趋势偏强"
    if current >= ma10 and ma5 >= ma20:
        return "站上关键均线"
    if current < ma20:
        return "跌破20日线"
    if current < ma10:
        return "跌破10日线"
    return "均线结构中性"


def pick_status(item: dict[str, Any], mode: str, current_price: float | None, market: dict[str, Any], stock_sectors_list: list[str], comments: list[dict[str, Any]], trend_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    entry_low = item.get("entry_low")
    entry_high = item.get("entry_high")
    stop_loss = item.get("stop_loss")
    tp1 = item.get("take_profit_1")
    trend_snapshot = trend_snapshot or {}
    risk_reward = risk_reward_text(entry_low, entry_high, stop_loss, tp1)
    rr_value = risk_reward_value(risk_reward)
    matched: list[str] = []
    missed: list[str] = []
    risk_points: list[str] = []

    pattern = item.get("pattern") or ""
    logic = item.get("logic") or ""
    risk = item.get("risk") or "中"
    source = item.get("source")
    technical_state = trend_snapshot.get("technical_state") or ""
    price_position = analyze_price_position(current_price, entry_low, entry_high, stop_loss)
    volume_signal = analyze_volume_signal(trend_snapshot)
    ma_structure = analyze_ma_structure(trend_snapshot)

    if source == mode:
        matched.append("来源命中")
    else:
        missed.append(f"当前模式为{source_display_name(mode)}，该票来自{item.get('source_name')}")

    if any(keyword in pattern + logic for keyword in ["回踩", "右侧转强", "底部", "强势延续", "中继"]):
        matched.append("技术形态可观察")
    else:
        missed.append("技术形态仍需补充确认")

    if entry_low is not None and entry_high is not None:
        matched.append("入场区间明确")
    else:
        missed.append("缺少明确入场区间")

    if stop_loss is not None:
        matched.append("止损位明确")
    else:
        missed.append("缺少止损位")

    if rr_value is not None and rr_value >= 1.5:
        matched.append("盈亏比合格")
    else:
        missed.append("盈亏比不足或待复核")

    if current_price is None:
        missed.append("当前价缺失，需补充价格后复核")
    elif stop_loss is not None and current_price < stop_loss:
        risk_points.append("当前价低于止损位")
    elif entry_high is not None and current_price > entry_high * 1.03:
        risk_points.append("当前价明显高于入场上沿")
    elif entry_low is not None and entry_high is not None and entry_low <= current_price <= entry_high:
        matched.append("当前价进入入场区间")

    if technical_state:
        if technical_state in {"强势延续", "回踩观察"}:
            matched.append(f"走势状态：{technical_state}")
        elif "追高" in technical_state or "破位" in technical_state:
            risk_points.append(f"走势状态：{technical_state}")

    if "多头排列" in ma_structure or "站上关键均线" in ma_structure:
        matched.append(ma_structure)
    elif "跌破" in ma_structure:
        risk_points.append(ma_structure)

    if volume_signal.startswith("量增价升"):
        matched.append("量增价升，动能配合")
    elif volume_signal.startswith("量增价跌"):
        risk_points.append("量增价跌，抛压需要复核")
    elif volume_signal.startswith("量减价升"):
        matched.append("量减价升，持有观察")
    elif "量能待补充" in volume_signal:
        missed.append("量能数据缺失")

    if risk == "高":
        risk_points.append("风险等级为高")
    if item.get("status") == "观察取消":
        risk_points.append("股票池状态为观察取消")
    if any("风险" in str(comment.get("value_reason", "")) or comment.get("sentiment") == "看空" for comment in comments):
        risk_points.append("评论区存在反向风险线索")

    hot = set(market.get("main_sectors") or [])
    if hot and set(stock_sectors_list) & hot:
        matched.append("板块与当日主线相关")
    elif stock_sectors_list:
        missed.append("板块与当日主线关联待确认")

    if mode == "lihongjuan":
        if item.get("type") in {"mid", "中长期"} or "趋势" in pattern + logic or "右侧" in pattern:
            matched.append("符合趋势/中长期观察")
        else:
            missed.append("一个月维度逻辑仍需补充")
        if "强势延续" in technical_state or "多头排列" in ma_structure:
            matched.append("趋势延续得到走势确认")
        if trend_snapshot.get("pct_change") is not None and trend_snapshot.get("pct_change") > 5 and entry_high is not None and current_price is not None and current_price > entry_high:
            risk_points.append("短期涨幅偏大，不追情绪高点")
    else:
        if any(word in pattern + logic for word in ["追高", "高位放量"]):
            risk_points.append("野哥模式下追高风险需降级")
        if "回踩观察" in technical_state and current_price is not None and trend_snapshot.get("ma10") is not None and current_price >= trend_snapshot["ma10"]:
            matched.append("回踩未破关键支撑")

    if "当前价低于止损位" in risk_points or "破位" in pattern or item.get("status") == "观察取消":
        status = "破位风险" if "当前价低于止损位" in risk_points or "破位" in pattern else "仅观察"
    elif risk_points and any("追高" in text or "高于入场" in text or "风险等级为高" in text or "量增价跌" in text for text in risk_points):
        status = "不建议追高"
    elif current_price is not None and entry_low is not None and entry_high is not None and entry_low <= current_price <= entry_high:
        status = "已到买点"
    elif len(matched) >= 4:
        status = "等待买点"
    elif len(matched) >= 2:
        status = "可关注"
    else:
        status = "数据不足"

    if status in {"已到买点", "等待买点", "可关注"} and risk != "高":
        suggest_entry = status == "已到买点"
    else:
        suggest_entry = False

    if mode == "lihongjuan":
        position = "轻仓趋势观察，不超过计划仓位 20%"
        cycle = "短期 7 天 / 中长期 30 天"
        today = "回踩确认后再判断，不追短期情绪高点。"
        wait = f"等待趋势延续、板块资金配合，并进入 {range_text(entry_low, entry_high)} 区间。"
        invalid = f"跌破风险位 {stop_loss:g} 或板块资金持续流出。" if stop_loss is not None else "跌破趋势支撑或原推荐逻辑失效。"
    else:
        position = "轻仓观察，不超过计划仓位 20%"
        cycle = "短期 7 天 / 波段 30 天"
        today = "不追高，只等买点。"
        wait = f"只在 {range_text(entry_low, entry_high)} 区间内观察，并确认量能承接。"
        invalid = f"跌破 {stop_loss:g} 无条件退出观察。" if stop_loss is not None else "缺少止损位时不做明确入场判断。"

    summary = build_summary(item, mode, status, stock_sectors_list, matched, missed, risk_points)
    return {
        "status": status,
        "suggest_entry": suggest_entry,
        "risk": risk,
        "summary": summary,
        "current_price": current_price,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_range": range_text(entry_low, entry_high),
        "stop_loss": stop_loss,
        "take_profit_1": tp1,
        "take_profit_2": item.get("take_profit_2"),
        "risk_reward": risk_reward,
        "position_advice": position,
        "tracking_cycle": cycle,
        "trend_snapshot": trend_snapshot,
        "price_position": price_position,
        "volume_signal": volume_signal,
        "ma_structure": ma_structure,
        "technical_state": technical_state or "待补充",
        "matched_rules": matched,
        "missed_rules": [*missed, *risk_points],
        "risk_points": risk_points,
        "action": {
            "today": today,
            "wait_condition": wait,
            "invalid_condition": invalid,
            "next_check": "次日继续观察量能、板块资金和来源人是否继续确认。",
        },
    }


def build_summary(item: dict[str, Any], mode: str, status: str, sectors: list[str], matched: list[str], missed: list[str], risk_points: list[str]) -> str:
    mode_name = "野哥模式" if mode == "yege" else "李红娟模式"
    sector_text = f"，关联板块：{'、'.join(sectors[:3])}" if sectors else ""
    if status == "破位风险":
        return f"{item['name']}在{mode_name}下出现破位或取消观察信号{sector_text}，当前不生成入场动作，先确认风险是否解除。"
    if status == "不建议追高":
        return f"{item['name']}有来源或形态线索{sector_text}，但存在追高/风险收益不足因素，当前只观察不追。"
    if status == "已到买点":
        return f"{item['name']}已进入预设入场区间，{mode_name}要求同步确认量能、板块和止损纪律。"
    if status in {"等待买点", "可关注"}:
        return f"{item['name']}命中{len(matched)}项条件{sector_text}，当前以{status}处理，等待价格、量能和板块继续确认。"
    return f"{item['name']}当前证据不足，已命中{len(matched)}项、缺失{len(missed)}项，需要补充价格、止损或大盘支持数据。"


def build_entries_for_date(date_text: str, sector_map: dict[str, Any]) -> dict[str, Any]:
    dashboard = load_dashboard(date_text)
    market = market_summary(dashboard)
    picks = collect_picks(date_text)
    posts = collect_posts(date_text)
    comments = collect_comments(date_text)
    positions = collect_my_positions(date_text)
    prices = collect_price_updates(date_text)

    explicit_sectors: dict[str, list[str]] = defaultdict(list)
    for item in posts:
        for stock in item["mentioned_stocks"]:
            explicit_sectors[stock["code"]].extend(item["mentioned_sectors"])
    for item in comments:
        for stock in item["mentioned_stocks"]:
            explicit_sectors[stock["code"]].extend(item["mentioned_sectors"])

    entries: list[dict[str, Any]] = []
    for pick in picks:
        stock = {"code": pick["code"], "name": pick["name"]}
        sectors = stock_sectors(pick["code"], list(dict.fromkeys(explicit_sectors[pick["code"]])), sector_map)
        stock_comments = comments_for(stock, comments)
        source_mentions = source_mentions_for(stock, posts)
        trend_snapshot = merge_market_snapshot(pick.get("logic", ""), prices.get(pick["code"]))
        current_price = trend_snapshot.get("current_price")
        mode_result = pick_status(pick, pick["source"], current_price, market, sectors, stock_comments, trend_snapshot)
        entries.append(
            {
                "date": date_text,
                "code": pick["code"],
                "name": pick["name"],
                "search_text": f"{pick['code']} {pick['name']} {pick['source_name']}",
                "mode": pick["source"],
                "mode_name": "野哥模式" if pick["source"] == "yege" else "李红娟模式",
                "source": pick["source"],
                "source_name": pick["source_name"],
                "type": "中长期" if pick.get("type") in {"mid", "中长期"} else "短期",
                "pattern": pick.get("pattern", ""),
                "logic": pick.get("logic", ""),
                "sectors": sectors,
                **mode_result,
                "evidence": {
                    "stock_pool": [pick],
                    "source_mentions": source_mentions,
                    "comments": stock_comments,
                    "market": [market],
                    "performance": [],
                    "my_positions": position_for(stock, positions),
                },
            }
        )

    known_keys = {normalize_stock_key(item["code"], item["name"]) for item in entries}
    for post in posts:
        for stock in post["mentioned_stocks"]:
            key = normalize_stock_key(stock["code"], stock["name"])
            if key in known_keys:
                continue
            sectors = stock_sectors(stock["code"], post["mentioned_sectors"], sector_map)
            stock_comments = comments_for(stock, comments)
            for mode in [post["source"]]:
                pseudo = {
                    "date": date_text,
                    "source": mode,
                    "source_name": source_display_name(mode),
                    "code": stock["code"],
                    "name": stock["name"],
                    "type": "",
                    "pattern": "来源提及",
                    "logic": post.get("summary", ""),
                    "entry_low": None,
                    "entry_high": None,
                    "stop_loss": None,
                    "take_profit_1": None,
                    "take_profit_2": None,
                    "risk": "中",
                    "status": "仅观察",
                }
                trend_snapshot = merge_market_snapshot(post.get("summary", ""), prices.get(stock["code"]))
                result = pick_status(pseudo, mode, trend_snapshot.get("current_price"), market, sectors, stock_comments, trend_snapshot)
                entries.append(
                    {
                        "date": date_text,
                        "code": stock["code"],
                        "name": stock["name"],
                        "search_text": f"{stock['code']} {stock['name']} {source_display_name(mode)}",
                        "mode": mode,
                        "mode_name": "野哥模式" if mode == "yege" else "李红娟模式",
                        "source": mode,
                        "source_name": source_display_name(mode),
                        "type": "仅观察",
                        "pattern": "来源提及",
                        "logic": post.get("summary", ""),
                        "sectors": sectors,
                        **result,
                        "evidence": {
                            "stock_pool": [],
                            "source_mentions": source_mentions_for(stock, posts),
                            "comments": stock_comments,
                            "market": [market],
                            "performance": [],
                            "my_positions": position_for(stock, positions),
                        },
                    }
                )
                known_keys.add(key)

    candidates = sorted(
        {
            (item["code"], item["name"]): {
                "code": item["code"],
                "name": item["name"],
                "sectors": item["sectors"],
            }
            for item in entries
        }.values(),
        key=lambda item: item["code"],
    )
    return {
        "date": date_text,
        "market": market,
        "entries": entries,
        "candidates": candidates,
    }


def main() -> int:
    try:
        sector_map = load_stock_sector_map()
        dates = collect_dates()
        if not dates:
            raise EntryDataError("未找到可用于入场判断的数据日期。")
        date_payloads = [build_entries_for_date(date_text, sector_map) for date_text in dates]
        payload = {
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "default_date": latest_dashboard_date(),
            "modes": [
                {"id": "yege", "name": "野哥模式", "source_name": "全能的野人"},
                {"id": "lihongjuan", "name": "李红娟模式", "source_name": "李红娟"},
            ],
            "dates": date_payloads,
        }
        write_json(OUTPUT, payload)
        write_json(SRC_OUTPUT, payload)
        print(f"updated: {OUTPUT.relative_to(ROOT)}")
        print(f"updated: {SRC_OUTPUT.relative_to(ROOT)}")
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
