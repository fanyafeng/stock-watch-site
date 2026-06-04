#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_ROOT = ROOT.parent / "yeren_signal_monitor"

PICK_FIELDS = [
    "source",
    "date",
    "code",
    "name",
    "type",
    "pattern",
    "logic",
    "entry_low",
    "entry_high",
    "stop_loss",
    "take_profit_1",
    "take_profit_2",
    "trend_score",
    "breakout_score",
    "pullback_score",
    "volume_score",
    "risk_reward_score",
    "risk_score",
    "status",
    "risk",
    "raw_text",
    "note",
]

HOLDING_FIELDS = [
    "source",
    "date",
    "code",
    "name",
    "position_type",
    "cost_price",
    "current_price",
    "position_ratio",
    "holding_days",
    "profit_loss_pct",
    "status",
    "plan",
    "stop_loss",
    "take_profit_1",
    "take_profit_2",
    "risk",
    "raw_text",
    "note",
]

POST_FIELDS = [
    "source",
    "date",
    "channel",
    "title",
    "url",
    "image",
    "summary",
    "mentioned_stocks",
    "mentioned_sectors",
    "raw_text",
    "note",
]

COMMENT_FIELDS = [
    "date",
    "source",
    "comment_source",
    "content",
    "mentioned_stocks",
    "mentioned_sectors",
    "value_reason",
    "include_in_logic",
    "note",
    "time",
    "platform",
    "parent_type",
    "parent_title",
    "commenter",
    "parent_id",
    "parent_url",
    "parent_cover",
    "comment_id",
    "comment_time",
    "include_status",
    "sentiment",
    "action_note",
    "value_score",
    "is_selected",
]

MARKET_FIELDS = ["section", "value", "note"]

TIMELINE_FIELDS = [
    "time",
    "category",
    "source",
    "title",
    "content",
    "related_stocks",
    "related_sectors",
    "note",
]

SOURCE_ALIASES = {
    "wangduoyu": ("王多于", "王多于-股之子"),
    "longge": ("龙哥", "阿龙闯大A"),
}

SOURCE_IDS = ("yege", "lihongjuan", "wangduoyu", "longge")

STOCK_SECTOR_HINTS = {
    "000547": ["商业航天", "军工电子"],
    "000592": ["林业", "福建自贸区"],
    "000720": ["电网设备", "电力"],
    "000783": ["证券"],
    "000967": ["环保设备"],
    "001209": ["服装家纺"],
    "002158": ["芯片设备", "通用设备"],
    "002210": ["物流"],
    "002217": ["消费电子", "光学光电子"],
    "002428": ["小金属", "半导体材料"],
    "002445": ["通用设备"],
    "002580": ["储能", "铅酸电池"],
    "002706": ["低压电器", "AIDC"],
    "002842": ["钨"],
    "003022": ["化工新材料"],
    "300136": ["消费电子", "射频"],
    "300390": ["锂电材料"],
    "300442": ["AIDC", "数据中心"],
    "600259": ["稀土"],
    "600330": ["商业航天", "光通信"],
    "600343": ["商业航天"],
    "600396": ["电力"],
    "600487": ["通信设备", "光通信"],
    "600545": ["工业母机"],
    "600589": ["AIDC", "算力"],
    "600821": ["电力"],
    "600879": ["商业航天", "军工电子"],
    "601016": ["电力", "风电"],
    "601179": ["电网设备"],
    "601778": ["电力", "光伏"],
    "601991": ["电力"],
    "603538": ["医药"],
    "603690": ["半导体设备"],
    "603906": ["锂电材料"],
    "605006": ["玻纤"],
    "605111": ["半导体"],
}


class ImportErrorMessage(Exception):
    pass


def date_text_to_compact(date_text: str) -> str:
    return dt.date.fromisoformat(date_text).strftime("%Y%m%d")


def compact_to_date_text(compact: str) -> str:
    return dt.datetime.strptime(compact, "%Y%m%d").date().isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_file(root: Path, pattern: str) -> Path | None:
    files = sorted(root.glob(pattern))
    return files[-1] if files else None


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    print(f"imported: {path} ({len(rows)} rows)")


def unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys([item for item in items if item]))


