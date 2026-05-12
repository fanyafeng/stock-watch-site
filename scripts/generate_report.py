#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "data" / "source_config.json"
REPORT_INDEX_FILE = ROOT / "data" / "reports.json"
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


class ReportError(Exception):
    pass


def parse_date(value: str | None) -> dt.date:
    if value:
        return dt.date.fromisoformat(value)
    return dt.date.today()


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
    ids = config.get("default_sources", []) if not all_sources else list(enabled.keys())
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


def to_float(row: dict[str, str], field: str) -> float:
    value = (row.get(field) or "").strip()
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        raise ReportError(f"{row.get('source', '')} {row.get('date', '')} {row.get('code', '')} 的 {field} 不是数字：{value}")


def score_candidates(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        item = dict(row)
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
        return "<p>暂无符合条件的标的。</p>"
    head = "".join(f"<th>{esc(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def risk_reward_text(item: dict[str, Any]) -> str:
    return f"盈亏比评分 {item['risk_reward_score']:.1f}，总分 {item['total_score']:.1f}，以止损位 {item.get('stop_loss')} 为纪律线。"


def selected_reason(item: dict[str, Any]) -> str:
    parts = [
        f"趋势 {item['trend_score']:.1f}",
        f"突破 {item['breakout_score']:.1f}",
        f"回踩 {item['pullback_score']:.1f}",
        f"量能 {item['volume_score']:.1f}",
        f"盈亏比 {item['risk_reward_score']:.1f}",
    ]
    return f"{item.get('logic')} 核心评分：{' / '.join(parts)}。"


def render_holdings_section(holdings: list[dict[str, str]]) -> str:
    if not holdings:
        return "<p>今日未记录公开持仓或持仓数据为空</p>"
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


def render_pick_table(rows: list[dict[str, Any]]) -> str:
    return table(
        ["股票代码", "股票名称", "技术形态", "入场区间", "止损位", "第一止盈位", "第二止盈位", "盈亏比说明", "风险等级", "当前状态", "入选理由"],
        [
            [
                item["code"],
                item["name"],
                item["pattern"],
                f"{item['entry_low']} - {item['entry_high']}",
                item["stop_loss"],
                item["take_profit_1"],
                item["take_profit_2"],
                risk_reward_text(item),
                item["risk"],
                item["status"],
                selected_reason(item),
            ]
            for item in rows
        ],
    )


def render_excluded_table(rows: list[dict[str, Any]]) -> str:
    return table(
        ["股票代码", "股票名称", "技术形态", "风险等级", "当前状态", "剔除原因"],
        [[item["code"], item["name"], item["pattern"], item["risk"], item["status"], item["excluded_reason"]] for item in rows],
    )


def render_raw_summary(picks: list[dict[str, Any]]) -> str:
    items = []
    for item in picks:
        detail = item.get("raw_text") or item.get("note") or item.get("logic")
        items.append(f"<li><strong>{esc(item['name'])}({esc(item['code'])})</strong>：{esc(detail)}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def render_report_html(source: dict[str, Any], date_text: str, picks: list[dict[str, str]], holdings: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
    scored = score_candidates(picks)
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
  <ul>
    <li>不追高，只等买点。</li>
    <li>买入前先看止损是否能接受。</li>
    <li>盈亏比不足不做。</li>
    <li>跌破止损无条件退出。</li>
    <li>本文仅为个人复盘与技术形态观察，不构成任何投资建议。</li>
  </ul>
</section>
""".strip()
    meta = {
        "date": date_text,
        "source": source["id"],
        "source_name": source["name"],
        "title": title,
        "summary": summary,
        "tags": [source["name"], "个人持仓", "短线观察", "中线观察", "技术形态"],
        "slug": f"{source['id']}_{date_text}",
        "url": f"/articles/{source['id']}_{date_text}/",
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


def upsert_report_index(meta_items: list[dict[str, Any]]) -> None:
    existing = load_report_index()
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate encrypted-site stock reports from CSV input.")
    parser.add_argument("--source", help="只生成指定来源")
    parser.add_argument("--date", help="报告日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--all", action="store_true", help="生成所有 enabled 来源")
    args = parser.parse_args()

    try:
        date_text = parse_date(args.date).isoformat()
        config = load_source_config()
        sources = resolve_sources(config, args.source, args.all)
        metas = [generate_for_source(source, date_text) for source in sources]
        upsert_report_index(metas)
        print(f"updated: {REPORT_INDEX_FILE}")
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
