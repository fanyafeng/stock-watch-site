#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import ssl
import subprocess
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EMAIL_TO = "1181631922@qq.com"
PAPER_STOCKS = [
    {"code": "000727", "name": "冠捷科技", "start_date": "2026-05-19", "initial_cash": 60000.0},
    {"code": "605006", "name": "山东玻纤", "start_date": "2026-05-21", "initial_cash": 60000.0},
]


def stock_dir(code: str) -> Path:
    return ROOT / "data" / "stocks" / code


def paper_dir(code: str) -> Path:
    return stock_dir(code) / "paper_trading"


def stock_paths(code: str) -> dict[str, Path]:
    base = stock_dir(code)
    paper = paper_dir(code)
    return {
        "stock": base,
        "paper": paper,
        "account": paper / "account.json",
        "journal": paper / "journal.csv",
        "signal_dir": paper / "signals",
        "latest_signal": paper / "latest_signal.md",
        "strategy": base / "active_strategy.json",
        "quote": base / "latest_quote.json",
        "daily": base / "daily_qfq_2y.csv",
    }


def symbol_for_code(code: str) -> str:
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_journal_tail(path: Path, limit: int = 8) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as file_obj:
        rows = list(csv.DictReader(file_obj))
    return rows[-limit:]


def read_daily_tail(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8", newline="") as file_obj:
        rows = list(csv.DictReader(file_obj))
    return rows[-1] if rows else None


def run_command(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return result.returncode, result.stdout


def fetch_realtime_quote(code: str, fallback_name: str) -> dict[str, Any]:
    symbol = symbol_for_code(code)
    request = urllib.request.Request(
        f"https://qt.gtimg.cn/q={symbol}",
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
    )
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(request, timeout=15, context=context) as response:
        text = response.read().decode("gbk", errors="ignore")
    fields = text.split('="', 1)[1].rsplit('"', 1)[0].split("~")

    def pick(index: int) -> str:
        return fields[index] if index < len(fields) else ""

    def to_float(value: str) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    quote_time = pick(30)
    quote_time_text = quote_time
    if len(quote_time) == 14:
        try:
            quote_time_text = datetime.strptime(quote_time, "%Y%m%d%H%M%S").isoformat(sep=" ")
        except ValueError:
            quote_time_text = quote_time
    return {
        "code": pick(2) or code,
        "name": pick(1) or fallback_name,
        "quote_time": quote_time_text,
        "current_price": to_float(pick(3)),
        "previous_close": to_float(pick(4)),
        "open": to_float(pick(5)),
        "high": to_float(pick(33)),
        "low": to_float(pick(34)),
        "pct_change": to_float(pick(32)),
    }


def money(value: float | int | None) -> str:
    if value is None:
        return "待补充"
    return f"{float(value):,.2f}"


def pct(value: float | int | None) -> str:
    if value is None:
        return "待补充"
    return f"{float(value):.2f}%"


def price(value: float | int | None) -> str:
    if value is None:
        return "待补充"
    return f"{float(value):.3f}"


def latest_wait_reason(journal_path: Path) -> str:
    for item in reversed(read_journal_tail(journal_path, limit=20)):
        reason = item.get("reason", "").strip()
        if reason:
            return reason
    return "暂无收盘信号记录，继续等待下一次收盘确认。"


def strategy_entry_checklist(strategy: dict[str, Any]) -> list[str]:
    entry = strategy.get("entry_rules", {})
    gap = entry.get("next_open_gap_filter", {}).get("max_gap_up_from_signal_close_pct", 4.5)
    return [
        f"换手率不低于 {entry.get('min_turnover_rate_pct', 0.5)}%。",
        f"信号日涨幅不超过 {entry.get('max_signal_day_pct_change', 9)}%，不追过热长阳。",
        f"低点靠近 20 日低点区域，阈值约为 20 日低点的 {entry.get('near_20d_low_multiplier', 1.03)} 倍以内。",
        "收盘必须收阳，并重新站回 5 日线。",
        f"收盘价不能跌破长期趋势底，需高于 MA60 的 {entry.get('trend_floor', {}).get('close_gt_ma60_multiplier', 0.92)} 倍附近。",
        f"RSI14 不能过热，需低于 {entry.get('max_rsi14', 75)}。",
        f"若收盘生成买入计划，次日开盘高于信号收盘价 {gap}% 以上则放弃追买。",
    ]


def operation_order_lines(
    *,
    stock: dict[str, Any],
    account: dict[str, Any],
    strategy: dict[str, Any],
    quote: dict[str, Any] | None,
    paths: dict[str, Path],
) -> list[str]:
    position = account.get("position")
    pending = account.get("pending_order")
    base_position = strategy.get("position_sizing", {}).get("base_position_pct", 60)
    current_price = quote.get("current_price") if quote else account.get("last_price")
    lines = [
        "## 盘前操作单",
        "",
        f"- 标的：{stock['name']}({stock['code']})",
        f"- 当前参考价：{price(current_price)}",
        f"- 当前仓位：{account.get('shares', 0)} 股",
    ]
    if pending:
        max_open = pending["signal_close"] * (
            1 + strategy["entry_rules"]["next_open_gap_filter"]["max_gap_up_from_signal_close_pct"] / 100
        )
        lines.extend(
            [
                "- 今日动作：等待开盘价确认后执行买入计划。",
                f"- 计划仓位：账户权益的 {base_position}%。",
                f"- 买入条件：开盘价 <= {price(max_open)}，否则取消，不追高。",
                f"- 信号收盘价：{price(pending['signal_close'])}",
                f"- 信号原因：{pending.get('reason', '收盘信号已确认')}",
                "- 买入后纪律：跌破初始止损卖出；浮盈触发保护后抬高止损；到目标价止盈。",
            ]
        )
    elif position:
        lines.extend(
            [
                "- 今日动作：持仓风控，不新增仓位。",
                f"- 持仓股数：{account.get('shares', 0)} 股。",
                f"- 买入价：{price(position.get('entry_price'))}",
                f"- 硬止损：{price(position.get('stop_price'))}",
                f"- 保护触发：{price(position.get('protect_trigger_price'))}",
                f"- 保护止损：{price(position.get('protect_stop_price'))}",
                f"- 目标止盈：{price(position.get('target_price'))}",
                f"- 动态回撤保护：{price(position.get('trail_stop_price') or None)}",
                "- 卖出纪律：触及硬止损/保护止损/目标止盈，按模拟规则记录卖出。",
            ]
        )
    else:
        lines.extend(
            [
                "- 今日动作：空仓等待，不买入。",
                f"- 计划仓位：若后续收盘生成买入计划，次日最多使用账户权益的 {base_position}%。",
                f"- 暂不买入原因：{latest_wait_reason(paths['journal'])}",
                "- 禁止动作：不盘中追涨，不因为单日拉升临时买入。",
                "- 下一步：等待收盘后重新计算是否生成次日开盘买入计划。",
                "- 买入触发条件：",
                *(f"  - {item}" for item in strategy_entry_checklist(strategy)),
            ]
        )
    return lines


def current_position_lines(account: dict[str, Any], quote: dict[str, Any] | None) -> list[str]:
    last_price = quote.get("current_price") if quote else account.get("last_price")
    equity = account.get("cash", 0) + account.get("shares", 0) * (last_price or account.get("last_price", 0))
    position_pct = 0 if equity <= 0 else account.get("shares", 0) * (last_price or 0) / equity * 100
    return [
        f"- 现金：{money(account.get('cash', 0))} 元",
        f"- 持仓：{account.get('shares', 0)} 股",
        f"- 仓位：{pct(position_pct)}",
        f"- 参考价格：{price(last_price)}",
        f"- 当前权益：{money(equity)} 元",
        f"- 浮动盈亏：{money(equity - account.get('initial_cash', 0))} 元",
        f"- 浮动收益率：{pct((equity / account.get('initial_cash', 1) - 1) * 100)}",
    ]


def build_plan_lines(account: dict[str, Any], strategy: dict[str, Any], quote: dict[str, Any] | None, stage: str) -> list[str]:
    position = account.get("position")
    pending = account.get("pending_order")
    lines: list[str] = []
    if pending:
        max_open = pending["signal_close"] * (
            1 + strategy["entry_rules"]["next_open_gap_filter"]["max_gap_up_from_signal_close_pct"] / 100
        )
        lines.extend(
            [
                "## 买入计划",
                "",
                f"- 信号日期：{pending['created_date']}",
                f"- 执行日期：{pending['execute_date']}",
                f"- 信号收盘价：{price(pending['signal_close'])}",
                f"- 允许最高开盘价：{price(max_open)}",
                f"- 计划仓位：账户权益的 {strategy.get('position_sizing', {}).get('base_position_pct', 60)}%",
                "- 执行规则：如果开盘价不高于允许最高开盘价，则按计划仓位买入；高开超过 4.5% 则取消。",
            ]
        )
    elif position:
        lines.extend(
            [
                "## 持仓风控线",
                "",
                f"- 买入日期：{position['entry_date']}",
                f"- 买入价：{price(position['entry_price'])}",
                f"- 硬止损价：{price(position['stop_price'])}",
                f"- 保护触发价：{price(position['protect_trigger_price'])}",
                f"- 保护止损价：{price(position['protect_stop_price'])}",
                f"- 目标止盈价：{price(position['target_price'])}",
                f"- 当前是否已触发保护：{'是' if position.get('protect_triggered') else '否'}",
                f"- 动态回撤保护价：{price(position.get('trail_stop_price') or None)}",
            ]
        )
        if quote and quote.get("current_price") is not None:
            now = quote["current_price"]
            alerts = []
            if now <= position["stop_price"]:
                alerts.append("当前价已触及硬止损线，需要卖出。")
            if not position.get("protect_triggered") and now >= position["protect_trigger_price"]:
                alerts.append("当前价已触及保护触发价，需要把止损抬到保护止损价。")
            if now >= position["target_price"]:
                alerts.append("当前价已触及目标止盈价，需要卖出。")
            if alerts:
                lines.extend(["", "## 盘中触发提醒", ""])
                lines.extend(f"- {item}" for item in alerts)
    else:
        lines.extend(
            [
                "## 当前计划",
                "",
                "- 无持仓。",
                "- 无待执行买入计划。",
                "- 不追涨，不盘中临时低吸；等待收盘后重新计算信号。",
            ]
        )

    if stage == "close":
        lines.extend(
            [
                "",
                "## 收盘任务",
                "",
                "- 已同步最新日线并更新模拟盘账户。",
                "- 明日计划以本文件最后生成结果为准。",
            ]
        )
    return lines


def write_signal(
    *,
    stage: str,
    stock: dict[str, Any],
    account: dict[str, Any],
    strategy: dict[str, Any],
    quote: dict[str, Any] | None,
    command_output: str = "",
) -> Path:
    paths = stock_paths(stock["code"])
    paths["signal_dir"].mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    quote_time = quote.get("quote_time") if quote else "未拉取"
    stage_title = {
        "preopen": "盘前确认",
        "intraday": "盘中盯盘",
        "tail": "尾盘风控",
        "close": "收盘策略",
    }.get(stage, stage)
    lines = [
        f"# {stock['name']}({stock['code']})模拟盘提示 - {stage_title}",
        "",
        f"- 生成时间：{now.isoformat(sep=' ', timespec='seconds')}",
        f"- 行情时间：{quote_time}",
        f"- 模拟区间：{account.get('start_date')} ~ {account.get('end_date')}",
        f"- 模拟本金：{money(account.get('initial_cash'))} 元",
        f"- 策略：{strategy.get('strategy_name')} / {strategy.get('strategy_id')}",
        "",
        "## 账户状态",
        "",
    ]
    lines.extend(current_position_lines(account, quote))
    lines.extend([""])
    lines.extend(operation_order_lines(stock=stock, account=account, strategy=strategy, quote=quote, paths=paths))
    lines.extend([""])
    lines.extend(build_plan_lines(account, strategy, quote, stage))

    journal_tail = read_journal_tail(paths["journal"])
    if journal_tail:
        lines.extend(["", "## 最近流水", ""])
        for item in journal_tail:
            lines.append(
                f"- {item.get('date')}｜{item.get('action')}｜价格 {item.get('price')}｜股数 {item.get('shares')}｜原因：{item.get('reason')}"
            )

    daily_tail = read_daily_tail(paths["daily"])
    if daily_tail:
        lines.extend(
            [
                "",
                "## 最新日线状态",
                "",
                f"- 日期：{daily_tail.get('date')}",
                f"- 状态：{daily_tail.get('bar_status')}",
                f"- 开高低收：{daily_tail.get('open')} / {daily_tail.get('high')} / {daily_tail.get('low')} / {daily_tail.get('close')}",
                f"- 涨跌幅：{daily_tail.get('pct_change')}%",
                f"- 换手率：{daily_tail.get('turnover_rate_pct')}%",
                f"- MA5/MA10/MA20：{daily_tail.get('ma5')} / {daily_tail.get('ma10')} / {daily_tail.get('ma20')}",
            ]
        )

    if command_output.strip():
        lines.extend(["", "## 脚本输出摘要", "", "```text", command_output.strip()[-3000:], "```"])

    lines.extend(
        [
            "",
            "## 执行口径",
            "",
            "- Python 自动化只负责拉行情、更新模拟盘和生成提示，不会真实下单。",
            "- 没有券商接口前，所有买卖仍需人工确认执行。",
            "- 盘中实时数据来自腾讯公网报价，可能有延迟；关键交易以券商盘口为准。",
        ]
    )
    target = paths["signal_dir"] / f"{now.strftime('%Y%m%d_%H%M%S')}_{stage}.md"
    text = "\n".join(lines) + "\n"
    target.write_text(text, encoding="utf-8")
    paths["latest_signal"].write_text(text, encoding="utf-8")
    return target


def ensure_account(stock: dict[str, Any], end_date: str) -> None:
    paths = stock_paths(stock["code"])
    if paths["account"].exists():
        return
    code, output = run_command(
        [
            sys.executable,
            "scripts/update_guanjie_paper_trade.py",
            "--code",
            stock["code"],
            "--name",
            stock["name"],
            "--reset",
            "--init-only",
            "--initial-cash",
            str(stock.get("initial_cash", 60000.0)),
            "--start-date",
            stock.get("start_date", end_date),
            "--end-date",
            end_date,
        ]
    )
    if code != 0:
        raise SystemExit(f"{stock['name']}账户初始化失败：\n{output}")


def process_stock(stage: str, stock: dict[str, Any], as_of: str | None, end_date: str) -> Path:
    paths = stock_paths(stock["code"])
    ensure_account(stock, end_date)
    strategy = load_json(paths["strategy"], {})
    command_output = ""
    quote: dict[str, Any] | None = None
    if stage in {"preopen", "intraday", "tail"}:
        quote = fetch_realtime_quote(stock["code"], stock["name"])
    if stage == "close":
        end = as_of or date.today().isoformat()
        code, output = run_command(
            [
                sys.executable,
                "scripts/fetch_stock_history.py",
                "--code",
                stock["code"],
                "--name",
                stock["name"],
                "--window-years",
                "2",
                "--count",
                "900",
                "--end",
                end,
            ]
        )
        command_output += output
        if code == 0:
            update_cmd = [
                sys.executable,
                "scripts/update_guanjie_paper_trade.py",
                "--code",
                stock["code"],
                "--name",
                stock["name"],
                "--start-date",
                stock.get("start_date", end),
                "--end-date",
                end_date,
            ]
            if as_of:
                update_cmd.extend(["--as-of", as_of])
            code2, output2 = run_command(update_cmd)
            command_output += "\n" + output2
            if code2 != 0:
                command_output += f"\n{stock['name']}模拟盘更新失败，已保留原账户。"
        else:
            command_output += f"\n{stock['name']}行情同步失败，已保留原账户。"
        quote = load_json(paths["quote"], None)

    account = load_json(paths["account"], None)
    if not account:
        raise SystemExit(f"{stock['name']}模拟盘账户不存在，且自动初始化失败。")
    return write_signal(stage=stage, stock=stock, account=account, strategy=strategy, quote=quote, command_output=command_output)


def send_stage_email(kind: str, mail_date: str) -> None:
    code, output = run_command(
        [
            sys.executable,
            "scripts/send_guanjie_paper_email.py",
            "--date",
            mail_date,
            "--kind",
            kind,
            "--to",
            EMAIL_TO,
        ]
    )
    if code != 0:
        print(output)
        print("邮件未能直接发出，邮件正文已由发送脚本备份到 data/stocks/paper_trading/emails。")
    else:
        print(output)


def sync_private_review(mail_date: str) -> None:
    steps = [
        [sys.executable, "scripts/build_my_trade_review.py", "--date", mail_date],
        [sys.executable, "scripts/encrypt_my_positions.py", "--date", mail_date, "--mode", "loose"],
    ]
    for command in steps:
        code, output = run_command(command)
        print(output)
        if code != 0:
            print(f"私密复盘同步失败：{' '.join(command)}")


def run_stage(stage: str, as_of: str | None, end_date: str) -> list[Path]:
    signal_paths: list[Path] = []
    for stock in PAPER_STOCKS:
        signal_paths.append(process_stock(stage, stock, as_of, end_date))

    if stage == "preopen":
        mail_date = as_of or date.today().isoformat()
        send_stage_email("preopen", mail_date)

    if stage == "close":
        mail_date = as_of or date.today().isoformat()
        sync_private_review(mail_date)
        send_stage_email("daily", mail_date)
    return signal_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="冠捷科技 + 山东玻纤双票模拟盘 Python 自动化提示")
    parser.add_argument(
        "--stage",
        required=True,
        choices=["preopen", "intraday", "tail", "close"],
        help="preopen=盘前确认，intraday=盘中盯盘，tail=尾盘风控，close=收盘策略",
    )
    parser.add_argument("--as-of", help="收盘阶段处理指定日期")
    parser.add_argument("--end-date", default="2026-05-29", help="模拟盘结束日期")
    args = parser.parse_args()
    targets = run_stage(args.stage, args.as_of, args.end_date)
    for target in targets:
        print(f"已生成提示：{target}")


if __name__ == "__main__":
    main()
