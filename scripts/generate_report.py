#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "data" / "source_config.json"
REPORT_INDEX_FILE = ROOT / "data" / "reports.json"
DASHBOARD_FILE = ROOT / "data" / "dashboard.json"
DASHBOARDS_DIR = ROOT / "data" / "dashboards"
TMP_DIR = ROOT / "build" / "tmp"

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
]

MARKET_SECTIONS = [
    ("market_status", "今日市场状态"),
    ("main_sectors", "今日主线板块"),
    ("risk_level", "今日风险等级"),
    ("operation_tone", "今日操作基调"),
    ("index_status", "指数状态"),
    ("volume_change", "成交量变化"),
    ("sector_rotation", "板块轮动"),
    ("accumulation_direction", "抢筹方向"),
    ("sector_first_limit_up", "板块首个涨停股"),
    ("capital_preference", "资金偏好"),
    ("sentiment_cycle", "情绪周期"),
    ("risk_signal", "风险信号"),
    ("tomorrow_watch", "明日观察方向"),
]

OVERVIEW_KEYS = ["market_status", "main_sectors", "risk_level", "operation_tone"]

TIMELINE_CATEGORIES = [
    ("market_node", "大盘关键节点"),
    ("sector_rotation", "板块轮动变化"),
    ("accumulation", "抢筹方向"),
    ("yege_post", "野哥同花顺发帖"),
    ("lihongjuan_post", "李红娟图文/帖子"),
    ("wangduoyu_video", "王多于抖音视频"),
    ("longge_video", "龙哥抖音视频"),
    ("valuable_comment", "有价值评论"),
    ("after_close", "盘后总结"),
]

SOURCE_POST_CATEGORY = {
    "yege": "yege_post",
    "lihongjuan": "lihongjuan_post",
    "wangduoyu": "wangduoyu_video",
    "longge": "longge_video",
}

SOURCE_POST_LABELS = {
    "yege": ("同花顺帖子", "图片/截图"),
    "lihongjuan": ("图文/帖子", "图片/截图"),
    "wangduoyu": ("抖音视频列表", "视频中提到的股票/板块"),
    "longge": ("抖音视频列表", "视频中提到的股票/板块"),
}

RISK_ORDER = {"低": 1, "中": 2, "高": 3}

BASE_DISCIPLINE_RULES = [
    "不追高，只等买点。",
    "买入前先看止损是否能接受。",
    "盈亏比不足不做。",
    "跌破止损无条件退出。",
    "多来源共同提到不等于可以买，只能提高观察优先级。",
]

POSITION_VOLUME_RULES = [
    ("低位无量", "低位无量要等，等错也要等。"),
    ("高位无量", "高位无量要拿，拿错了也要拿。"),
    ("低位放量", "低位放量要跟，跟错了也要跟。"),
    ("高位放量", "高位放量要跑，跑错了也要跑。"),
]

VOLUME_PRICE_RULES = [
    ("量增价升", "量增价升要买入。"),
    ("量增价减", "量增价减要卖出。"),
    ("量增价平", "量增价平要转阴。"),
    ("量平价升", "量平价升要加仓。"),
    ("量平价跌", "量平价跌出局。"),
    ("量减价升", "量减价升持有。"),
]

LOW_POSITION_WORDS = ("低位", "底部", "低吸", "底部突破")
HIGH_POSITION_WORDS = ("高位", "顶部", "高位滞涨", "放量滞涨")
QUIET_VOLUME_WORDS = ("无量", "缩量", "量缩")
EXPANDED_VOLUME_WORDS = ("放量", "量增", "爆量")


class ReportError(Exception):
    pass


def parse_date(value: str | None) -> dt.date:
    if value:
        return dt.date.fromisoformat(value)
    return dt.date.today()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_source_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        raise ReportError(f"未找到来源配置文件：{CONFIG_FILE}")
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def enabled_source_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in config.get("sources", []) if item.get("enabled", True)}


def resolve_sources(config: dict[str, Any], source: str | None, all_sources: bool) -> list[dict[str, Any]]:
    enabled = enabled_source_map(config)
    if source:
        if source not in enabled:
            raise ReportError(f"未知或未启用的来源：{source}")
        return [enabled[source]]
    ids = list(enabled.keys()) if all_sources else config.get("default_sources", [])
    resolved = [enabled[source_id] for source_id in ids if source_id in enabled]
    if not resolved:
        raise ReportError("没有可生成的 enabled 来源")
    return resolved


