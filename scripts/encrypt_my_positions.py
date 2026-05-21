#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import html
import json
import os
import sys
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "my"
TMP_DIR = ROOT / "build" / "tmp"
ENCRYPTED_DIR = ROOT / "encrypted" / "my"
ASTRO_INDEX_FILE = ROOT / "src" / "data" / "my_positions_index.json"
ITERATIONS = 200000

POSITION_FIELDS = [
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
    "note",
]

OPERATION_FIELDS = [
    "date",
    "time",
    "action",
    "code",
    "name",
    "price",
    "volume_ratio",
    "reason",
    "plan",
    "stop_loss",
    "take_profit",
    "result",
    "note",
]

TRADE_REVIEW_FIELDS = [
    "date",
    "code",
    "name",
    "account_type",
    "action",
    "trade_timing",
    "price",
    "shares",
    "trade_amount",
    "buy_amount",
    "sell_amount",
    "fees",
    "position_cost",
    "position_shares",
    "position_ratio",
    "cash_after",
    "equity_after",
    "daily_pnl",
    "total_pnl",
    "total_return_pct",
    "buy_point",
    "sell_point",
    "stop_loss",
    "take_profit",
    "holding_days",
    "signal",
    "reason",
    "plan",
    "risk",
    "user_confirmation",
    "confirmation_source",
    "quote_time",
    "bar_status",
    "open",
    "high",
    "low",
    "close",
    "pct_change",
    "turnover_rate_pct",
    "amount_wan",
    "volume_lot",
    "ma5",
    "ma10",
    "ma20",
    "high_20",
    "low_20",
    "data_source",
    "note",
]


class MyPositionError(Exception):
    pass


def build_my_position_password() -> str:
    return "xiaofan666888"


def parse_date(value: str | None) -> dt.date:
    if value:
        return dt.date.fromisoformat(value)
    return dt.date.today()


def read_csv_rows(path: Path, fields: list[str], label: str, mode: str) -> tuple[list[dict[str, str]], bool]:
    if not path.exists():
        if mode == "strict":
            raise MyPositionError(f"未找到我的{label}数据，请先创建 {path.relative_to(ROOT)}")
        return [], False

    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        missing = [field for field in fields if field not in (reader.fieldnames or [])]
        if missing:
            raise MyPositionError(f"{path.relative_to(ROOT)} 缺少字段：{', '.join(missing)}")
        rows = [{field: (row.get(field) or "").strip() for field in fields} for row in reader]
    return [row for row in rows if any(row.values())], True


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def parse_number(value: str) -> float | None:
    cleaned = (
        (value or "")
        .replace(",", "")
        .replace("%", "")
        .replace("元", "")
        .replace("+", "")
        .strip()
    )
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def value_class(value: str) -> str:
    number = parse_number(value)
    if number is None or number == 0:
        return ""
    return "danger-text" if number > 0 else "green-text"


def sum_numeric(rows: list[dict[str, str]], field: str) -> float:
    total = 0.0
    for row in rows:
        number = parse_number(row.get(field, ""))
        if number is not None:
            total += number
    return total


