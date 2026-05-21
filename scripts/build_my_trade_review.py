#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STOCK_DATA_DIR = ROOT / "data" / "stocks"
OUT_DIR = ROOT / "data" / "my" / "trade_reviews"

DEFAULT_STOCKS = [
    {"code": "000727", "name": "冠捷科技", "account_type": "独立模拟盘", "initial_cash": 60000.0},
    {"code": "605006", "name": "山东玻纤", "account_type": "独立模拟盘", "initial_cash": 60000.0},
]
LEGACY_STOCKS = [
    {"code": "000420", "name": "吉林化纤", "account_type": "历史兼容模拟盘", "initial_cash": 60000.0},
]

FIELDS = [
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


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        return list(csv.DictReader(file_obj))


def to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def money(value: Any) -> str:
    number = to_float(value)
    return "" if number is None else f"{number:.2f}"


def price(value: Any) -> str:
    number = to_float(value)
    return "" if number is None else f"{number:.3f}"


def pct(value: Any) -> str:
    number = to_float(value)
    return "" if number is None else f"{number:.2f}%"


def amount_wan(value: Any) -> str:
    number = to_float(value)
    return "" if number is None else f"{number:.2f}万"


def volume_lot(value: Any) -> str:
    number = to_float(value)
    return "" if number is None else f"{number:.0f}手"


def stock_dir(code: str) -> Path:
    return STOCK_DATA_DIR / code


def paper_dir(code: str) -> Path:
    return stock_dir(code) / "paper_trading"


def latest_daily_row(rows: list[dict[str, str]], date_text: str) -> dict[str, str] | None:
    candidates = [row for row in rows if row.get("date", "") <= date_text]
    return candidates[-1] if candidates else None


def journal_for_date(rows: list[dict[str, str]], date_text: str) -> list[dict[str, str]]:
    return [row for row in rows if row.get("date") == date_text]


def previous_equity(rows: list[dict[str, str]], date_text: str, initial_cash: float) -> float:
    previous = [row for row in rows if row.get("date", "") < date_text and row.get("equity_after")]
    if not previous:
        return initial_cash
    return to_float(previous[-1].get("equity_after")) or initial_cash


def last_equity_on_or_before(rows: list[dict[str, str]], date_text: str, initial_cash: float) -> float:
    previous = [row for row in rows if row.get("date", "") <= date_text and row.get("equity_after")]
    if not previous:
        return initial_cash
    return to_float(previous[-1].get("equity_after")) or initial_cash


def trading_hold_days(daily_rows: list[dict[str, str]], entry_date: str | None, date_text: str) -> str:
    if not entry_date:
        return "0"
    dates = [row.get("date") for row in daily_rows if row.get("date")]
    if entry_date not in dates:
        return ""
    return str(len([item for item in dates if entry_date <= item <= date_text]) - 1)


def strategy_line(strategy: dict[str, Any]) -> str:
    entry = strategy.get("entry_rules", {})
    gap = entry.get("next_open_gap_filter", {}).get("max_gap_up_from_signal_close_pct", 4.5)
    base = strategy.get("position_sizing", {}).get("base_position_pct", 60)
    return (
        f"等待接近20日低点、收阳站回5日线、换手达标，"
        f"次日高开不超过{gap}%时按{base}%计划仓位执行"
    )


def planned_stop_take(strategy: dict[str, Any]) -> tuple[str, str]:
    exits = strategy.get("exit_rules", {})
    stop = exits.get("initial_stop_loss_pct", 4)
    target = exits.get("target_take_profit_pct", 12)
    return f"买入价下方{stop}%", f"买入价上方{target}%"


def action_summary(journal_rows: list[dict[str, str]], account: dict[str, Any] | None) -> tuple[str, str]:
    if journal_rows:
        actions = [row.get("action", "").strip() for row in journal_rows if row.get("action")]
        reasons = [row.get("reason", "").strip() for row in journal_rows if row.get("reason")]
        return " / ".join(actions) or "已记录", "；".join(reasons)
    if not account:
        return "待建账", "尚未初始化该股票的模拟盘账户"
    if account.get("pending_order"):
        return "有买入计划", "等待次一交易日开盘过滤确认"
    if account.get("position"):
        return "持仓观察", "按止损、保护线和目标止盈执行"
    return "等待", "无买卖流水，继续等待收盘信号"


def trade_timing(journal_rows: list[dict[str, str]], account: dict[str, Any] | None) -> str:
    actions = " / ".join(row.get("action", "") for row in journal_rows)
    if "买入" in actions and "放弃" not in actions:
        return "次日开盘过滤后按模拟盘成交"
    if any(keyword in actions for keyword in ("卖出", "止损", "止盈", "减仓", "清仓")):
        return "盘中触发风控或收盘规则后模拟成交"
    if "生成买入计划" in actions or (account and account.get("pending_order")):
        return "收盘生成信号，下一交易日开盘过滤"
    if "等待" in actions:
        return "收盘后复核，未触发买卖"
    if account and account.get("position"):
        return "持仓中，盘中和尾盘只执行风控"
    return "无交易，等待下一次收盘信号"


def build_plan(account: dict[str, Any] | None, strategy: dict[str, Any], reference_price: float | None) -> str:
    if not account:
        return "先同步行情并初始化模拟盘，再纳入每日买卖点复盘。"
    pending = account.get("pending_order")
    if pending:
        gap = strategy.get("entry_rules", {}).get("next_open_gap_filter", {}).get("max_gap_up_from_signal_close_pct", 4.5)
        signal_close = to_float(pending.get("signal_close")) or 0
        max_open = signal_close * (1 + gap / 100)
        return f"{pending.get('execute_date')} 开盘不高于 {price(max_open)} 执行，否则放弃追买。"
    position = account.get("position")
    if position:
        return (
            f"持仓只盯风控：硬止损 {price(position.get('stop_price'))}，"
            f"保护触发 {price(position.get('protect_trigger_price'))}，目标止盈 {price(position.get('target_price'))}。"
        )
    if reference_price is None:
        return "空仓等待，不盘中追涨；收盘后重新计算信号。"
    return f"空仓等待，参考价 {price(reference_price)}；收盘后重新计算是否触发买点。"


def build_review_row(stock: dict[str, Any], date_text: str) -> dict[str, str]:
    code = stock["code"]
    name = stock["name"]
    paths = {
        "account": paper_dir(code) / "account.json",
        "journal": paper_dir(code) / "journal.csv",
        "strategy": stock_dir(code) / "active_strategy.json",
        "daily": stock_dir(code) / "daily_qfq_2y.csv",
        "quote": stock_dir(code) / "latest_quote.json",
    }
    account = load_json(paths["account"], None)
    strategy = load_json(paths["strategy"], {})
    journal_rows = read_csv(paths["journal"])
    today_journal = journal_for_date(journal_rows, date_text)
    daily_rows = read_csv(paths["daily"])
    latest_daily = latest_daily_row(daily_rows, date_text)
    quote_data = load_json(paths["quote"], {})

    initial_cash = to_float(account.get("initial_cash") if account else stock.get("initial_cash")) or 0.0
    reference_price = (
        to_float(today_journal[-1].get("price")) if today_journal else None
    ) or to_float((latest_daily or {}).get("close")) or to_float((quote_data or {}).get("current_price"))

    if account:
        cash = to_float(account.get("cash")) or 0.0
        shares = int(account.get("shares") or 0)
        equity = (to_float(today_journal[-1].get("equity_after")) if today_journal else None)
        if equity is None:
            if shares > 0:
                mark_price = reference_price or to_float(account.get("last_price")) or 0.0
                equity = cash + shares * mark_price
            else:
                equity = last_equity_on_or_before(journal_rows, date_text, initial_cash)
        prev_equity = previous_equity(journal_rows, date_text, initial_cash)
        daily_pnl = equity - prev_equity if latest_daily or today_journal else 0.0
        total_pnl = equity - initial_cash
        position_ratio = 0 if equity <= 0 or reference_price is None else shares * reference_price / equity * 100
    else:
        cash = initial_cash
        shares = 0
        equity = initial_cash
        daily_pnl = 0.0
        total_pnl = 0.0
        position_ratio = 0.0

    action, reason = action_summary(today_journal, account)
    gross_values = [to_float(row.get("gross")) or 0.0 for row in today_journal]
    fee_values = [to_float(row.get("fees")) or 0.0 for row in today_journal]
    buy_amount = sum(
        to_float(row.get("gross")) or 0.0
        for row in today_journal
        if "买入" in row.get("action", "") and "放弃" not in row.get("action", "")
    )
    sell_amount = sum(
        to_float(row.get("gross")) or 0.0
        for row in today_journal
        if any(keyword in row.get("action", "") for keyword in ("卖出", "止损", "止盈", "减仓", "清仓"))
    )
    position = account.get("position") if account else None
    stop_loss, take_profit = planned_stop_take(strategy)
    sell_point = "未持仓，暂无卖点"
    holding_days = "0"
    if position:
        stop_loss = price(position.get("stop_price"))
        take_profit = price(position.get("target_price"))
        sell_point = (
            f"硬止损 {stop_loss}；保护止损 {price(position.get('protect_stop_price'))}；"
            f"目标止盈 {take_profit}"
        )
        holding_days = trading_hold_days(daily_rows, position.get("entry_date"), date_text)

    buy_point = strategy_line(strategy) if strategy else "待补策略配置"
    if any("买入" in row.get("action", "") for row in today_journal):
        buy_point = f"今日按流水买入，成交参考价 {price(reference_price)}"
    if account and account.get("pending_order"):
        pending = account["pending_order"]
        buy_point = f"已生成买点：{pending.get('execute_date')} 开盘过滤执行"

    if not account:
        risk = "待补"
    elif position and reference_price is not None and to_float(position.get("stop_price")) and reference_price <= float(position["stop_price"]):
        risk = "高"
    elif account.get("pending_order") or position:
        risk = "中"
    else:
        risk = "低"

    return {
        "date": date_text,
        "code": code,
        "name": name,
        "account_type": stock.get("account_type", "独立模拟盘"),
        "action": action,
        "trade_timing": trade_timing(today_journal, account),
        "price": price(reference_price),
        "shares": str(sum(int(to_float(row.get("shares")) or 0) for row in today_journal)),
        "trade_amount": money(sum(gross_values)),
        "buy_amount": money(buy_amount),
        "sell_amount": money(sell_amount),
        "fees": money(sum(fee_values)),
        "position_cost": price(position.get("entry_price")) if position else "",
        "position_shares": str(shares),
        "position_ratio": pct(position_ratio),
        "cash_after": money(cash),
        "equity_after": money(equity),
        "daily_pnl": money(daily_pnl),
        "total_pnl": money(total_pnl),
        "total_return_pct": pct((total_pnl / initial_cash * 100) if initial_cash else 0),
        "buy_point": buy_point,
        "sell_point": sell_point,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "holding_days": holding_days,
        "signal": action,
        "reason": reason,
        "plan": build_plan(account, strategy, reference_price),
        "risk": risk,
        "user_confirmation": "待确认",
        "confirmation_source": "等你通知买卖点一致并提供截图后，再写入我的确认记录。",
        "quote_time": str((quote_data or {}).get("quote_time") or (latest_daily or {}).get("quote_time") or ""),
        "bar_status": str((latest_daily or {}).get("bar_status") or ""),
        "open": price((latest_daily or {}).get("open")),
        "high": price((latest_daily or {}).get("high")),
        "low": price((latest_daily or {}).get("low")),
        "close": price((latest_daily or {}).get("close")),
        "pct_change": pct((latest_daily or {}).get("pct_change")),
        "turnover_rate_pct": pct((latest_daily or {}).get("turnover_rate_pct")),
        "amount_wan": amount_wan((latest_daily or {}).get("amount_wan")),
        "volume_lot": volume_lot((latest_daily or {}).get("volume_lot")),
        "ma5": price((latest_daily or {}).get("ma5")),
        "ma10": price((latest_daily or {}).get("ma10")),
        "ma20": price((latest_daily or {}).get("ma20")),
        "high_20": price((latest_daily or {}).get("high_20")),
        "low_20": price((latest_daily or {}).get("low_20")),
        "data_source": str((latest_daily or {}).get("source") or (quote_data or {}).get("source") or "public_quote"),
        "note": "从本地模拟盘 account.json / journal.csv 自动生成；真实交易只在截图确认后单独写入。",
    }


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build private daily trade review CSV for my review tab.")
    parser.add_argument("--date", default=date.today().isoformat(), help="日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--include-legacy", action="store_true", help="同时写入已有吉林化纤历史模拟盘行")
    args = parser.parse_args()

    datetime.strptime(args.date, "%Y-%m-%d")
    stocks = [*DEFAULT_STOCKS, *(LEGACY_STOCKS if args.include_legacy else [])]
    rows = [build_review_row(stock, args.date) for stock in stocks]
    out_file = OUT_DIR / f"{args.date}.csv"
    write_rows(out_file, rows)
    print(f"wrote {len(rows)} trade review rows: {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