def read_csv_rows(path: Path, required_fields: list[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            return []
        missing = [field for field in required_fields if field not in reader.fieldnames]
        if missing:
            raise ReportError(f"{path} 缺少字段：{', '.join(missing)}")
        return [{field: (row.get(field) or "").strip() for field in required_fields} for row in reader]


def read_optional_rows(path: Path, required_fields: list[str], strict_extra: bool, label: str) -> list[dict[str, str]]:
    if not path.exists():
        if strict_extra:
            raise ReportError(f"未找到{label}数据：{rel(path)}")
        return []
    return [row for row in read_csv_rows(path, required_fields) if any(row.values())]


def load_picks(source_id: str, date_text: str) -> list[dict[str, str]]:
    path = ROOT / "data" / "sources" / source_id / "picks" / f"{date_text}.csv"
    if not path.exists():
        raise ReportError(f"未找到 {source_id} 在 {date_text} 的选股数据，请先创建 data/sources/{source_id}/picks/{date_text}.csv")
    rows = read_csv_rows(path, PICK_FIELDS)
    rows = [row for row in rows if any(row.values())]
    if not rows:
        raise ReportError(f"{source_id} 在 {date_text} 的选股数据为空，无法生成报告")
    return rows


def load_holdings(source_id: str, date_text: str) -> list[dict[str, str]]:
    path = ROOT / "data" / "sources" / source_id / "holdings" / f"{date_text}.csv"
    if not path.exists():
        raise ReportError(f"未找到 {source_id} 在 {date_text} 的持仓数据，请先创建 data/sources/{source_id}/holdings/{date_text}.csv")
    return [row for row in read_csv_rows(path, HOLDING_FIELDS) if any(row.values())]


def load_picks_for_daily(source_id: str, date_text: str, loose_source_data: bool) -> list[dict[str, str]]:
    if not loose_source_data:
        return load_picks(source_id, date_text)
    path = ROOT / "data" / "sources" / source_id / "picks" / f"{date_text}.csv"
    if not path.exists():
        print(f"loose: 未找到 {source_id} 在 {date_text} 的选股数据，来源板块将显示暂无数据")
        return []
    rows = [row for row in read_csv_rows(path, PICK_FIELDS) if any(row.values())]
    if not rows:
        print(f"loose: {source_id} 在 {date_text} 的选股数据为空，来源板块将显示暂无数据")
    return rows


def load_holdings_for_daily(source_id: str, date_text: str, loose_source_data: bool) -> list[dict[str, str]]:
    if not loose_source_data:
        return load_holdings(source_id, date_text)
    path = ROOT / "data" / "sources" / source_id / "holdings" / f"{date_text}.csv"
    if not path.exists():
        print(f"loose: 未找到 {source_id} 在 {date_text} 的持仓数据，来源板块将显示暂无数据")
        return []
    return [row for row in read_csv_rows(path, HOLDING_FIELDS) if any(row.values())]


def load_market_info(date_text: str, strict_extra: bool) -> dict[str, dict[str, str]]:
    path = ROOT / "data" / "daily" / date_text / "market.csv"
    rows = read_optional_rows(path, MARKET_FIELDS, strict_extra, "大盘信息")
    return {row["section"]: row for row in rows}


def load_timeline(date_text: str, strict_extra: bool) -> list[dict[str, str]]:
    path = ROOT / "data" / "daily" / date_text / "timeline.csv"
    return read_optional_rows(path, TIMELINE_FIELDS, strict_extra, "时间线")


def load_daily_comments(date_text: str, strict_extra: bool) -> list[dict[str, str]]:
    path = ROOT / "data" / "daily" / date_text / "comments.csv"
    return read_optional_rows(path, COMMENT_FIELDS, strict_extra, "有价值评论")


def load_source_posts(source_id: str, date_text: str, strict_extra: bool) -> list[dict[str, str]]:
    path = ROOT / "data" / "sources" / source_id / "posts" / f"{date_text}.csv"
    return read_optional_rows(path, POST_FIELDS, strict_extra, f"{source_id} 帖子/视频")


def to_float(row: dict[str, str], field: str) -> float:
    value = (row.get(field) or "").strip()
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        raise ReportError(f"{row.get('source', '')} {row.get('date', '')} {row.get('code', '')} 的 {field} 不是数字：{value}")


def score_candidates(rows: list[dict[str, str]], source_name: str | None = None) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        item: dict[str, Any] = dict(row)
        if source_name:
            item["source_name"] = source_name
        item["trend_score"] = to_float(row, "trend_score")
        item["breakout_score"] = to_float(row, "breakout_score")
        item["pullback_score"] = to_float(row, "pullback_score")
        item["volume_score"] = to_float(row, "volume_score")
        item["risk_reward_score"] = to_float(row, "risk_reward_score")
        item["risk_score"] = to_float(row, "risk_score")
        item["total_score"] = (
            item["trend_score"]
            + item["breakout_score"]
            + item["pullback_score"]
            + item["volume_score"]
            + item["risk_reward_score"]
            - item["risk_score"]
        )
        scored.append(item)
    return scored


def filter_reason(item: dict[str, Any]) -> list[str]:
    reasons = []
    if not item.get("entry_low") or not item.get("entry_high"):
        reasons.append("缺少明确入场区间")
    if not item.get("stop_loss"):
        reasons.append("缺少止损位")
    if not item.get("take_profit_1"):
        reasons.append("缺少第一止盈位")
    if item["risk_reward_score"] < 6:
        reasons.append("盈亏比不足")
    if item["risk_score"] >= 7:
        reasons.append("风险扣分过高")
    if item.get("status") == "观察取消":
        reasons.append("状态为观察取消")
    if item["trend_score"] < 4:
        reasons.append("趋势未确认")
    if "放量滞涨" in item.get("pattern", ""):
        reasons.append("放量滞涨")
    return reasons


def filter_candidates(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted = []
    rejected = []
    for item in rows:
        reasons = filter_reason(item)
        if reasons:
            rejected.append({**item, "excluded_reason": "；".join(reasons)})
        else:
            accepted.append(item)
    return accepted, rejected


def pick_top_candidates(rows: list[dict[str, Any]], candidate_type: str, limit: int = 3) -> list[dict[str, Any]]:
    typed = [row for row in rows if row.get("type") == candidate_type]
    return sorted(typed, key=lambda row: row["total_score"], reverse=True)[:limit]


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return '<p class="empty-note">暂无数据。</p>'
    head = "".join(f"<th>{esc(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def empty_note(text: str) -> str:
    return f'<p class="empty-note">{esc(text)}</p>'


def type_label(value: str) -> str:
    return {"short": "短期", "mid": "中长期"}.get(value, value or "未标注")


def risk_reward_text(item: dict[str, Any]) -> str:
    score = item.get("risk_reward_score", 0)
    total = item.get("aggregate_score", item.get("total_score", 0))
    return f"盈亏比评分 {score:.1f}，综合分 {total:.1f}，以止损位 {item.get('stop_loss')} 为纪律线。"


def signal_text(item: dict[str, Any]) -> str:
    fields = ("pattern", "logic", "raw_text", "note", "status")
    return " ".join(str(item.get(field, "")) for field in fields)


def has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def volume_price_rule_for_item(item: dict[str, Any]) -> str:
    text = signal_text(item)
    for trigger, rule in VOLUME_PRICE_RULES:
        if trigger in text:
            return rule

    low_position = has_any(text, LOW_POSITION_WORDS)
    high_position = has_any(text, HIGH_POSITION_WORDS)
    quiet_volume = has_any(text, QUIET_VOLUME_WORDS)
    expanded_volume = has_any(text, EXPANDED_VOLUME_WORDS)

    if low_position and quiet_volume:
        return "低位无量要等，等错也要等。"
    if high_position and quiet_volume:
        return "高位无量要拿，拿错了也要拿。"
    if low_position and expanded_volume:
        return "低位放量要跟，跟错了也要跟。"
    if high_position and expanded_volume:
        return "高位放量要跑，跑错了也要跑。"
    return "未标注明确量价组合，需盘中复核量能与价格方向后再执行。"


def render_rule_list(rules: list[str]) -> str:
    return "<ul class=\"discipline-list\">" + "".join(f"<li>{esc(rule)}</li>" for rule in rules) + "</ul>"


def render_trading_discipline_block() -> str:
    volume_rules = [rule for _, rule in [*POSITION_VOLUME_RULES, *VOLUME_PRICE_RULES]]
    return f"""
<h3>基础交易纪律</h3>
{render_rule_list(BASE_DISCIPLINE_RULES)}
<h3>量价交易纪律</h3>
{render_rule_list(volume_rules)}
<p class="empty-note">CSV 的 pattern、logic、raw_text、note 中可写入“低位无量 / 高位放量 / 量增价升”等关键词，系统会在入选理由中自动提示对应量价动作。</p>
<p class="empty-note">本文仅为个人复盘与技术形态观察，不构成任何投资建议。</p>
""".strip()


def selected_reason(item: dict[str, Any]) -> str:
    parts = [
        f"趋势 {item['trend_score']:.1f}",
        f"突破 {item['breakout_score']:.1f}",
        f"回踩 {item['pullback_score']:.1f}",
        f"量能 {item['volume_score']:.1f}",
        f"盈亏比 {item['risk_reward_score']:.1f}",
    ]
    source_text = item.get("source_names") or item.get("source_name") or item.get("source")
    agreement = f"来源：{source_text}。"
    logic = item.get("logic") or "请结合入场区间、止损位和量价关系复核。"
    return f"{agreement}{logic} 核心评分：{' / '.join(parts)}。量价纪律：{volume_price_rule_for_item(item)}"


def render_holdings_section(holdings: list[dict[str, str]]) -> str:
    if not holdings:
        return empty_note("今日未记录公开持仓或持仓数据为空")
    rows = [
        [
            item["code"],
            item["name"],
            item["position_type"],
            item["cost_price"],
            item["current_price"],
            item["position_ratio"],
            item["holding_days"],
            item["profit_loss_pct"],
            item["status"],
            item["plan"],
            item["stop_loss"],
            f"{item['take_profit_1']} / {item['take_profit_2']}",
            item["risk"],
        ]
        for item in holdings
    ]
    return table(
        ["股票代码", "股票名称", "仓位类型", "成本价", "当前价", "仓位比例", "持仓天数", "浮盈浮亏", "当前状态", "后续计划", "止损位", "止盈位", "风险等级"],
        rows,
    )


def render_pick_table(rows: list[dict[str, Any]], include_sources: bool = False) -> str:
    headers = ["股票代码", "股票名称", "类型", "技术形态", "入场区间", "止损位", "第一止盈位", "第二止盈位", "盈亏比说明", "量价纪律", "风险等级", "当前状态", "入选理由"]
    if include_sources:
        headers.insert(2, "来源人")
    table_rows = []
    for item in rows:
        row = [
            item["code"],
            item["name"],
            type_label(item.get("type", "")),
            item["pattern"],
            f"{item['entry_low']} - {item['entry_high']}",
            item["stop_loss"],
            item["take_profit_1"],
            item["take_profit_2"],
            risk_reward_text(item),
            volume_price_rule_for_item(item),
            item["risk"],
            item["status"],
            selected_reason(item),
        ]
        if include_sources:
            row.insert(2, item.get("source_names") or item.get("source_name") or item.get("source"))
        table_rows.append(row)
    return table(headers, table_rows)


def render_source_recommendations(rows: list[dict[str, Any]]) -> str:
    selected = sorted(rows, key=lambda row: row["total_score"], reverse=True)
    if not selected:
        return empty_note("暂无符合筛选规则的今日推荐，原始候选会在摘要或剔除观察中展示。")
    return render_pick_table(selected)


def render_excluded_table(rows: list[dict[str, Any]]) -> str:
    return table(
        ["来源人", "股票代码", "股票名称", "技术形态", "风险等级", "当前状态", "剔除原因"],
        [
            [
                item.get("source_name") or item.get("source"),
                item["code"],
                item["name"],
                item["pattern"],
                item["risk"],
                item["status"],
                item["excluded_reason"],
            ]
            for item in rows
        ],
    )


def render_raw_summary(picks: list[dict[str, Any]]) -> str:
    if not picks:
        return empty_note("暂无原始选股摘要。")
    items = []
    for item in picks:
        detail = item.get("raw_text") or item.get("note") or item.get("logic")
        items.append(f"<li><strong>{esc(item['name'])}({esc(item['code'])})</strong>：{esc(detail)}</li>")
    return "<ul class=\"summary-list\">" + "".join(items) + "</ul>"


def market_value(market: dict[str, dict[str, str]], section: str) -> str:
    row = market.get(section)
    if not row or not row.get("value"):
        return "暂无数据"
    if row.get("note"):
        return f"{row['value']}（{row['note']}）"
    return row["value"]


def plain_market_value(market: dict[str, dict[str, str]], section: str, fallback: str = "暂无数据") -> str:
    row = market.get(section)
    if not row or not row.get("value"):
        return fallback
    return row["value"]


def render_overview_section(date_text: str, updated_at: str, market: dict[str, dict[str, str]]) -> str:
    cards = [
        ("日期", date_text),
        ("更新时间", updated_at),
        *[(label, market_value(market, key)) for key, label in MARKET_SECTIONS if key in OVERVIEW_KEYS],
    ]
    card_html = "".join(
        f'<div class="metric-card"><span>{esc(label)}</span><strong>{esc(value)}</strong></div>'
        for label, value in cards
    )
    return f"""
<section class="section-card" id="overview">
  <div class="section-title">
    <p>Overview</p>
    <h2>今日总览</h2>
  </div>
  <div class="metric-grid">{card_html}</div>
</section>
""".strip()


def render_market_section(market: dict[str, dict[str, str]], date_text: str) -> str:
    path = ROOT / "data" / "daily" / date_text / "market.csv"
    rows = [[label, market_value(market, key)] for key, label in MARKET_SECTIONS[4:]]
    note = ""
    if not market:
        note = empty_note(f"未提供大盘信息 CSV，可补充 {rel(path)}；当前仅显示字段结构。")
    return f"""
<section class="section-card" id="market">
  <div class="section-title">
    <p>Market Map</p>
    <h2>大盘信息</h2>
  </div>
  {note}
  {table(["模块", "内容"], rows)}
</section>
""".strip()


def source_post_to_timeline(post: dict[str, str]) -> dict[str, str]:
    source_id = post.get("source", "")
    return {
        "time": "",
        "category": SOURCE_POST_CATEGORY.get(source_id, "source_post"),
        "source": source_id,
        "title": post.get("title") or post.get("channel") or "来源内容",
        "content": post.get("summary") or post.get("raw_text") or post.get("note"),
        "related_stocks": post.get("mentioned_stocks", ""),
        "related_sectors": post.get("mentioned_sectors", ""),
        "note": post.get("url", ""),
    }


def comment_to_timeline(comment: dict[str, str]) -> dict[str, str]:
    return {
        "time": "",
        "category": "valuable_comment",
        "source": comment.get("source", ""),
        "title": comment.get("comment_source") or "有价值评论",
        "content": comment.get("content", ""),
        "related_stocks": comment.get("mentioned_stocks", ""),
        "related_sectors": comment.get("mentioned_sectors", ""),
        "note": comment.get("value_reason", ""),
    }


def render_timeline_section(
    timeline: list[dict[str, str]],
    all_posts: list[dict[str, str]],
    comments: list[dict[str, str]],
    source_lookup: dict[str, str],
    date_text: str,
) -> str:
    items = [*timeline, *[source_post_to_timeline(post) for post in all_posts], *[comment_to_timeline(comment) for comment in comments]]
    timeline_path = ROOT / "data" / "daily" / date_text / "timeline.csv"
    groups = []
    for category, label in TIMELINE_CATEGORIES:
        rows = [item for item in items if item.get("category") == category]
        if rows:
            body = "".join(
                f"""
<li class="timeline-item">
  <span>{esc(item.get('time') or '未标注时间')}</span>
  <strong>{esc(item.get('title'))}</strong>
  <p>{esc(item.get('content'))}</p>
  <small>{esc(source_lookup.get(item.get('source', ''), item.get('source', '')))} {esc(item.get('related_stocks'))} {esc(item.get('related_sectors'))} {esc(item.get('note'))}</small>
</li>
""".strip()
                for item in rows
            )
            content = f'<ol class="timeline-list">{body}</ol>'
        else:
            content = empty_note(f"暂无数据，可在 {rel(timeline_path)} 中补充 category={category}。")
        groups.append(f'<div class="timeline-group"><h3>{esc(label)}</h3>{content}</div>')
    return f"""
<section class="section-card" id="timeline">
  <div class="section-title">
    <p>Intraday Timeline</p>
    <h2>今日时间线</h2>
  </div>
  <div class="timeline-grid">{''.join(groups)}</div>
</section>
""".strip()


def render_posts_table(posts: list[dict[str, str]], source_id: str, date_text: str) -> str:
    if not posts:
        path = ROOT / "data" / "sources" / source_id / "posts" / f"{date_text}.csv"
        return empty_note(f"暂无帖子/视频数据，可补充 {rel(path)}。")
    return table(
        ["渠道", "标题", "链接", "摘要", "提到股票", "提到板块", "备注"],
        [
            [
                post["channel"],
                post["title"],
                post["url"],
                post["summary"] or post["raw_text"],
                post["mentioned_stocks"],
                post["mentioned_sectors"],
                post["note"],
            ]
            for post in posts
        ],
    )


def render_media_list(posts: list[dict[str, str]]) -> str:
    media = [post for post in posts if post.get("image")]
    if not media:
        return empty_note("暂无图片、截图或视频封面记录。")
    items = [
        f'<li><strong>{esc(post.get("title") or post.get("channel"))}</strong>：{esc(post["image"])}</li>'
        for post in media
    ]
    return "<ul class=\"summary-list\">" + "".join(items) + "</ul>"


def render_video_mentions(posts: list[dict[str, str]]) -> str:
    rows = [
        [post["title"], post["mentioned_stocks"], post["mentioned_sectors"], post["summary"] or post["note"]]
        for post in posts
        if post.get("mentioned_stocks") or post.get("mentioned_sectors")
    ]
    if not rows:
        return empty_note("暂无视频提到的股票或板块记录。")
    return table(["视频/内容", "提到的股票", "提到的板块", "摘要"], rows)


def render_source_comments(comments: list[dict[str, str]]) -> str:
    if not comments:
        return empty_note("暂无有价值评论记录。")
    return table(
        ["评论来源", "评论内容", "提到股票", "提到板块", "为什么有价值", "纳入推荐逻辑"],
        [
            [
                comment["comment_source"],
                comment["content"],
                comment["mentioned_stocks"],
                comment["mentioned_sectors"],
                comment["value_reason"],
                comment["include_in_logic"],
            ]
            for comment in comments
        ],
    )


def render_source_panel(source_data: dict[str, Any], date_text: str) -> str:
    source = source_data["source"]
    source_id = source["id"]
    post_label, media_label = SOURCE_POST_LABELS.get(source_id, ("帖子/视频", "图片/截图"))
    posts = source_data["posts"]
    comments = source_data["comments"]
    return f"""
<section class="source-panel" id="source-{esc(source_id)}">
  <div class="source-panel__head">
    <span>{esc(source_id)}</span>
    <h3>{esc(source["name"])}</h3>
  </div>
  <div class="source-detail-grid">
    <div class="source-detail"><h4>{esc(post_label)}</h4>{render_posts_table(posts, source_id, date_text)}</div>
    <div class="source-detail"><h4>{esc(media_label)}</h4>{render_video_mentions(posts) if source_id in ("wangduoyu", "longge") else render_media_list(posts)}</div>
    <div class="source-detail"><h4>原文摘要</h4>{render_raw_summary(source_data["scored"])}</div>
    <div class="source-detail"><h4>今日推荐</h4>{render_source_recommendations(source_data["accepted"])}</div>
    <div class="source-detail source-detail--wide"><h4>个人持仓</h4>{render_holdings_section(source_data["holdings"])}</div>
    <div class="source-detail source-detail--wide"><h4>有价值评论</h4>{render_source_comments(comments)}</div>
  </div>
</section>
""".strip()


def render_sources_section(source_sections: list[dict[str, Any]], date_text: str) -> str:
    panels = "".join(render_source_panel(item, date_text) for item in source_sections)
    return f"""
<section class="section-card" id="sources">
  <div class="section-title">
    <p>Source Boards</p>
    <h2>来源人板块</h2>
  </div>
  <div class="source-stack">{panels}</div>
</section>
""".strip()


def worst_risk(items: list[dict[str, Any]]) -> str:
    risks = [item.get("risk", "") for item in items if item.get("risk")]
    if not risks:
        return ""
    return max(risks, key=lambda value: RISK_ORDER.get(value, 0))


def aggregate_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in rows:
        key = (item.get("type", ""), item.get("code", ""))
        groups.setdefault(key, []).append(item)

    aggregated = []
    for group_rows in groups.values():
        best = max(group_rows, key=lambda row: row["total_score"])
        source_names = []
        for row in sorted(group_rows, key=lambda item: item.get("source_name", "")):
            name = row.get("source_name") or row.get("source")
            if name not in source_names:
                source_names.append(name)
        item = dict(best)
        item["source_names"] = "、".join(source_names)
        item["source_count"] = len(source_names)
        item["aggregate_score"] = best["total_score"] + max(0, len(source_names) - 1) * 1.5
        item["risk"] = worst_risk(group_rows) or best.get("risk", "")
        if len(source_names) > 1:
            item["logic"] = f"{best.get('logic')} 多来源共振，需优先确认共同买点与止损纪律。"
        aggregated.append(item)
    return sorted(aggregated, key=lambda row: row["aggregate_score"], reverse=True)


def render_aggregate_section(accepted: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> tuple[str, int, int]:
    aggregated = aggregate_candidates(accepted)
    short_top = pick_top_candidates(aggregated, "short")
    mid_top = pick_top_candidates(aggregated, "mid")
    return (
        f"""
<section class="section-card" id="selection">
  <div class="section-title">
    <p>Composite Selection</p>
    <h2>综合筛选结果</h2>
  </div>
  <h3>短期观察 3 只</h3>
  {render_pick_table(short_top, include_sources=True)}
  <h3>中长期观察 3 只</h3>
  {render_pick_table(mid_top, include_sources=True)}
  <h3>剔除观察</h3>
  {render_excluded_table(rejected)}
</section>
""".strip(),
        len(short_top),
        len(mid_top),
    )


def render_comments_section(comments: list[dict[str, str]], source_lookup: dict[str, str], date_text: str) -> str:
    if comments:
        content = table(
            ["评论来源", "来源人", "评论内容", "提到的股票", "提到的板块", "为什么有价值", "是否纳入推荐逻辑"],
            [
                [
                    comment["comment_source"],
                    source_lookup.get(comment["source"], comment["source"]),
                    comment["content"],
                    comment["mentioned_stocks"],
                    comment["mentioned_sectors"],
                    comment["value_reason"],
                    comment["include_in_logic"],
                ]
                for comment in comments
            ],
        )
    else:
        path = ROOT / "data" / "daily" / date_text / "comments.csv"
        content = empty_note(f"暂无有价值评论聚合，可补充 {rel(path)}。")
    return f"""
<section class="section-card" id="comments">
  <div class="section-title">
    <p>Comment Signals</p>
    <h2>有价值评论聚合</h2>
  </div>
  {content}
</section>
""".strip()


def render_discipline_section() -> str:
    return f"""
<section class="section-card section-card--warning" id="risk">
  <div class="section-title">
    <p>Risk Rules</p>
    <h2>操作纪律与风险提示</h2>
  </div>
  {render_trading_discipline_block()}
</section>
""".strip()


def render_report_html(source: dict[str, Any], date_text: str, picks: list[dict[str, str]], holdings: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
    scored = score_candidates(picks, source["name"])
    accepted, rejected = filter_candidates(scored)
    short_top = pick_top_candidates(accepted, "short")
    mid_top = pick_top_candidates(accepted, "mid")
    updated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = f"{source['name']} {date_text} A股技术形态观察池"
    summary = f"短线观察 {len(short_top)} 只，中线观察 {len(mid_top)} 只，包含个人持仓、右侧转强、底部突破、中继回踩与盈亏比筛选。"
    html_text = f"""
<section class="report-document">
  <h1>{esc(title)}</h1>
  <h2>一、今日总览</h2>
  <ul>
    <li>来源人：{esc(source['name'])}</li>
    <li>日期：{esc(date_text)}</li>
    <li>更新时间：{esc(updated_at)}</li>
    <li>策略说明：A股技术形态观察池，偏好右侧转强、底部突破、中继回踩，强调止损位与盈亏比。</li>
    <li>风险提示：本文仅为个人复盘与技术形态观察，不构成任何投资建议。</li>
  </ul>

  <h2>二、博主个人持仓</h2>
  {render_holdings_section(holdings)}

  <h2>三、今日原始选股摘要</h2>
  {render_raw_summary(scored)}

  <h2>四、短线观察池 TOP 3</h2>
  {render_pick_table(short_top)}

  <h2>五、中线观察池 TOP 3</h2>
  {render_pick_table(mid_top)}

  <h2>六、剔除观察</h2>
  {render_excluded_table(rejected)}

  <h2>七、操作纪律</h2>
  {render_trading_discipline_block()}
</section>
""".strip()
    meta = {
        "date": date_text,
        "source": source["id"],
        "source_name": source["name"],
        "report_type": "source_article",
        "title": title,
        "summary": summary,
        "tags": [source["name"], "个人持仓", "短线观察", "中线观察", "技术形态"],
        "slug": f"{source['id']}_{date_text}",
        "url": f"/articles/{source['id']}_{date_text}/",
    }
    return html_text, meta


def collect_daily_data(
    sources: list[dict[str, Any]],
    date_text: str,
    strict_extra: bool,
    loose_source_data: bool = False,
) -> dict[str, Any]:
    comments = load_daily_comments(date_text, strict_extra)
    comments_by_source: dict[str, list[dict[str, str]]] = {}
    for comment in comments:
        comments_by_source.setdefault(comment.get("source", ""), []).append(comment)

    source_sections = []
    all_scored: list[dict[str, Any]] = []
    all_accepted: list[dict[str, Any]] = []
    all_rejected: list[dict[str, Any]] = []
    all_posts: list[dict[str, str]] = []

    for source in sources:
        picks = load_picks_for_daily(source["id"], date_text, loose_source_data)
        holdings = load_holdings_for_daily(source["id"], date_text, loose_source_data)
        posts = load_source_posts(source["id"], date_text, strict_extra)
        scored = score_candidates(picks, source["name"])
        accepted, rejected = filter_candidates(scored)
        source_sections.append(
            {
                "source": source,
                "picks": picks,
                "holdings": holdings,
                "posts": posts,
                "comments": comments_by_source.get(source["id"], []),
                "scored": scored,
                "accepted": accepted,
                "rejected": rejected,
            }
        )
        all_scored.extend(scored)
        all_accepted.extend(accepted)
        all_rejected.extend(rejected)
        all_posts.extend(posts)

    return {
        "market": load_market_info(date_text, strict_extra),
        "timeline": load_timeline(date_text, strict_extra),
        "comments": comments,
        "source_sections": source_sections,
        "all_scored": all_scored,
        "all_accepted": all_accepted,
        "all_rejected": all_rejected,
        "all_posts": all_posts,
    }


def render_daily_report_html(
    sources: list[dict[str, Any]],
    date_text: str,
    strict_extra: bool,
    loose_source_data: bool = False,
) -> tuple[str, dict[str, Any]]:
    daily = collect_daily_data(sources, date_text, strict_extra, loose_source_data)
    source_lookup = {source["id"]: source["name"] for source in sources}
    updated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    selection_html, short_count, mid_count = render_aggregate_section(daily["all_accepted"], daily["all_rejected"])
    title = f"{date_text} A股综合复盘工作台"
    summary = f"按日期聚合四个来源，短期观察 {short_count} 只，中长期观察 {mid_count} 只，覆盖时间线、大盘信息、来源人板块与评论信号。"
    nav_items = ["今日总览", "今日时间线", "大盘信息", "来源人板块", "综合筛选结果", "有价值评论聚合", "操作纪律"]
    nav_html = "".join(f"<span>{esc(item)}</span>" for item in nav_items)
    html_text = f"""
<section class="workbench">
  <header class="workbench-hero">
    <p>Encrypted Daily Desk</p>
    <h1>{esc(title)}</h1>
    <div class="workbench-nav">{nav_html}</div>
  </header>
  {render_overview_section(date_text, updated_at, daily["market"])}
  {render_timeline_section(daily["timeline"], daily["all_posts"], daily["comments"], source_lookup, date_text)}
  {render_market_section(daily["market"], date_text)}
  {render_sources_section(daily["source_sections"], date_text)}
  {selection_html}
  {render_comments_section(daily["comments"], source_lookup, date_text)}
  {render_discipline_section()}
</section>
""".strip()
    meta = {
        "date": date_text,
        "source": "daily",
        "source_name": "综合复盘",
        "report_type": "daily_workbench",
        "title": title,
        "summary": summary,
        "tags": ["综合复盘", "今日总览", "时间线", "大盘信息", "来源聚合", "技术形态"],
        "slug": f"daily_{date_text}",
        "url": f"/articles/daily_{date_text}/",
    }
    return html_text, meta


def load_report_index() -> list[dict[str, Any]]:
    if not REPORT_INDEX_FILE.exists():
        return []
    return json.loads(REPORT_INDEX_FILE.read_text(encoding="utf-8"))


def save_report_index(items: list[dict[str, Any]]) -> None:
    REPORT_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    sorted_items = sorted(items, key=lambda item: (item["date"], item["source"]), reverse=True)
    REPORT_INDEX_FILE.write_text(json.dumps(sorted_items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def upsert_report_index(meta_items: list[dict[str, Any]], replace_date_with_daily: str | None = None) -> None:
    existing = load_report_index()
    if replace_date_with_daily:
        existing = [item for item in existing if item.get("date") != replace_date_with_daily]
    by_key = {(item["source"], item["date"]): item for item in existing}
    for item in meta_items:
        by_key[(item["source"], item["date"])] = item
    save_report_index(list(by_key.values()))


def generate_for_source(source: dict[str, Any], date_text: str) -> dict[str, Any]:
    picks = load_picks(source["id"], date_text)
    holdings = load_holdings(source["id"], date_text)
    report_html, meta = render_report_html(source, date_text, picks, holdings)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out_file = TMP_DIR / f"{source['id']}_{date_text}.html"
    out_file.write_text(report_html, encoding="utf-8")
    print(f"generated: {out_file}")
    return meta


def generate_daily_workspace(
    sources: list[dict[str, Any]],
    date_text: str,
    strict_extra: bool,
    loose_source_data: bool = False,
) -> dict[str, Any]:
    report_html, meta = render_daily_report_html(sources, date_text, strict_extra, loose_source_data)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out_file = TMP_DIR / f"daily_{date_text}.html"
    out_file.write_text(report_html, encoding="utf-8")
    print(f"generated: {out_file}")
    return meta


def public_stock(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": item.get("code", ""),
        "name": item.get("name", ""),
        "type": type_label(item.get("type", "")),
        "pattern": item.get("pattern", ""),
        "source_names": item.get("source_names") or item.get("source_name") or item.get("source", ""),
        "entry_range": f"{item.get('entry_low', '')}-{item.get('entry_high', '')}",
        "stop_loss": item.get("stop_loss", ""),
        "take_profit_1": item.get("take_profit_1", ""),
        "take_profit_2": item.get("take_profit_2", ""),
        "risk_reward": f"1:{item.get('risk_reward_score', 0):.1f}",
        "trade_signal": volume_price_rule_for_item(item),
        "risk": item.get("risk", ""),
        "reason": item.get("logic", ""),
        "score": round(float(item.get("aggregate_score", item.get("total_score", 0))), 2),
    }


def split_values(value: str, limit: int = 4) -> list[str]:
    separators = ["；", ";", "、", ",", "，", "|", "/"]
    values = [value]
    for separator in separators:
        values = [part for item in values for part in item.split(separator)]
    cleaned = [item.strip() for item in values if item.strip()]
    return cleaned[:limit]


def parse_sector_stock_map(value: str) -> dict[str, dict[str, str]]:
    """Parse '板块=股票(代码);板块=股票(代码)' into a lookup map."""
    mapping: dict[str, dict[str, str]] = {}
    for segment in re.split(r"[;；\n]+", value or ""):
        text = segment.strip()
        if not text or "=" not in text:
            continue
        sector, stock_text = [part.strip() for part in text.split("=", 1)]
        if not sector or not stock_text:
            continue
        match = re.search(r"(.+?)\((\d{6})\)", stock_text)
        if match:
            mapping[sector] = {"name": match.group(1).strip(), "code": match.group(2), "source": "first_limit_up"}
        else:
            mapping[sector] = {"name": stock_text, "code": "", "source": "first_limit_up"}
    return mapping


def extract_media_paths(value: str) -> list[str]:
    text = value or ""
    matches = re.findall(r"/media/[^\s;，,]+", text)
    return list(dict.fromkeys(matches))


def extract_http_urls(value: str) -> list[str]:
    text = value or ""
    matches = re.findall(r"https?://[^\s;，,]+", text)
    return list(dict.fromkeys(matches))


def public_post(post: dict[str, str]) -> dict[str, Any]:
    return {
        "channel": post.get("channel", ""),
        "title": post.get("title", ""),
        "url": post.get("url", ""),
        "media": extract_media_paths(post.get("image", "")),
        "summary": post.get("summary") or post.get("raw_text") or post.get("note", ""),
        "mentioned_stocks": post.get("mentioned_stocks", ""),
        "mentioned_sectors": post.get("mentioned_sectors", ""),
        "note": post.get("note", ""),
    }


def public_comment(item: dict[str, str], source_lookup: dict[str, str]) -> dict[str, Any]:
    source_id = item.get("source", "")
    return {
        "source_id": source_id,
        "source": source_lookup.get(source_id, source_id),
        "source_name": source_lookup.get(source_id, source_id),
        "comment_source": item.get("comment_source", ""),
        "content": item.get("content", ""),
        "mentioned_stocks": item.get("mentioned_stocks", ""),
        "mentioned_sectors": item.get("mentioned_sectors", ""),
        "value_reason": item.get("value_reason", ""),
        "include_in_logic": item.get("include_in_logic", ""),
        "note": item.get("note", ""),
        "media": extract_media_paths(item.get("note", "")),
        "video_urls": extract_http_urls(item.get("note", "")),
    }


def summarize_source_card(source_data: dict[str, Any]) -> dict[str, Any]:
    source = source_data["source"]
    accepted = sorted(source_data["accepted"], key=lambda item: item["total_score"], reverse=True)
    holdings = source_data["holdings"]
    posts = source_data["posts"]
    comments = source_data["comments"]
    top_picks = accepted[:3]
    return {
        "id": source["id"],
        "name": source["name"],
        "channel": SOURCE_POST_LABELS.get(source["id"], ("帖子/视频", ""))[0],
        "latest_title": posts[0]["title"] if posts else "暂无公开帖子/视频数据",
        "latest_summary": (posts[0].get("summary") or posts[0].get("raw_text") or posts[0].get("note")) if posts else "可补充 posts CSV 后展示来源原文摘要。",
        "top_picks": [
            {
                "code": item["code"],
                "name": item["name"],
                "type": type_label(item.get("type", "")),
                "pattern": item.get("pattern", ""),
            }
            for item in top_picks
        ],
        "holdings": [
            {
                "code": item["code"],
                "name": item["name"],
                "position_ratio": item["position_ratio"],
                "status": item["status"],
            }
            for item in holdings[:3]
        ],
        "comment_count": len(comments),
        "posts": [public_post(post) for post in posts],
        "comments": [public_comment(comment, {source["id"]: source["name"]}) for comment in comments[:8]],
    }


def fallback_timeline_from_sources(daily: dict[str, Any], source_lookup: dict[str, str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for row in daily["timeline"]:
        items.append(
            {
                "time": row.get("time") or "--:--",
                "category": row.get("category", ""),
                "source": source_lookup.get(row.get("source", ""), row.get("source", "")),
                "title": row.get("title", ""),
                "content": row.get("content", ""),
            }
        )
    if items:
        return items[:8]

    for source_data in daily["source_sections"]:
        source = source_data["source"]
        first_pick = source_data["scored"][0] if source_data["scored"] else None
        if first_pick:
            items.append(
                {
                    "time": "盘中",
                    "category": "source_pick",
                    "source": source["name"],
                    "title": f"{source['name']} 今日观察",
                    "content": f"{first_pick['name']}：{first_pick.get('raw_text') or first_pick.get('logic')}",
                }
            )
    items.append(
        {
            "time": "15:00",
            "category": "after_close",
            "source": "系统",
            "title": "盘后总结",
            "content": "大盘信息、帖子/视频和评论 CSV 缺失时，首页展示基于 picks/holdings 的公开概要。",
        }
    )
    return items[:8]


def write_dashboard_data(
    report_meta: dict[str, Any],
    sources: list[dict[str, Any]],
    date_text: str,
    strict_extra: bool,
    loose_source_data: bool = False,
) -> None:
    daily = collect_daily_data(sources, date_text, strict_extra, loose_source_data)
    source_lookup = {source["id"]: source["name"] for source in sources}
    aggregated = aggregate_candidates(daily["all_accepted"])
    short_top = pick_top_candidates(aggregated, "short")
    mid_top = pick_top_candidates(aggregated, "mid")
    top_patterns = []
    for item in daily["all_accepted"]:
        pattern = item.get("pattern", "")
        if pattern and pattern not in top_patterns:
            top_patterns.append(pattern)
    dashboard = {
        "date": date_text,
        "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "report": report_meta,
        "overview": {
            "market_status": plain_market_value(daily["market"], "market_status", "需补充 market.csv"),
            "main_sectors": split_values(plain_market_value(daily["market"], "main_sectors", "暂无数据")),
            "risk_level": plain_market_value(daily["market"], "risk_level", "中"),
            "operation_tone": plain_market_value(daily["market"], "operation_tone", "控制仓位，只等买点"),
            "sentiment": plain_market_value(daily["market"], "sentiment_cycle", "暂无数据"),
            "risk_signal": plain_market_value(daily["market"], "risk_signal", "暂无数据"),
            "tomorrow_watch": plain_market_value(daily["market"], "tomorrow_watch", "暂无数据"),
        },
        "market": {
            "index_status": plain_market_value(daily["market"], "index_status", "暂无指数状态"),
            "volume_change": plain_market_value(daily["market"], "volume_change", "暂无成交量数据"),
            "sector_rotation": plain_market_value(daily["market"], "sector_rotation", "暂无板块轮动数据"),
            "accumulation_direction": split_values(plain_market_value(daily["market"], "accumulation_direction", "暂无数据")),
            "sector_first_limit_up": parse_sector_stock_map(plain_market_value(daily["market"], "sector_first_limit_up", "")),
            "capital_preference": plain_market_value(daily["market"], "capital_preference", "暂无资金偏好数据"),
        },
        "stats": {
            "source_count": len(sources),
            "candidate_count": len(daily["all_scored"]),
            "accepted_count": len(daily["all_accepted"]),
            "rejected_count": len(daily["all_rejected"]),
            "comment_count": len(daily["comments"]),
            "top_patterns": top_patterns[:4],
        },
        "timeline": fallback_timeline_from_sources(daily, source_lookup),
        "sources": [summarize_source_card(item) for item in daily["source_sections"]],
        "selection": {
            "short": [public_stock(item) for item in short_top],
            "mid": [public_stock(item) for item in mid_top],
        },
        "comments": [public_comment(item, source_lookup) for item in daily["comments"]],
        "comment_sources": [
            {
                "id": source["id"],
                "name": source["name"],
                "count": len([item for item in daily["comments"] if item.get("source") == source["id"]]),
                "post_count": len([post for post in daily["all_posts"] if post.get("source") == source["id"]]),
            }
            for source in sources
        ],
        "evidence": {
            source["id"]: {
                "name": source["name"],
                "posts": [
                    public_post(post)
                    for post in daily["all_posts"]
                    if post.get("source") == source["id"]
                ],
            }
            for source in sources
        },
    }
    DASHBOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_FILE.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    DASHBOARDS_DIR.mkdir(parents=True, exist_ok=True)
    dated_dashboard = DASHBOARDS_DIR / f"{date_text}.json"
    dated_dashboard.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"updated: {DASHBOARD_FILE}")
    print(f"updated: {dated_dashboard}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate encrypted-site stock reports from CSV input.")
    parser.add_argument("--source", help="只生成指定来源的兼容旧版来源文章")
    parser.add_argument("--date", help="报告日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--all", action="store_true", help="生成全部 enabled 来源的每日综合复盘工作台")
    parser.add_argument("--strict-extra", action="store_true", help="可选的大盘、时间线、帖子/视频、评论 CSV 缺失时直接报错")
    parser.add_argument("--loose-source-data", action="store_true", help="历史导入使用：某来源 picks/holdings 缺失时显示暂无数据，不生成随机内容")
    args = parser.parse_args()

    try:
        date_text = parse_date(args.date).isoformat()
        config = load_source_config()
        sources = resolve_sources(config, args.source, args.all)
        if args.source:
            metas = [generate_for_source(source, date_text) for source in sources]
            upsert_report_index(metas)
        else:
            meta = generate_daily_workspace(sources, date_text, args.strict_extra, args.loose_source_data)
            upsert_report_index([meta], replace_date_with_daily=date_text)
            write_dashboard_data(meta, sources, date_text, args.strict_extra, args.loose_source_data)
        print(f"updated: {REPORT_INDEX_FILE}")
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