def render_positions_table(rows: list[dict[str, str]], existed: bool) -> str:
    if not rows:
        message = "今日未上传个人持仓" if not existed else "今日个人持仓文件为空"
        return f'<div class="private-empty">{esc(message)}</div>'

    body = "\n".join(
        "<tr>"
        f"<td>{esc(row['code'])}</td>"
        f"<td><strong>{esc(row['name'])}</strong></td>"
        f"<td>{esc(row['position_type'])}</td>"
        f"<td>{esc(row['cost_price'])}</td>"
        f"<td>{esc(row['current_price'])}</td>"
        f"<td>{esc(row['position_ratio'])}</td>"
        f"<td class=\"{'green-text' if row['profit_loss_pct'].startswith('-') else 'danger-text'}\">{esc(row['profit_loss_pct'])}</td>"
        f"<td>{esc(row['status'])}</td>"
        f"<td>{esc(row['plan'])}</td>"
        f"<td>{esc(row['stop_loss'])}</td>"
        f"<td>{esc(row['take_profit_1'])}</td>"
        f"<td>{esc(row['take_profit_2'])}</td>"
        f"<td>{esc(row['risk'])}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
<div class="private-table-wrap">
  <table class="private-table">
    <thead>
      <tr><th>代码</th><th>名称</th><th>仓位类型</th><th>成本价</th><th>现价</th><th>仓位比例</th><th>浮盈浮亏</th><th>状态</th><th>后续计划</th><th>止损位</th><th>止盈1</th><th>止盈2</th><th>风险</th></tr>
    </thead>
    <tbody>{body}</tbody>
  </table>
</div>
"""


def render_trade_reviews(rows: list[dict[str, str]], existed: bool) -> str:
    if not rows:
        message = "今日未生成单票每日复盘" if not existed else "今日单票复盘文件为空"
        return f'<div class="private-empty">{esc(message)}</div>'

    cards = []
    for row in rows:
        daily_class = value_class(row["daily_pnl"])
        total_class = value_class(row["total_pnl"])
        cards.append(
            f"""
<article class="private-review-card">
  <header>
    <div>
      <span>{esc(row['code'])} · {esc(row['account_type'])}</span>
      <h3>{esc(row['name'])}</h3>
    </div>
    <strong>{esc(row['action'])}</strong>
  </header>
  <div class="private-review-metrics">
    <p><span>参考价</span><strong>{esc(row['price'])}</strong></p>
    <p><span>交易金额</span><strong>{esc(row['trade_amount'])}</strong></p>
    <p><span>买入金额</span><strong>{esc(row['buy_amount'])}</strong></p>
    <p><span>卖出金额</span><strong>{esc(row['sell_amount'])}</strong></p>
    <p><span>费用</span><strong>{esc(row['fees'])}</strong></p>
    <p><span>持仓股数</span><strong>{esc(row['position_shares'])}</strong></p>
    <p><span>仓位</span><strong>{esc(row['position_ratio'])}</strong></p>
    <p><span>现金</span><strong>{esc(row['cash_after'])}</strong></p>
    <p><span>账户权益</span><strong>{esc(row['equity_after'])}</strong></p>
    <p><span>当天盈亏</span><strong class="{daily_class}">{esc(row['daily_pnl'])}</strong></p>
    <p><span>总盈亏</span><strong class="{total_class}">{esc(row['total_pnl'])}</strong></p>
    <p><span>总收益率</span><strong class="{total_class}">{esc(row['total_return_pct'])}</strong></p>
  </div>
  <dl class="private-review-lines">
    <div><dt>交易时机</dt><dd>{esc(row['trade_timing'])}</dd></div>
    <div><dt>买点</dt><dd>{esc(row['buy_point'])}</dd></div>
    <div><dt>卖点</dt><dd>{esc(row['sell_point'])}</dd></div>
    <div><dt>止损</dt><dd>{esc(row['stop_loss'])}</dd></div>
    <div><dt>止盈</dt><dd>{esc(row['take_profit'])}</dd></div>
    <div><dt>信号</dt><dd>{esc(row['signal'])}</dd></div>
    <div><dt>计划</dt><dd>{esc(row['plan'])}</dd></div>
    <div><dt>行情状态</dt><dd>{esc(row['bar_status'])} · {esc(row['quote_time'])}</dd></div>
    <div><dt>开高低收</dt><dd>{esc(row['open'])} / {esc(row['high'])} / {esc(row['low'])} / {esc(row['close'])}</dd></div>
    <div><dt>涨跌/换手</dt><dd>{esc(row['pct_change'])} / {esc(row['turnover_rate_pct'])}</dd></div>
    <div><dt>成交额/成交量</dt><dd>{esc(row['amount_wan'])} / {esc(row['volume_lot'])}</dd></div>
    <div><dt>均线</dt><dd>MA5 {esc(row['ma5'])} · MA10 {esc(row['ma10'])} · MA20 {esc(row['ma20'])}</dd></div>
    <div><dt>20日区间</dt><dd>{esc(row['low_20'])} - {esc(row['high_20'])}</dd></div>
    <div><dt>你的记录</dt><dd>{esc(row['user_confirmation'])}；{esc(row['confirmation_source'])}</dd></div>
  </dl>
  <p class="private-review-note"><strong>复盘备注</strong><span>{esc(row['reason'] or row['note'])}</span></p>
</article>
"""
        )
    return f'<div class="private-review-grid">{"".join(cards)}</div>'


def render_operations_table(rows: list[dict[str, str]], existed: bool) -> str:
    if not rows:
        message = "今日未上传操作记录" if not existed else "今日操作记录文件为空"
        return f'<div class="private-empty">{esc(message)}</div>'

    body = "\n".join(
        "<tr>"
        f"<td>{esc(row['time'])}</td>"
        f"<td>{esc(row['action'])}</td>"
        f"<td>{esc(row['code'])}</td>"
        f"<td><strong>{esc(row['name'])}</strong></td>"
        f"<td>{esc(row['price'])}</td>"
        f"<td>{esc(row['volume_ratio'])}</td>"
        f"<td>{esc(row['reason'])}</td>"
        f"<td>{esc(row['plan'])}</td>"
        f"<td>{esc(row['stop_loss'])}</td>"
        f"<td>{esc(row['take_profit'])}</td>"
        f"<td class=\"green-text\">{esc(row['result'])}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
<div class="private-table-wrap">
  <table class="private-table">
    <thead>
      <tr><th>时间</th><th>操作类型</th><th>代码</th><th>股票</th><th>价格</th><th>仓位</th><th>原因</th><th>后续计划</th><th>止损位</th><th>止盈位</th><th>结果</th></tr>
    </thead>
    <tbody>{body}</tbody>
  </table>
</div>
"""


def sum_position_ratio(rows: list[dict[str, str]]) -> float:
    total = 0.0
    for row in rows:
        value = row.get("position_ratio", "").replace("%", "").strip()
        if not value:
            continue
        try:
            total += float(value)
        except ValueError:
            continue
    return total


def count_by_keyword(rows: list[dict[str, str]], *keywords: str) -> int:
    return sum(1 for row in rows if any(keyword in row.get("status", "") or keyword in row.get("action", "") for keyword in keywords))


def render_watch_list(rows: list[dict[str, str]], keyword: str, empty: str) -> str:
    matched = [row for row in rows if keyword in row.get("status", "")]
    if not matched:
        return f'<div class="private-empty">{esc(empty)}</div>'
    items = "\n".join(
        f"<li><strong>{esc(row['name'])}</strong><span>{esc(row['current_price'])}</span><em>{esc(row['plan'])}</em></li>"
        for row in matched
    )
    return f"<ul class=\"private-watch-list\">{items}</ul>"


def render_report_html(
    date_text: str,
    positions: list[dict[str, str]],
    positions_existed: bool,
    operations: list[dict[str, str]],
    operations_existed: bool,
    trade_reviews: list[dict[str, str]],
    trade_reviews_existed: bool,
) -> str:
    total_ratio = sum_position_ratio(positions)
    floating_count = sum(1 for row in positions if row.get("profit_loss_pct", "").startswith("+"))
    stop_loss_count = count_by_keyword(positions, "止损")
    take_profit_count = count_by_keyword(positions, "止盈")
    operation_count = len(operations)
    review_count = len(trade_reviews)
    daily_pnl = sum_numeric(trade_reviews, "daily_pnl")
    total_pnl = sum_numeric(trade_reviews, "total_pnl")
    equity_total = sum_numeric(trade_reviews, "equity_after")
    cash_total = sum_numeric(trade_reviews, "cash_after")
    risk_high_count = sum(1 for row in positions if row.get("risk") == "高")

    return f"""
<section class="private-workbench">
  <header class="private-hero">
    <div>
      <p>每日复盘 / 两票模拟盘</p>
      <h1>{esc(date_text)} 冠捷科技与山东玻纤复盘</h1>
      <span>默认同步本地模拟盘；你的真实买卖只在截图确认后写入。</span>
    </div>
    <strong>已解锁</strong>
  </header>

  <section class="private-metric-grid">
    <article><span>跟踪标的</span><strong>{review_count} 只</strong><small>冠捷科技 / 山东玻纤</small></article>
    <article><span>当天盈亏</span><strong class="{value_class(str(daily_pnl))}">{daily_pnl:,.2f}</strong><small>按独立模拟账户合计</small></article>
    <article><span>总盈亏</span><strong class="{value_class(str(total_pnl))}">{total_pnl:,.2f}</strong><small>自模拟起始日累计</small></article>
    <article><span>账户权益</span><strong>{equity_total:,.2f}</strong><small>两只票模拟账户合计</small></article>
    <article><span>可用现金</span><strong>{cash_total:,.2f}</strong><small>两只票模拟账户合计</small></article>
    <article><span>真实确认</span><strong>{operation_count} 条</strong><small>等截图确认后写入</small></article>
  </section>

  <section class="private-grid">
    <article class="private-panel private-full">
      <div class="private-panel-head"><h2>一、模拟盘每日复盘</h2><span>交易时机、金额、买卖点、止损止盈与公开行情</span></div>
      {render_trade_reviews(trade_reviews, trade_reviews_existed)}
    </article>

    <article class="private-panel private-wide">
      <div class="private-panel-head"><h2>二、我的确认记录</h2><span>你通知买卖点一致并给截图后，才会写入这里</span></div>
      {render_operations_table(operations, operations_existed)}
    </article>

    <article class="private-panel private-wide">
      <div class="private-panel-head"><h2>三、个人持仓总览</h2><span>仅展示你确认上传的个人持仓</span></div>
      {render_positions_table(positions, positions_existed)}
    </article>

    <article class="private-panel">
      <div class="private-panel-head"><h2>四、仓位分布</h2><span>个人确认持仓</span></div>
      <div class="private-donut"><strong>{total_ratio:.0f}%</strong><span>总仓位</span></div>
      <div class="private-risk-list">
        <p><span>短线/观察仓</span><strong>{sum(1 for row in positions if row.get('position_type') in ('短线', '观察仓'))} 只</strong></p>
        <p><span>中线/长线</span><strong>{sum(1 for row in positions if row.get('position_type') in ('中线', '长线'))} 只</strong></p>
        <p><span>高风险</span><strong class="danger-text">{risk_high_count} 只</strong></p>
      </div>
    </article>

    <article class="private-panel">
      <div class="private-panel-head"><h2>五、风险分布</h2><span>个人确认持仓</span></div>
      <div class="private-donut private-donut-risk"><strong>{risk_high_count}</strong><span>高风险</span></div>
      <div class="private-risk-list">
        <p><span>低风险</span><strong>{sum(1 for row in positions if row.get('risk') == '低')} 只</strong></p>
        <p><span>中风险</span><strong class="warning-text">{sum(1 for row in positions if row.get('risk') == '中')} 只</strong></p>
        <p><span>高风险</span><strong class="danger-text">{risk_high_count} 只</strong></p>
      </div>
    </article>

    <article class="private-panel">
      <div class="private-panel-head"><h2>六、止损观察</h2><span>{stop_loss_count} 只</span></div>
      {render_watch_list(positions, "止损", "今日暂无止损观察记录")}
    </article>

    <article class="private-panel">
      <div class="private-panel-head"><h2>七、止盈观察</h2><span>{take_profit_count} 只</span></div>
      {render_watch_list(positions, "止盈", "今日暂无止盈观察记录")}
    </article>

    <article class="private-panel private-wide">
      <div class="private-panel-head"><h2>八、操作纪律与风险提示</h2><span>模拟盘与真实操作分开记</span></div>
      <div class="private-discipline-grid">
        <p><strong>默认只记模拟盘</strong><span>每天自动同步本地模拟盘，不自动当作真实操作。</span></p>
        <p><strong>截图确认后落库</strong><span>只有你说买卖点一致并提供截图，才写入你的确认记录。</span></p>
        <p><strong>不追高</strong><span>只在计划区间内执行，错过就等下一次信号。</span></p>
        <p><strong>设好止损</strong><span>每笔操作必须有止损位，跌破无条件处理。</span></p>
        <p><strong>盈亏比优先</strong><span>不做盈亏比不划算的交易。</span></p>
        <p><strong>位置量能</strong><span>低位无量等，低位放量跟；高位无量拿，高位放量跑。</span></p>
        <p><strong>量价关系</strong><span>量增价升买，量增价减卖；量平价升加仓，量平价跌出局。</span></p>
        <p><strong>缩量上涨</strong><span>量减价升优先持有，但继续跟踪承接和止损线。</span></p>
        <p><strong>分批操作</strong><span>分批买入、分批止盈，降低单点判断风险。</span></p>
        <p><strong>控制仓位</strong><span>单只股票仓位不超过计划上限，总仓位按市场风险调整。</span></p>
        <p><strong>风险提示</strong><span>本文仅为个人复盘记录，不构成任何投资建议。</span></p>
      </div>
    </article>
  </section>
</section>
"""


def b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_html(date_text: str, html_text: str) -> Path:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = TMP_DIR / f"my_{date_text}.html"
    tmp_file.write_text(html_text, encoding="utf-8")

    salt = os.urandom(16)
    iv = os.urandom(12)
    key = derive_key(build_my_position_password(), salt)
    ciphertext = AESGCM(key).encrypt(iv, html_text.encode("utf-8"), None)
    payload = {
        "version": 1,
        "kdf": "PBKDF2-HMAC-SHA256",
        "cipher": "AES-GCM",
        "iterations": ITERATIONS,
        "salt": b64(salt),
        "iv": b64(iv),
        "ciphertext": b64(ciphertext),
    }

    ENCRYPTED_DIR.mkdir(parents=True, exist_ok=True)
    out_file = ENCRYPTED_DIR / f"{date_text}.json"
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_file


def sync_index() -> None:
    ENCRYPTED_DIR.mkdir(parents=True, exist_ok=True)
    items = [
        {
            "date": path.stem,
            "payload": f"{path.stem}.json",
            "url": "/my-positions/",
        }
        for path in sorted(ENCRYPTED_DIR.glob("*.json"), reverse=True)
    ]
    ASTRO_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    ASTRO_INDEX_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def encrypt_for_date(date_obj: dt.date, mode: str) -> Path:
    date_text = date_obj.isoformat()
    positions_path = DATA_DIR / "positions" / f"{date_text}.csv"
    operations_path = DATA_DIR / "operations" / f"{date_text}.csv"
    trade_reviews_path = DATA_DIR / "trade_reviews" / f"{date_text}.csv"
    positions, positions_existed = read_csv_rows(positions_path, POSITION_FIELDS, "个人持仓", mode)
    operations, operations_existed = read_csv_rows(operations_path, OPERATION_FIELDS, "操作记录", mode)
    trade_reviews, trade_reviews_existed = read_csv_rows(trade_reviews_path, TRADE_REVIEW_FIELDS, "单票每日复盘", mode)
    report_html = render_report_html(
        date_text,
        positions,
        positions_existed,
        operations,
        operations_existed,
        trade_reviews,
        trade_reviews_existed,
    )
    out_file = encrypt_html(date_text, report_html)
    sync_index()
    print(f"encrypted my positions: {out_file}")
    print(f"synced index: {ASTRO_INDEX_FILE}")
    return out_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Encrypt my positions and operations for the private static tab.")
    parser.add_argument("--date", help="日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--mode", choices=["strict", "loose"], default="strict", help="strict 缺文件报错；loose 缺文件展示暂无数据")
    args = parser.parse_args()

    try:
        encrypt_for_date(parse_date(args.date), args.mode)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
