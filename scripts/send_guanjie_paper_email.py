#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EMAIL_DIR = ROOT / "data" / "stocks" / "paper_trading" / "emails"
STOCKS = [
    {"code": "000727", "name": "冠捷科技"},
]
ENV_FILES = [
    ROOT / ".env.local",
    ROOT / ".env",
    ROOT.parent / "yeren_signal_monitor" / ".env.local",
]


def stock_paths(code: str) -> dict[str, Path]:
    paper_dir = ROOT / "data" / "stocks" / code / "paper_trading"
    return {
        "paper_dir": paper_dir,
        "account": paper_dir / "account.json",
        "journal": paper_dir / "journal.csv",
        "latest_signal": paper_dir / "latest_signal.md",
    }


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_env_files() -> None:
    for path in ENV_FILES:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def bool_env(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def read_journal(path: Path, date_text: str) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as file_obj:
        return [row for row in csv.DictReader(file_obj) if row.get("date") == date_text]


def money(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "待补充"


def pct(value: Any) -> str:
    try:
        return f"{float(value):.4f}%"
    except (TypeError, ValueError):
        return "待补充"


def compact_pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "待补充"


def read_latest_signal(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else "暂无最新提示。"


def clean_signal_lines(lines: list[str]) -> list[str]:
    output: list[str] = []
    in_code = False
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line:
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        if line:
            output.append(line)
    return output


def extract_signal_section(signal: str, heading: str) -> list[str]:
    target = f"## {heading}"
    lines = signal.splitlines()
    captured: list[str] = []
    capturing = False
    for line in lines:
        stripped = line.strip()
        if stripped == target:
            capturing = True
            continue
        if capturing and stripped.startswith("## "):
            break
        if capturing:
            captured.append(line)
    return clean_signal_lines(captured)


def account_metrics(account: dict[str, Any]) -> dict[str, Any]:
    shares = int(account.get("shares") or 0)
    last_price = float(account.get("last_price") or 0)
    last_equity = float(account.get("last_equity") or account.get("initial_cash") or 0)
    initial_cash = float(account.get("initial_cash") or 0)
    position_pct = 0 if last_equity <= 0 else shares * last_price / last_equity * 100
    pnl = last_equity - initial_cash
    return {
        "initial_cash": initial_cash,
        "cash": account.get("cash"),
        "shares": shares,
        "last_price": last_price,
        "last_equity": last_equity,
        "position_pct": position_pct,
        "pnl": pnl,
        "return_pct": (last_equity / initial_cash - 1) * 100 if initial_cash else 0,
    }


def daily_action_summary(journal: list[dict[str, str]], account: dict[str, Any]) -> tuple[str, str]:
    actions = [item.get("action", "") for item in journal]
    if any("买入" in action for action in actions):
        return "买入/计划执行", "今日出现买入相关流水，请重点核对成交价、仓位和止损线。"
    if any("卖出" in action or "止损" in action or "止盈" in action for action in actions):
        return "卖出/风控执行", "今日出现卖出或风控相关流水，请重点核对剩余仓位和现金。"
    if account.get("pending_order"):
        return "有买入计划", "已有待执行买入计划，次一交易日按开盘过滤规则判断是否执行。"
    if account.get("position"):
        return "持仓观察", "当前有持仓，盘中只盯止损、保护线和目标止盈，不临时扩大仓位。"
    return "等待信号", "今日暂无买卖，账户空仓，继续等待收盘信号。"


def html_escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def render_list_html(items: list[str]) -> str:
    if not items:
        return '<p class="muted">暂无。</p>'
    return "<ul>" + "".join(f"<li>{html_escape(item)}</li>" for item in items) + "</ul>"


def stock_context(stock: dict[str, str], date_text: str) -> dict[str, Any] | None:
    paths = stock_paths(stock["code"])
    account = load_json(paths["account"], None)
    if not account:
        return None
    journal = read_journal(paths["journal"], date_text)
    signal = read_latest_signal(paths["latest_signal"])
    metrics = account_metrics(account)
    status, summary = daily_action_summary(journal, account)
    plan_lines = (
        extract_signal_section(signal, "盘前操作单")
        or extract_signal_section(signal, "盘中触发提醒")
        or extract_signal_section(signal, "当前计划")
        or extract_signal_section(signal, "买入计划")
        or extract_signal_section(signal, "持仓风控线")
        or ["无持仓，无待执行买入计划；等待收盘后重新计算信号。"]
    )
    execution_lines = (
        extract_signal_section(signal, "当前计划")
        or extract_signal_section(signal, "买入计划")
        or extract_signal_section(signal, "持仓风控线")
        or ["无持仓，无待执行买入计划；等待收盘后重新计算信号。"]
    )
    daily_lines = extract_signal_section(signal, "最新日线状态")
    return {
        "stock": stock,
        "paths": paths,
        "account": account,
        "journal": journal,
        "signal": signal,
        "metrics": metrics,
        "status": status,
        "summary": summary,
        "plan_lines": plan_lines,
        "execution_lines": execution_lines,
        "daily_lines": daily_lines,
    }


def load_contexts(date_text: str) -> list[dict[str, Any]]:
    contexts = [stock_context(stock, date_text) for stock in STOCKS]
    return [context for context in contexts if context]


def build_body(date_text: str, kind: str = "daily") -> str:
    contexts = load_contexts(date_text)
    total_initial = sum(item["metrics"]["initial_cash"] for item in contexts)
    total_equity = sum(item["metrics"]["last_equity"] for item in contexts)
    total_pnl = total_equity - total_initial
    total_return = (total_equity / total_initial - 1) * 100 if total_initial else 0
    lines = [
        f"{'冠捷科技盘前操作单' if kind == 'preopen' else '冠捷科技模拟盘日报'} - {date_text}",
        "",
        "一、组合概览",
        f"- 初始本金合计：{money(total_initial)} 元",
        f"- 当前总权益：{money(total_equity)} 元",
        f"- 当前总盈亏：{money(total_pnl)} 元",
        f"- 当前总收益率：{pct(total_return)}",
        "",
    ]
    for index, context in enumerate(contexts, 1):
        stock = context["stock"]
        account = context["account"]
        metrics = context["metrics"]
        journal = context["journal"]
        lines.extend(
            [
                f"{index}、{stock['name']}({stock['code']})",
                f"- 状态：{context['status']}",
                f"- 摘要：{context['summary']}",
                f"- 初始本金：{money(metrics['initial_cash'])} 元",
                f"- 当前现金：{money(account.get('cash'))} 元",
                f"- 当前持仓：{metrics['shares']} 股",
                f"- 当前仓位：{metrics['position_pct']:.2f}%",
                f"- 当前总权益：{money(metrics['last_equity'])} 元",
                f"- 当期盈亏：{money(metrics['pnl'])} 元",
                f"- 当期收益率：{pct(metrics['return_pct'])}",
                "",
                "今日操作：",
            ]
        )
        if journal:
            for item in journal:
                lines.append(
                    f"- {item.get('action')}｜价格 {item.get('price')}｜股数 {item.get('shares')}｜金额 {item.get('gross')}｜费用 {item.get('fees')}｜原因：{item.get('reason')}"
                )
        else:
            lines.append("- 今日暂无流水。")
        lines.extend(
            [
                "",
                "盘前操作/当前计划：",
                *(f"- {item}" for item in context["plan_lines"]),
                "",
                "交易规则明细：",
                *(f"- {item}" for item in context["execution_lines"]),
                "",
                "最新日线：",
                *(f"- {item}" for item in (context["daily_lines"] or ["暂无最新日线摘要。"])),
                "",
            ]
        )
    lines.extend(
        [
            "执行口径",
            "- 当前邮件仅保留冠捷科技模拟盘提醒；山东玻纤只写入私密复盘账本。",
            "- Python 自动化只生成提示和记录模拟盘，不会真实下单。",
            "- 没有持仓时不盘中追涨、不临时低吸；等待收盘后重新计算信号。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def build_html_body(date_text: str, kind: str = "daily") -> str:
    contexts = load_contexts(date_text)
    total_initial = sum(item["metrics"]["initial_cash"] for item in contexts)
    total_equity = sum(item["metrics"]["last_equity"] for item in contexts)
    total_pnl = total_equity - total_initial
    total_return = (total_equity / total_initial - 1) * 100 if total_initial else 0
    pnl_color = "#DC2626" if total_pnl > 0 else "#16A34A" if total_pnl < 0 else "#475569"
    cards: list[str] = []
    for context in contexts:
        stock = context["stock"]
        account = context["account"]
        metrics = context["metrics"]
        item_pnl_color = "#DC2626" if metrics["pnl"] > 0 else "#16A34A" if metrics["pnl"] < 0 else "#475569"
        rows = []
        if context["journal"]:
            for item in context["journal"]:
                rows.append(
                    "<tr>"
                    f"<td>{html_escape(item.get('action'))}</td>"
                    f"<td>{html_escape(item.get('price'))}</td>"
                    f"<td>{html_escape(item.get('shares'))}</td>"
                    f"<td>{html_escape(item.get('gross'))}</td>"
                    f"<td>{html_escape(item.get('fees'))}</td>"
                    f"<td>{html_escape(item.get('reason'))}</td>"
                    "</tr>"
                )
        else:
            rows.append('<tr><td colspan="6" class="muted">今日暂无流水。</td></tr>')
        cards.append(
            f"""
    <div class="card">
      <h2>{html_escape(stock['name'])}({html_escape(stock['code'])})</h2>
      <span class="badge">{html_escape(context['status'])}</span>
      <p class="summary">{html_escape(context['summary'])}</p>
      <table class="metrics">
        <tr>
          <td><span class="label">初始本金</span><span class="value">{money(metrics['initial_cash'])}</span></td>
          <td><span class="label">当前现金</span><span class="value">{money(account.get('cash'))}</span></td>
          <td><span class="label">当前持仓</span><span class="value">{html_escape(metrics['shares'])} 股</span></td>
          <td><span class="label">当前仓位</span><span class="value">{compact_pct(metrics['position_pct'])}</span></td>
        </tr>
        <tr>
          <td><span class="label">参考价</span><span class="value">{html_escape(f"{metrics['last_price']:.3f}")}</span></td>
          <td><span class="label">总权益</span><span class="value">{money(metrics['last_equity'])}</span></td>
          <td><span class="label">当期盈亏</span><span class="value" style="color:{item_pnl_color}">{money(metrics['pnl'])}</span></td>
          <td><span class="label">收益率</span><span class="value" style="color:{item_pnl_color}">{compact_pct(metrics['return_pct'])}</span></td>
        </tr>
      </table>
      <h3>今日操作</h3>
      <table>
        <thead><tr><th>动作</th><th>价格</th><th>股数</th><th>金额</th><th>费用</th><th>原因</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      <h3>盘前操作/当前计划</h3>
      {render_list_html(context['plan_lines'])}
      <h3>交易规则明细</h3>
      {render_list_html(context['execution_lines'])}
      <h3>最新日线状态</h3>
      {render_list_html(context['daily_lines'])}
    </div>"""
        )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body{{margin:0;background:#F6F8FC;color:#172033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif;line-height:1.55;}}
    .wrap{{max-width:860px;margin:0 auto;padding:20px;}}
    .card{{background:#fff;border:1px solid #E5EAF2;border-radius:12px;padding:16px;margin:12px 0;}}
    h1{{font-size:22px;line-height:1.3;margin:0 0 6px;font-weight:800;color:#0F172A;}}
    h2{{font-size:17px;margin:0 0 10px;font-weight:800;color:#0F172A;}}
    h3{{font-size:14px;margin:14px 0 8px;font-weight:800;color:#334155;}}
    p{{margin:6px 0;}}
    .muted{{color:#64748B;font-size:13px;}}
    .badge{{display:inline-block;padding:3px 9px;border-radius:999px;background:#EFF6FF;color:#2563EB;font-size:12px;font-weight:700;}}
    .summary{{font-size:15px;font-weight:700;color:#1E293B;margin-top:8px;}}
    table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px;}}
    th,td{{border:1px solid #E5EAF2;padding:8px 9px;text-align:left;vertical-align:top;}}
    th{{background:#F8FAFC;color:#475569;font-weight:700;}}
    .metrics td{{width:25%;}}
    .label{{display:block;color:#64748B;font-size:12px;margin-bottom:2px;}}
    .value{{display:block;font-size:18px;font-weight:800;color:#0F172A;}}
    .pnl{{color:{pnl_color};}}
    ul{{margin:6px 0 0;padding-left:18px;}}
    li{{margin:4px 0;}}
    .risk{{font-size:12px;color:#64748B;border-top:1px solid #E5EAF2;margin-top:14px;padding-top:10px;}}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>{'冠捷科技盘前操作单' if kind == 'preopen' else '冠捷科技模拟盘日报'}</h1>
      <p class="muted">日期：{html_escape(date_text)} ｜ 本邮件由本地 Python 自动化生成</p>
      <span class="badge">冠捷科技 60,000</span>
      <p class="summary">组合当前权益 {money(total_equity)} 元，盈亏 <span class="pnl">{money(total_pnl)}</span> 元，收益率 <span class="pnl">{compact_pct(total_return)}</span>。</p>
    </div>
    <div class="card">
      <h2>组合概览</h2>
      <table class="metrics">
        <tr>
          <td><span class="label">初始本金</span><span class="value">{money(total_initial)}</span></td>
          <td><span class="label">当前权益</span><span class="value">{money(total_equity)}</span></td>
          <td><span class="label">组合盈亏</span><span class="value pnl">{money(total_pnl)}</span></td>
          <td><span class="label">组合收益率</span><span class="value pnl">{compact_pct(total_return)}</span></td>
        </tr>
      </table>
    </div>
    {''.join(cards)}
    <div class="card">
      <h2>执行口径</h2>
      {render_list_html(["当前邮件仅保留冠捷科技模拟盘提醒；山东玻纤只写入私密复盘账本。", "Python 自动化只负责拉行情、更新模拟盘和生成提示，不会真实下单。", "没有券商接口前，所有买卖仍需人工确认执行。"])}
      <p class="risk">风险提示：本文仅用于个人复盘、模拟盘记录和交易纪律验证，不构成任何投资建议。真实买卖前请以券商盘口、个人风险承受能力和止损纪律为准。</p>
    </div>
  </div>
</body>
</html>
"""


def send_with_smtp(to_addr: str, subject: str, body: str, html_body: str) -> bool:
    host = os.environ.get("PAPER_TRADE_SMTP_HOST") or os.environ.get("SMTP_HOST")
    user = os.environ.get("PAPER_TRADE_SMTP_USER") or os.environ.get("SMTP_USER")
    password = os.environ.get("PAPER_TRADE_SMTP_PASSWORD") or os.environ.get("SMTP_PASS")
    if not host or not user or not password:
        return False
    port = int(os.environ.get("PAPER_TRADE_SMTP_PORT") or os.environ.get("SMTP_PORT") or "465")
    secure = bool_env("PAPER_TRADE_SMTP_SECURE", bool_env("SMTP_SECURE", port == 465))
    reject_unauthorized = bool_env(
        "PAPER_TRADE_SMTP_TLS_REJECT_UNAUTHORIZED",
        bool_env("SMTP_TLS_REJECT_UNAUTHORIZED", True),
    )
    from_addr = os.environ.get("PAPER_TRADE_SMTP_FROM") or os.environ.get("ALERT_FROM") or user
    message = EmailMessage()
    message["From"] = from_addr
    message["To"] = to_addr
    message["Subject"] = subject
    message.set_content(body)
    message.add_alternative(html_body, subtype="html")
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()
    if not reject_unauthorized:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    if secure:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as smtp:
            smtp.login(user, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=context)
            smtp.login(user, password)
            smtp.send_message(message)
    return True


def main() -> int:
    load_env_files()
    parser = argparse.ArgumentParser(description="发送冠捷科技模拟盘日报")
    parser.add_argument("--date", default=datetime.now().date().isoformat())
    parser.add_argument("--to", default=os.environ.get("PAPER_TRADE_ALERT_TO") or os.environ.get("ALERT_TO") or "1181631922@qq.com")
    parser.add_argument("--kind", choices=["daily", "preopen"], default="daily", help="daily=收盘日报，preopen=盘前操作单")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    EMAIL_DIR.mkdir(parents=True, exist_ok=True)
    title = "冠捷科技盘前操作单" if args.kind == "preopen" else "冠捷科技模拟盘日报"
    subject = f"{title} {args.date}"
    body = build_body(args.date, args.kind)
    html_body = build_html_body(args.date, args.kind)
    suffix = "preopen_trade_plan" if args.kind == "preopen" else "paper_trade_email"
    out_file = EMAIL_DIR / f"{args.date}_{suffix}.txt"
    html_file = EMAIL_DIR / f"{args.date}_{suffix}.html"
    out_file.write_text(body, encoding="utf-8")
    html_file.write_text(html_body, encoding="utf-8")

    if args.dry_run:
        print(body)
        print(f"邮件正文已保存：{out_file}")
        print(f"HTML 正文已保存：{html_file}")
        return 0

    try:
        sent = send_with_smtp(args.to, subject, body, html_body)
    except Exception as error:
        print(f"SMTP 发送失败：{error}")
        print(f"邮件正文已保存：{out_file}")
        return 1
    if sent:
        print(f"SMTP 邮件已发送：{args.to}")
        print(f"邮件正文备份：{out_file}")
        print(f"HTML 正文备份：{html_file}")
        return 0
    print("未能发送邮件：缺少 SMTP_HOST/SMTP_USER/SMTP_PASS 配置。")
    print(f"邮件正文已保存：{out_file}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