def clean_number(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return match.group(0) if match else ""


def stock_label(code: str, name: str) -> str:
    return f"{name}({code})" if code and name else name or code


def stock_labels_from_items(items: list[dict[str, Any]]) -> str:
    labels = []
    for item in items:
        code = str(item.get("code") or item.get("stock_code") or "")
        name = str(item.get("name") or item.get("stock_name") or "")
        if code or name:
            labels.append(stock_label(code, name))
    return ";".join(unique(labels))


def sectors_for_code(code: str) -> list[str]:
    return STOCK_SECTOR_HINTS.get(code, [])


def sectors_for_stock_labels(labels: str) -> str:
    sectors: list[str] = []
    for code in re.findall(r"\((\d{6})\)", labels):
        sectors.extend(sectors_for_code(code))
    return ";".join(unique(sectors))


def summarize(text: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def extract_time(value: str) -> str:
    match = re.search(r"(\d{1,2}:\d{2})", value or "")
    return match.group(1) if match else ""


def copy_attachments(backup_root: Path, date_text: str) -> dict[str, list[str]]:
    compact = date_text_to_compact(date_text)
    source_dir = backup_root / "state" / "attachments" / compact
    copied: dict[str, list[str]] = {}
    if not source_dir.exists():
        return copied
    target_dir = ROOT / "public" / "media" / date_text / "yege"
    target_dir.mkdir(parents=True, exist_ok=True)
    for image in sorted(source_dir.glob("*")):
        if not image.is_file():
            continue
        target = target_dir / image.name
        shutil.copy2(image, target)
        post_id = image.stem.split("_")[-1]
        copied.setdefault(post_id, []).append(f"/media/{date_text}/yege/{image.name}")
    print(f"copied media: {source_dir} -> {target_dir}")
    return copied


def load_yege_posts(backup_root: Path, date_text: str) -> list[dict[str, Any]]:
    compact = date_text_to_compact(date_text)
    daily = latest_file(backup_root / "daily_reports", f"{compact}_*_daily_summary.json")
    if daily and daily.exists():
        data = load_json(daily)
        posts = data.get("todaySignals") or []
        if posts:
            return posts
    raw = latest_file(backup_root / "outbox", f"{compact}_*_raw_posts.json")
    return load_json(raw) if raw else []


def normalize_yege_signal(signal: dict[str, Any]) -> dict[str, Any]:
    stocks = signal.get("stocks") or []
    if not stocks and signal.get("post"):
        stocks = signal["post"].get("stocks") or []
    return {
        "id": signal.get("postId") or signal.get("id") or "",
        "ctime": signal.get("ctime") or "",
        "text": signal.get("text") or signal.get("summary") or "",
        "url": signal.get("url") or "",
        "stats": signal.get("stats") or {},
        "stocks": stocks,
        "labels": signal.get("labels") or [],
        "reasons": signal.get("reasons") or [],
        "priority": signal.get("priority") or "",
    }


def import_yege(
    backup_root: Path,
    date_text: str,
    media_by_post: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    signals = [normalize_yege_signal(item) for item in load_yege_posts(backup_root, date_text)]
    today = [item for item in signals if item.get("ctime", "").startswith(date_text)]
    posts = []
    comments = []
    picks = []
    seen_pick_codes: set[str] = set()
    for item in today:
        stocks_label = stock_labels_from_items(item.get("stocks") or [])
        labels = unique([str(label) for label in item.get("labels", [])])
        sectors = unique([sector for code in re.findall(r"\((\d{6})\)", stocks_label) for sector in sectors_for_code(code)])
        post_id = str(item.get("id", ""))
        time_text = extract_time(item.get("ctime", ""))
        media = media_by_post.get(post_id, [])
        text = item.get("text", "")
        comment_count = item.get("stats", {}).get("comment", "")
        posts.append(
            {
                "source": "yege",
                "date": date_text,
                "channel": "同花顺帖子",
                "title": f"{date_text} {time_text} {stocks_label or '野哥同花顺动态'}".strip(),
                "url": item.get("url", ""),
                "image": ";".join(media),
                "summary": summarize(text, 240),
                "mentioned_stocks": stocks_label,
                "mentioned_sectors": ";".join(unique([*labels, *sectors])),
                "raw_text": text,
                "note": f"优先级 {item.get('priority', '')}; 点赞 {item.get('stats', {}).get('like', '')}; 评论 {comment_count}; 转发 {item.get('stats', {}).get('forward', '')}; 本地截图 {len(media)} 张",
            }
        )
        if text or stocks_label or media:
            include = "否" if any("退出" in label or "减仓" in label for label in labels) else "待确认"
            comments.append(
                {
                    "date": date_text,
                    "source": "yege",
                    "comment_source": f"同花顺评论备份 {time_text or '未标注时间'}",
                    "content": f"帖子评论量备份：{comment_count} 条。帖子摘要：{text}",
                    "mentioned_stocks": stocks_label,
                    "mentioned_sectors": ";".join(unique([*labels, *sectors])),
                    "value_reason": "；".join(item.get("reasons") or ["同花顺帖子备份，需结合截图和评论热度人工复核。"]),
                    "include_in_logic": include,
                    "note": f"post_id={post_id}; media={';'.join(media)}",
                }
            )
        for stock in item.get("stocks") or []:
            code = stock.get("code", "")
            name = stock.get("name", "")
            if not code or code in seen_pick_codes:
                continue
            seen_pick_codes.add(code)
            market = stock.get("market") or {}
            posture = market.get("posture", "")
            action_hint = stock.get("actionHint") or "只作观察，等待右侧确认。"
            risk_score = 8 if "追高" in posture else 4
            risk_reward = 5 if risk_score >= 7 else 7
            picks.append(make_pick_row("yege", date_text, code, name, "short" if len(picks) < 3 else "mid", posture or "技术形态观察", action_hint, market, risk_score, risk_reward, text))
    return posts, comments, picks[:8]


def make_pick_row(
    source: str,
    date_text: str,
    code: str,
    name: str,
    pick_type: str,
    pattern: str,
    logic: str,
    technicals: dict[str, Any],
    risk_score: int,
    risk_reward_score: int,
    raw_text: str,
) -> dict[str, Any]:
    close = float(technicals.get("close") or 0)
    ma10 = float(technicals.get("ma10") or 0)
    ma20 = float(technicals.get("ma20") or 0)
    entry_low = ma10 or close
    entry_high = close or ma10
    if entry_low and entry_high and entry_low > entry_high:
        entry_low, entry_high = entry_high, entry_low
    stop_loss = ma20 or (entry_low * 0.94 if entry_low else 0)
    tp1 = close * 1.06 if close else entry_high * 1.06
    tp2 = close * 1.10 if close else entry_high * 1.10
    labels = technicals.get("labels") or []
    trend = 8 if "均线多头" in labels or "右侧" in pattern or "强势" in pattern else 6
    breakout = 7 if "突破" in pattern or "强势" in pattern else 5
    pullback = 8 if "回踩" in pattern or "贴近" in " ".join(labels) else 6
    volume = 7 if float(technicals.get("volumeRatio5") or 0) >= 1 else 5
    return {
        "source": source,
        "date": date_text,
        "code": code,
        "name": name,
        "type": pick_type,
        "pattern": pattern or "技术形态观察",
        "logic": logic,
        "entry_low": f"{entry_low:.2f}" if entry_low else "",
        "entry_high": f"{entry_high:.2f}" if entry_high else "",
        "stop_loss": f"{stop_loss:.2f}" if stop_loss else "",
        "take_profit_1": f"{tp1:.2f}" if tp1 else "",
        "take_profit_2": f"{tp2:.2f}" if tp2 else "",
        "trend_score": trend,
        "breakout_score": breakout,
        "pullback_score": pullback,
        "volume_score": volume,
        "risk_reward_score": risk_reward_score,
        "risk_score": risk_score,
        "status": "等待买点" if risk_score < 7 else "观察取消",
        "risk": "高" if risk_score >= 7 else "中",
        "raw_text": raw_text,
        "note": "由真实备份信号转换，买点需人工复核。",
    }


def report_score(payload: dict[str, Any]) -> tuple[int, int, int, int, str]:
    yeren = payload.get("data_source", {}).get("yeren_douyin_video_signals") or {}
    return (
        len(payload.get("valid_comments") or []),
        len(payload.get("messages") or []),
        len(payload.get("short_term_picks") or []) + len(payload.get("long_term_picks") or []),
        len(yeren.get("videos") or []) + len(yeren.get("signals") or []),
        str(payload.get("generated_at") or ""),
    )


def latest_pick_report(backup_root: Path, compact: str, name: str) -> dict[str, Any] | None:
    date_text = compact_to_date_text(compact)
    candidates: list[tuple[tuple[int, int, int, int, str], dict[str, Any]]] = []
    for path in sorted((backup_root / "daily_reports").glob(f"*_{name}.json")):
        payload = load_json(path)
        if str(payload.get("date", "")).strip() != date_text:
            continue
        candidates.append((report_score(payload), payload))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    path = latest_file(backup_root / "daily_reports", f"{compact}_*_{name}.json")
    if not path:
        return None
    payload = load_json(path)
    return payload if str(payload.get("date", date_text)).strip() == date_text else None


def source_from_creator(creator_name: str = "", creator_id: str = "") -> str:
    normalized_id = creator_id.strip().lower()
    if normalized_id == "yeren" or "全能的野人" in creator_name or "野人" in creator_name:
        return "yege"
    if normalized_id == "wangduoyu" or "王多于" in creator_name:
        return "wangduoyu"
    if normalized_id in {"along", "longge"} or "阿龙" in creator_name or "龙哥" in creator_name or "龙" in creator_name:
        return "longge"
    return ""


def extract_video_id_from_url(url: str) -> str:
    match = re.search(r"/video/(\d+)", url or "")
    return match.group(1) if match else ""


def comment_signature(
    *,
    creator_name: str,
    video_url: str,
    text: str,
    create_time_text: str,
    source_type: str,
    parent_comment_text: str,
) -> tuple[str, str, str, str, str, str]:
    return (
        creator_name.strip(),
        video_url.strip(),
        re.sub(r"\s+", " ", text or "").strip(),
        (create_time_text or "").strip(),
        (source_type or "comment").strip().lower(),
        re.sub(r"\s+", " ", parent_comment_text or "").strip(),
    )


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def unique_pairs(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return list(dict.fromkeys([(left, right) for left, right in items if left]))


def douyin_sentiment_label(value: str) -> str:
    text = (value or "").strip().lower()
    if text in {"risk", "bearish", "cautious"}:
        return "谨慎"
    if text in {"bullish", "positive"}:
        return "看多"
    if text in {"negative"}:
        return "看空"
    return "中性"


def merge_include_status(statuses: list[str]) -> str:
    if "已纳入" in statuses:
        return "已纳入"
    if "待确认" in statuses:
        return "待确认"
    if "未纳入" in statuses:
        return "未纳入"
    if "无效评论" in statuses:
        return "无效评论"
    return "待确认"


def merge_sentiment(values: list[str]) -> str:
    if "看多" in values:
        return "看多"
    if "谨慎" in values:
        return "谨慎"
    if "看空" in values:
        return "看空"
    return values[0] if values else "中性"


def effective_comment_score(value_score: float, mentioned_stocks: list[str], include_status: str, value_reason: str) -> bool:
    return (
        value_score >= 6.5
        or bool(mentioned_stocks)
        or include_status in {"已纳入", "待确认"}
        or bool(value_reason.strip())
    )


def aggregate_include_status(aggregate: dict[str, Any], selected_codes: set[str]) -> str:
    code = str(aggregate.get("stock_code", "")).strip()
    if code in selected_codes:
        return "已纳入"
    if str(aggregate.get("sentiment", "")).lower() == "risk":
        return "未纳入"
    return "待确认"


def aggregate_value_score(aggregate: dict[str, Any], selected_codes: set[str]) -> float:
    code = str(aggregate.get("stock_code", "")).strip()
    mention_count = int(aggregate.get("mention_count") or 0)
    valid_count = int(aggregate.get("valid_comment_count") or 0)
    creator_count = int(aggregate.get("creator_count") or 0)
    base = 5.8 + min(mention_count, 9) * 0.22 + min(valid_count, 8) * 0.18 + min(creator_count, 2) * 0.25
    if aggregate.get("cross_creator"):
        base += 0.45
    if str(aggregate.get("sentiment", "")).lower() == "risk":
        base -= 0.55
    if code in selected_codes:
        base += 0.8
    return round(clamp(base, 4.6, 9.6), 1)


def annotation_reason_for_aggregate(
    aggregate: dict[str, Any],
    stock: str,
    include_status: str,
) -> str:
    mention_count = int(aggregate.get("mention_count") or 0)
    valid_count = int(aggregate.get("valid_comment_count") or 0)
    creator_count = int(aggregate.get("creator_count") or 0)
    sentiment = douyin_sentiment_label(str(aggregate.get("sentiment", "")))
    resonance = "跨来源共振" if aggregate.get("cross_creator") else "单视频线索"
    decision = "已进入推荐候选" if include_status == "已纳入" else ("保留观察" if include_status == "待确认" else "偏风险观察")
    return f"{stock} 被提及 {mention_count} 次，有效评论 {valid_count} 条，来源 {creator_count} 个，{resonance}，情绪 {sentiment}，当前判断：{decision}。"


def yeren_signal_annotations(report: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    yeren = report.get("data_source", {}).get("yeren_douyin_video_signals") or {}
    annotations: dict[tuple[str, str], dict[str, Any]] = {}
    for signal in yeren.get("signals", []) or []:
        signal_id = str(signal.get("id", "")).strip()
        video_id = str(signal.get("video_id", "")).strip()
        if not signal_id or not video_id:
            continue
        stock = stock_label(str(signal.get("stock_code", "")), str(signal.get("stock_name", "")))
        direction = str(signal.get("direction", "")).strip()
        notes = "；".join(str(item) for item in signal.get("strategy_notes", []) or [] if item)
        mentioned_stocks = stock
        mentioned_sectors = direction or "交易纪律"
        include_status = "待确认" if signal.get("sentiment") != "cautious" else "未纳入"
        sentiment = douyin_sentiment_label(str(signal.get("sentiment", "")))
        value_score = round(clamp(float(signal.get("confidence") or 6.6), 4.6, 9.2), 1)
        reason = str(signal.get("reason", "")).strip() or f"野哥抖音视频提到 {stock or direction or notes}，需结合盘面二次确认。"
        annotations[(video_id, signal_id)] = {
            "stock": stock,
            "sectors": mentioned_sectors,
            "value_reason": reason,
            "include_status": include_status,
            "sentiment": sentiment,
            "value_score": value_score,
            "is_selected": False,
            "direction": direction,
        }
    return annotations


def build_douyin_comment_annotations(report: dict[str, Any]) -> dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]]:
    selected_codes = {
        str(item.get("stock_code", "")).strip()
        for item in [*(report.get("short_term_picks", []) or []), *(report.get("long_term_picks", []) or [])]
        if str(item.get("stock_code", "")).strip()
    }
    annotations: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = {}

    for aggregate in report.get("comment_aggregates", []) or []:
        code = str(aggregate.get("stock_code", "")).strip()
        name = str(aggregate.get("stock_name", "")).strip()
        stock = stock_label(code, name)
        if not stock:
            continue
        sectors = sectors_for_code(code)
        include_status = aggregate_include_status(aggregate, selected_codes)
        sentiment = douyin_sentiment_label(str(aggregate.get("sentiment", "")))
        value_score = aggregate_value_score(aggregate, selected_codes)
        is_selected = include_status == "已纳入"
        reason = annotation_reason_for_aggregate(aggregate, stock, include_status)

        for sample in [*(aggregate.get("sample_comments", []) or []), *(aggregate.get("sample_reply_comments", []) or [])]:
            signature = comment_signature(
                creator_name=str(sample.get("creator_name", "")),
                video_url=str(sample.get("video_url", "")),
                text=str(sample.get("text", "")),
                create_time_text=str(sample.get("create_time_text", "")),
                source_type=str(sample.get("source_type", "comment")),
                parent_comment_text=str(sample.get("parent_comment_text", "")),
            )
            if not signature[2]:
                continue
            annotations.setdefault(signature, []).append(
                {
                    "stock": stock,
                    "sectors": sectors,
                    "value_reason": reason,
                    "include_status": include_status,
                    "sentiment": sentiment,
                    "value_score": value_score,
                    "is_selected": is_selected,
                }
            )

    return annotations


def load_douyin_raw_snapshot(backup_root: Path, compact: str, report: dict[str, Any]) -> dict[str, Any] | None:
    raw_path_text = str(report.get("data_source", {}).get("raw_comments_file", "")).strip()
    candidates: list[Path] = []
    if raw_path_text:
        candidates.append(Path(raw_path_text))
    candidates.extend(sorted((backup_root / "outbox").glob(f"{compact}_*_douyin_comments_raw.json"), reverse=True))
    for path in candidates:
        if path.exists():
            payload = load_json(path)
            if isinstance(payload, dict):
                return payload
    return None


def latest_yeren_video_signals(backup_root: Path, date_text: str) -> dict[str, Any] | None:
    candidates: list[tuple[tuple[int, int, str], dict[str, Any]]] = []
    for path in sorted((backup_root / "outbox").glob("*_yeren_douyin_video_signals.json")):
        payload = load_json(path)
        if str(payload.get("date", "")).strip() != date_text:
            continue
        score = (
            len(payload.get("videos") or []),
            len(payload.get("signals") or []),
            str(payload.get("generated_at") or ""),
        )
        candidates.append((score, payload))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def yeren_only_report(backup_root: Path, date_text: str) -> dict[str, Any] | None:
    yeren = latest_yeren_video_signals(backup_root, date_text)
    if not yeren:
        return None
    return {
        "date": date_text,
        "data_source": {
            "creators": [],
            "videos": [],
            "yeren_douyin_video_signals": yeren,
        },
        "comment_aggregates": [],
        "short_term_picks": [],
        "long_term_picks": [],
    }


def import_douyin(backup_root: Path, date_text: str) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    compact = date_text_to_compact(date_text)
    report = latest_pick_report(backup_root, compact, "douyin_comment_picks") or yeren_only_report(backup_root, date_text)
    if not report:
        return {source: [] for source in ("yege", "wangduoyu", "longge")}, []

    raw_snapshot = load_douyin_raw_snapshot(backup_root, compact, report) or {}
    annotations = build_douyin_comment_annotations(report)
    yeren_annotations = yeren_signal_annotations(report)
    comments: list[dict[str, Any]] = []
    video_rows: dict[str, list[dict[str, Any]]] = {}

    for raw_comment in raw_snapshot.get("comments", []) or []:
        source = source_from_creator(str(raw_comment.get("creator_name", "")), str(raw_comment.get("creator_id", "")))
        if not source:
            continue
        video_id = str(raw_comment.get("video_id", "")).strip() or extract_video_id_from_url(str(raw_comment.get("video_url", "")))
        video_url = str(raw_comment.get("video_url", "")).strip()
        create_time_text = str(raw_comment.get("create_time_text", "")).strip()
        signature = comment_signature(
            creator_name=str(raw_comment.get("creator_name", "")),
            video_url=video_url,
            text=str(raw_comment.get("text", "")),
            create_time_text=create_time_text,
            source_type=str(raw_comment.get("source_type", "comment")),
            parent_comment_text=str(raw_comment.get("parent_comment_text", "")),
        )
        matched = annotations.get(signature, [])
        yeren_signal = raw_comment.get("yeren_signal") or {}
        yeren_annotation = yeren_annotations.get((video_id, str(yeren_signal.get("id", "")).strip()))
        stocks = unique([item["stock"] for item in matched if item.get("stock")])
        sectors = unique([sector for item in matched for sector in item.get("sectors", [])])
        include_statuses = [str(item.get("include_status", "")) for item in matched if item.get("include_status")]
        sentiments = [str(item.get("sentiment", "")) for item in matched if item.get("sentiment")]
        value_reasons = unique([str(item.get("value_reason", "")) for item in matched if item.get("value_reason")])
        selected = any(bool(item.get("is_selected")) for item in matched)
        value_score = round(max([float(item.get("value_score") or 0) for item in matched] or [0.0]), 1)
        if yeren_annotation:
            if yeren_annotation.get("stock"):
                stocks = unique([*stocks, yeren_annotation["stock"]])
            if yeren_annotation.get("sectors"):
                sectors = unique([*sectors, *str(yeren_annotation["sectors"]).split("、")])
            include_statuses.append(str(yeren_annotation.get("include_status", "")))
            sentiments.append(str(yeren_annotation.get("sentiment", "")))
            value_reasons.append(str(yeren_annotation.get("value_reason", "")))
            selected = selected or bool(yeren_annotation.get("is_selected"))
            value_score = max(value_score, float(yeren_annotation.get("value_score") or 0))
        include_status = merge_include_status(include_statuses) if include_statuses else "未纳入"
        sentiment = merge_sentiment(sentiments) if sentiments else "中性"

        if not matched and (int(raw_comment.get("like_count") or 0) >= 8 or int(raw_comment.get("reply_count") or 0) >= 6):
            include_status = "待确认"
            sentiment = "中性"
            value_score = max(value_score, 6.2)
            value_reasons = ["评论热度较高，但暂未自动识别到明确股票线索，保留人工复核。"]

        row = {
            "date": date_text,
            "source": source,
            "comment_source": f"抖音评论 {extract_time(create_time_text) or create_time_text or '未标注时间'}",
            "content": str(raw_comment.get("text", "")).strip(),
            "mentioned_stocks": ";".join(stocks),
            "mentioned_sectors": ";".join(sectors),
            "value_reason": "；".join(value_reasons),
            "include_in_logic": {"已纳入": "是", "待确认": "待确认", "未纳入": "否", "无效评论": "否"}.get(include_status, "待确认"),
            "note": (
                f"video_id={video_id}; video_url={video_url}; creator={raw_comment.get('creator_name', '')}; "
                f"like={raw_comment.get('like_count', 0)}; reply={raw_comment.get('reply_count', 0)}; "
                f"source_type={raw_comment.get('source_type', 'comment')}; yeren_signal_id={yeren_signal.get('id', '')}; "
                f"parent_comment_text={raw_comment.get('parent_comment_text', '')}"
            ),
            "time": extract_time(str(raw_comment.get("video_title", ""))) or extract_time(create_time_text) or "--:--",
            "platform": "抖音视频" if yeren_annotation else "抖音评论",
            "parent_type": "video",
            "parent_title": str(raw_comment.get("video_title", "")).strip(),
            "commenter": str(raw_comment.get("user_nickname", "")).strip() or str(raw_comment.get("creator_name", "")).strip(),
            "parent_id": video_id,
            "parent_url": video_url,
            "parent_cover": "",
            "comment_id": str(raw_comment.get("id", "")).strip(),
            "comment_time": extract_time(create_time_text) or "--:--",
            "include_status": include_status,
            "sentiment": sentiment,
            "action_note": "野哥抖音视频方向/个股线索，自动映射到评论聚合池。" if yeren_annotation else "自动映射到抖音视频评论池。",
            "value_score": f"{value_score:.1f}" if value_score else "",
            "is_selected": "true" if selected else "false",
        }
        comments.append(row)
        if video_id:
            video_rows.setdefault(video_id, []).append(row)

    posts_by_source = {source: [] for source in ("yege", "wangduoyu", "longge")}
    raw_videos = raw_snapshot.get("videos", []) or report.get("data_source", {}).get("videos", []) or []
    yeren_payload = report.get("data_source", {}).get("yeren_douyin_video_signals") or {}
    raw_videos = [*raw_videos, *(yeren_payload.get("videos") or [])]
    videos_by_key = {}
    for video in raw_videos:
        if str(video.get("publish_date", "")).strip() != date_text:
            continue
        video_id = str(video.get("id", "")).strip() or extract_video_id_from_url(str(video.get("url", "")))
        if not video_id:
            continue
        videos_by_key[video_id] = video

    for creator in report.get("data_source", {}).get("creators", []) or []:
        source = source_from_creator(str(creator.get("name", "")), str(creator.get("id", "")))
        if not source:
            continue
        for video in creator.get("latest_scanned_videos", []) or []:
            if str(video.get("publish_date", "")).strip() != date_text:
                continue
            video_id = str(video.get("id", "")).strip() or extract_video_id_from_url(str(video.get("url", "")))
            if not video_id:
                continue
            videos_by_key.setdefault(video_id, video)

    for video_id, video in sorted(videos_by_key.items(), key=lambda item: str(item[1].get("publish_time", "")), reverse=True):
        source = source_from_creator(str(video.get("creator_name", "")), str(video.get("creator_id", "")))
        if not source:
            continue
        rows = video_rows.get(video_id, [])
        effective_rows = [row for row in rows if effective_comment_score(float(row.get("value_score") or 0), unique(row.get("mentioned_stocks", "").split(";")) if row.get("mentioned_stocks") else [], row.get("include_status", ""), row.get("value_reason", ""))]
        stock_counter: dict[str, int] = {}
        sector_counter: dict[str, int] = {}
        for row in rows:
            for stock in [item for item in row.get("mentioned_stocks", "").split(";") if item]:
                stock_counter[stock] = stock_counter.get(stock, 0) + 1
            for sector in [item for item in row.get("mentioned_sectors", "").split(";") if item]:
                sector_counter[sector] = sector_counter.get(sector, 0) + 1
        top_stocks = [stock for stock, _count in sorted(stock_counter.items(), key=lambda item: (-item[1], item[0]))[:6]]
        top_sectors = [sector for sector, _count in sorted(sector_counter.items(), key=lambda item: (-item[1], item[0]))[:6]]
        publish_time = str(video.get("publish_time", "")).strip()
        comment_total = len(rows) or int(video.get("comment_count") or 0)
        summary_bits = [f"视频评论抓取 {comment_total} 条"]
        if source == "yege":
            summary_bits = [f"野哥抖音视频信号 {comment_total} 条"]
        if effective_rows:
            summary_bits.append(f"有效线索 {len(effective_rows)} 条")
        if top_stocks:
            summary_bits.append(f"重点股票：{'、'.join(top_stocks[:4])}")
        posts_by_source[source].append(
            {
                "source": source,
                "date": date_text,
                "channel": "抖音视频",
                "title": f"{publish_time} {str(video.get('title', '')).strip()}".strip(),
                "url": str(video.get("url", "")).strip(),
                "image": "",
                "summary": "；".join(summary_bits) or f"视频标题：{str(video.get('title', '')).strip()}",
                "mentioned_stocks": ";".join(top_stocks),
                "mentioned_sectors": ";".join(top_sectors),
                "raw_text": str(video.get("title", "")).strip(),
                "note": (
                    f"video_id={video_id}; creator={video.get('creator_name', '')}; "
                    f"comment_count={video.get('comment_count', 0)}; digg={video.get('digg_count', 0)}; share={video.get('share_count', 0)}; "
                    f"来源备份 {compact}_*_douyin_comment_picks.json"
                ),
            }
        )

    return posts_by_source, comments


def pick_from_yeren_signal(date_text: str, signal: dict[str, Any]) -> dict[str, Any] | None:
    code = str(signal.get("stock_code", "")).strip()
    name = str(signal.get("stock_name", "")).strip()
    if not code:
        return None
    direction = str(signal.get("direction", "")).strip()
    sentiment = str(signal.get("sentiment_label") or signal.get("sentiment") or "").strip()
    notes = "；".join(str(item) for item in signal.get("strategy_notes", []) or [] if item)
    context = str(signal.get("context", "")).strip()
    confidence = float(signal.get("confidence") or 6.8)
    risk_score = 6 if "谨慎" in sentiment or str(signal.get("sentiment", "")).lower() == "cautious" else 4
    risk_reward = 8 if confidence >= 8 else 7
    logic = "；".join(unique([
        str(signal.get("reason", "")).strip(),
        f"方向：{direction}" if direction else "",
        f"观点：{sentiment}" if sentiment else "",
        notes,
    ])) or "全能的野人抖音视频出现个股线索，等待盘面确认。"
    technicals = {"labels": [direction] if direction else []}
    row = make_pick_row(
        "yege",
        date_text,
        code,
        name,
        "short",
        direction or "全能的野人抖音个股线索",
        logic,
        technicals,
        risk_score,
        risk_reward,
        context,
    )
    row["status"] = "等待买点"
    row["note"] = f"全能的野人抖音视频信号；video_id={signal.get('video_id', '')}; url={signal.get('video_url', '')}"
    return row


def import_yege_picks_from_douyin_report(backup_root: Path, date_text: str) -> list[dict[str, Any]]:
    compact = date_text_to_compact(date_text)
    report = latest_pick_report(backup_root, compact, "douyin_comment_picks") or yeren_only_report(backup_root, date_text)
    if not report:
        return []
    yeren = report.get("data_source", {}).get("yeren_douyin_video_signals") or {}
    rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for signal in yeren.get("signals", []) or []:
        row = pick_from_yeren_signal(date_text, signal)
        if not row:
            continue
        code = str(row.get("code", "")).strip()
        if code in seen_codes:
            continue
        seen_codes.add(code)
        rows.append(row)
    return rows[:8]


def pick_from_report_item(source: str, date_text: str, item: dict[str, Any], pick_type: str) -> dict[str, Any]:
    final_filter = item.get("final_action_filter") or {}
    technicals = final_filter.get("technicals") or {}
    if "current_price" in technicals:
        technicals["close"] = technicals.get("current_price")
    technicals.setdefault("ma10", clean_number(item.get("entry_plan")))
    technicals.setdefault("ma20", clean_number(item.get("stop_loss")))
    score = float(item.get("score") or 80)
    risk_notes = item.get("risk_notes") or ""
    risk_score = 7 if "追高" in item.get("rise_logic", "") or "风险" in risk_notes else 4
    risk_reward = 8 if score >= 85 else 7
    pattern = "中继回踩" if "回踩" in item.get("entry_plan", "") else "右侧转强"
    if "底部" in item.get("rise_logic", ""):
        pattern = "底部突破"
    return make_pick_row(
        source,
        date_text,
        item.get("stock_code", ""),
        item.get("stock_name", ""),
        pick_type,
        pattern,
        item.get("rise_logic") or item.get("reason") or "评论区真实线索，等待右侧确认。",
        technicals,
        risk_score,
        risk_reward,
        item.get("reason", ""),
    ) | {
        "entry_low": clean_number(item.get("entry_plan")) or make_pick_row(source, date_text, item.get("stock_code", ""), item.get("stock_name", ""), pick_type, pattern, "", technicals, risk_score, risk_reward, "").get("entry_low"),
        "entry_high": clean_number(technicals.get("close")) or make_pick_row(source, date_text, item.get("stock_code", ""), item.get("stock_name", ""), pick_type, pattern, "", technicals, risk_score, risk_reward, "").get("entry_high"),
        "stop_loss": clean_number(item.get("stop_loss")) or clean_number(item.get("stop_loss_text")) or clean_number(technicals.get("ma20")),
        "take_profit_1": clean_number(item.get("take_profit_1")) or clean_number(item.get("take_profit_text")),
        "take_profit_2": clean_number(item.get("take_profit_2")) or "",
        "note": "来自真实评论选股报告；不是随机推荐。",
    }


def import_picks_from_reports(backup_root: Path, date_text: str, source: str) -> list[dict[str, Any]]:
    compact = date_text_to_compact(date_text)
    rows: list[dict[str, Any]] = []
    if source in ("wangduoyu", "longge"):
        report = latest_pick_report(backup_root, compact, "douyin_comment_picks")
        if not report:
            return []
        creator_token = SOURCE_ALIASES[source][1]
        stock_sources: dict[str, set[str]] = {}
        for aggregate in report.get("comment_aggregates", []):
            code = aggregate.get("stock_code", "")
            creators = {sample.get("creator_name", "") for sample in aggregate.get("sample_comments", [])}
            creators.add((aggregate.get("top_comment") or {}).get("creator_name", ""))
            stock_sources[code] = creators
        for item in report.get("short_term_picks", []):
            creators = stock_sources.get(item.get("stock_code", ""), set())
            if creator_token in " ".join(creators) or not creators:
                rows.append(pick_from_report_item(source, date_text, item, "short"))
        for item in report.get("long_term_picks", []):
            creators = stock_sources.get(item.get("stock_code", ""), set())
            if creator_token in " ".join(creators) or not creators:
                rows.append(pick_from_report_item(source, date_text, item, "mid"))
        return rows[:8]

    if source == "lihongjuan":
        report = latest_pick_report(backup_root, compact, "lihongjuan_group_report") or latest_pick_report(backup_root, compact, "lihongjuan_group_morning_report")
        if not report:
            return []
        for item in report.get("short_term_picks", []):
            rows.append(pick_from_report_item(source, date_text, item, "short"))
        for item in report.get("long_term_picks", []):
            rows.append(pick_from_report_item(source, date_text, item, "mid"))
        return rows[:8]
    return []


def import_lihongjuan(backup_root: Path, date_text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    compact = date_text_to_compact(date_text)
    report = latest_pick_report(backup_root, compact, "lihongjuan_group_report") or latest_pick_report(backup_root, compact, "lihongjuan_group_morning_report")
    if not report:
        return [], []
    messages = [msg for msg in report.get("messages", []) if msg.get("date_text", date_text) == date_text or not msg.get("date_text")]
    valid_comments = report.get("valid_comments", [])
    mentioned = unique([stock_label(stock.get("code", ""), stock.get("name", "")) for item in valid_comments for stock in item.get("stocks", [])])
    sectors = sectors_for_stock_labels(";".join(mentioned))
    posts = []
    if messages or valid_comments:
        posts.append(
            {
                "source": "lihongjuan",
                "date": date_text,
                "channel": "图文/帖子",
                "title": f"李红娟 {date_text} 群聊评论备份",
                "url": "douyin://im/group",
                "image": "",
                "summary": summarize(" ".join(msg.get("text", "") for msg in messages[:5]), 260) or "当日群聊报告为空，保留来源占位。",
                "mentioned_stocks": ";".join(mentioned),
                "mentioned_sectors": sectors,
                "raw_text": " | ".join(f"{msg.get('time', '')} {msg.get('text', '')}" for msg in messages),
                "note": f"群聊原话 {len(messages)} 条；有效股票评论 {len(valid_comments)} 条；来源备份 {compact}_*_lihongjuan_group_report.json",
            }
        )
    comments = []
    for item in valid_comments:
        stocks = stock_labels_from_items(item.get("stocks", []))
        sentiment = item.get("sentiment", "")
        comments.append(
            {
                "date": date_text,
                "source": "lihongjuan",
                "comment_source": f"李红娟群聊 {item.get('create_time_text') or '未标注时间'}",
                "content": item.get("text", ""),
                "mentioned_stocks": stocks,
                "mentioned_sectors": sectors_for_stock_labels(stocks),
                "value_reason": f"群聊原话已识别股票线索：{stocks}；情绪={sentiment}。",
                "include_in_logic": "否" if sentiment == "risk" else "是",
                "note": f"creator={item.get('creator_name', '李红娟')}; source={item.get('video_title', '偶尔心情好发发群聊')}",
            }
        )
    return posts, comments


def import_market(backup_root: Path, date_text: str) -> list[dict[str, Any]]:
    compact = date_text_to_compact(date_text)
    path = latest_file(backup_root / "daily_reports", f"{compact}_*_market_review.json")
    if not path:
        return []
    payload = load_json(path)
    data = payload.get("data") or {}
    indexes = data.get("indexes") or []
    boards = data.get("boards") or {}
    gainers = boards.get("industryGainers") or []
    concepts = boards.get("conceptGainers") or boards.get("conceptGainersList") or []
    main = indexes[0] if indexes else {}
    top_boards = unique([item.get("name", "") for item in [*gainers[:4], *concepts[:3]]])
    up_count = sum(int(item.get("upCount") or 0) for item in indexes[:2])
    down_count = sum(int(item.get("downCount") or 0) for item in indexes[:2])
    risk_level = "中" if down_count else "低"
    operation_tone = "不追高，只等主线回踩承接；高位放量优先降风险。"
    index_status = "；".join(
        f"{item.get('name')}收{item.get('close')}，涨跌幅{item.get('pct')}%，形态{item.get('shape', '')}"
        for item in indexes[:3]
    )
    amount = sum(float(item.get("amount") or 0) for item in indexes[:2]) / 100000000
    rows = {
        "market_status": f"{main.get('shape', '震荡')}，上涨家数约{up_count}，下跌家数约{down_count}",
        "main_sectors": "、".join(top_boards[:5]) or "暂无数据",
        "risk_level": risk_level,
        "operation_tone": operation_tone,
        "index_status": index_status,
        "volume_change": f"沪深主要指数成交额合计约 {amount:.0f} 亿，需结合昨日继续复核。",
        "index_money_flow_series": "",
        "sector_rotation": "、".join(top_boards[:6]) or "暂无板块轮动数据",
        "accumulation_direction": "、".join([item.get("name", "") for item in gainers[:4]]) or "暂无数据",
        "sector_first_limit_up": "",
        "capital_preference": "主线优先看资金合力，弱分支不追高。",
        "sentiment_cycle": f"上涨/下跌约 {up_count}/{down_count}，情绪按结构性修复处理。",
        "risk_signal": "高位放量、偏离均线过大的方向只做风险观察。",
        "tomorrow_watch": "观察主线板块延续性、回踩承接和量能是否继续放大。",
    }
    result = []
    for key, value in rows.items():
        note = "需人工补充每个板块最先封板的股票，格式：板块=股票(代码);板块=股票(代码)" if key == "sector_first_limit_up" else f"导入自 {path.name}"
        result.append({"section": key, "value": value, "note": note})
    return result


def import_timeline(backup_root: Path, date_text: str, comments: list[dict[str, Any]], posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for post in posts[:8]:
        time_text = extract_time(post.get("title", "")) or "盘中"
        source = post.get("source", "")
        category = {
            "yege": "yege_post",
            "lihongjuan": "lihongjuan_post",
            "wangduoyu": "wangduoyu_video",
            "longge": "longge_video",
        }.get(source, "valuable_comment")
        rows.append(
            {
                "time": time_text,
                "category": category,
                "source": source,
                "title": post.get("title", ""),
                "content": summarize(post.get("summary", ""), 160),
                "related_stocks": post.get("mentioned_stocks", ""),
                "related_sectors": post.get("mentioned_sectors", ""),
                "note": post.get("url", ""),
            }
        )
    for comment in comments[:6]:
        rows.append(
            {
                "time": extract_time(comment.get("comment_source", "")) or "盘中",
                "category": "valuable_comment",
                "source": comment.get("source", ""),
                "title": comment.get("comment_source", ""),
                "content": summarize(comment.get("content", ""), 160),
                "related_stocks": comment.get("mentioned_stocks", ""),
                "related_sectors": comment.get("mentioned_sectors", ""),
                "note": comment.get("value_reason", ""),
            }
        )
    rows.append(
        {
            "time": "15:05",
            "category": "after_close",
            "source": "",
            "title": "盘后总结",
            "content": "以真实备份数据生成当日复盘，缺失模块保持暂无数据，不自动编造。",
            "related_stocks": "",
            "related_sectors": "",
            "note": "import_yeren_backup.py",
        }
    )
    return rows


def import_date(backup_root: Path, date_text: str) -> None:
    media_by_post = copy_attachments(backup_root, date_text)
    yege_posts, yege_comments, yege_picks = import_yege(backup_root, date_text, media_by_post)
    douyin_posts_by_source, douyin_comments = import_douyin(backup_root, date_text)
    lihongjuan_posts, lihongjuan_comments = import_lihongjuan(backup_root, date_text)

    posts_by_source: dict[str, list[dict[str, Any]]] = {source: [] for source in SOURCE_IDS}
    comments = [*yege_comments, *lihongjuan_comments, *douyin_comments]
    posts_by_source["yege"] = [*yege_posts, *douyin_posts_by_source.get("yege", [])]
    posts_by_source["lihongjuan"] = lihongjuan_posts
    posts_by_source["wangduoyu"] = douyin_posts_by_source.get("wangduoyu", [])
    posts_by_source["longge"] = douyin_posts_by_source.get("longge", [])

    picks_by_source: dict[str, list[dict[str, Any]]] = {source: [] for source in SOURCE_IDS}
    picks_by_source["yege"] = [*yege_picks, *import_yege_picks_from_douyin_report(backup_root, date_text)]
    for source in ("lihongjuan", "wangduoyu", "longge"):
        picks_by_source[source] = import_picks_from_reports(backup_root, date_text, source)

    # Keep empty holdings as real "not recorded" files. The report renderer will show a clear empty-state.
    for source in SOURCE_IDS:
        write_csv(ROOT / "data" / "sources" / source / "posts" / f"{date_text}.csv", POST_FIELDS, posts_by_source[source])
        write_csv(ROOT / "data" / "sources" / source / "picks" / f"{date_text}.csv", PICK_FIELDS, picks_by_source[source])
        write_csv(ROOT / "data" / "sources" / source / "holdings" / f"{date_text}.csv", HOLDING_FIELDS, [])

    daily_dir = ROOT / "data" / "daily" / date_text
    all_posts = [post for rows in posts_by_source.values() for post in rows]
    write_csv(daily_dir / "comments.csv", COMMENT_FIELDS, comments)
    write_csv(daily_dir / "market.csv", MARKET_FIELDS, import_market(backup_root, date_text))
    write_csv(daily_dir / "timeline.csv", TIMELINE_FIELDS, import_timeline(backup_root, date_text, comments, all_posts))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import real yeren_signal_monitor backups into stock-watch-site CSV files.")
    parser.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT), help="yeren_signal_monitor 目录")
    parser.add_argument("--date", action="append", help="导入日期 YYYY-MM-DD，可重复。默认导入 2026-05-11 到 2026-05-14")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    backup_root = Path(args.backup_root)
    if not backup_root.exists():
        raise ImportErrorMessage(f"未找到备份目录：{backup_root}")
    dates = args.date or ["2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14"]
    for date_text in dates:
        dt.date.fromisoformat(date_text)
        import_date(backup_root, date_text)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
