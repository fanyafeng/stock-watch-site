#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STOCK_DIR = ROOT / "data" / "stocks" / "000727"
DAILY_FILE = STOCK_DIR / "daily_qfq_2y.csv"
STRATEGY_FILE = STOCK_DIR / "active_strategy.json"
PAPER_DIR = STOCK_DIR / "paper_trading"
ACCOUNT_FILE = PAPER_DIR / "account.json"
JOURNAL_FILE = PAPER_DIR / "journal.csv"


def configure_stock_paths(code: str) -> None:
    global STOCK_DIR, DAILY_FILE, STRATEGY_FILE, PAPER_DIR, ACCOUNT_FILE, JOURNAL_FILE
    STOCK_DIR = ROOT / "data" / "stocks" / code
    DAILY_FILE = STOCK_DIR / "daily_qfq_2y.csv"
    STRATEGY_FILE = STOCK_DIR / "active_strategy.json"
    PAPER_DIR = STOCK_DIR / "paper_trading"
    ACCOUNT_FILE = PAPER_DIR / "account.json"
    JOURNAL_FILE = PAPER_DIR / "journal.csv"


def to_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def read_rows(path: Path, include_intraday: bool = True) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as file_obj:
        for raw in csv.DictReader(file_obj):
            if raw.get("bar_status") == "intraday" and not include_intraday:
                continue
            row = {
                "date": raw["date"],
                "dt": datetime.strptime(raw["date"], "%Y-%m-%d").date(),
                "open": to_float(raw.get("open")),
                "high": to_float(raw.get("high")),
                "low": to_float(raw.get("low")),
                "close": to_float(raw.get("close")),
                "pre_close": to_float(raw.get("pre_close")),
                "pct_change": to_float(raw.get("pct_change")),
                "turnover_rate_pct": to_float(raw.get("turnover_rate_pct")),
                "volume_lot": to_float(raw.get("volume_lot")),
                "bar_status": raw.get("bar_status", "closed"),
                "quote_time": raw.get("quote_time", ""),
            }
            rows.append(row)
    add_indicators(rows)
    return rows


def add_indicators(rows: list[dict[str, Any]]) -> None:
    closes: list[float] = []
    lows: list[float] = []
    for index, row in enumerate(rows):
        closes.append(row["close"])
        lows.append(row["low"])
        row["prev_close"] = rows[index - 1]["close"] if index > 0 else row["pre_close"] or row["close"]
        for window in (5, 10, 20, 60):
            start = max(0, index - window + 1)
            prev_start = max(0, index - window)
            row[f"ma{window}"] = mean(closes[start : index + 1])
            row[f"prev_low{window}"] = min(lows[prev_start:index]) if index > 0 else row["low"]

        if index >= 14:
            gains: list[float] = []
            losses: list[float] = []
            for cursor in range(index - 13, index + 1):
                change = rows[cursor]["close"] - rows[cursor - 1]["close"]
                gains.append(max(change, 0.0))
                losses.append(max(-change, 0.0))
            avg_gain = mean(gains)
            avg_loss = mean(losses)
            row["rsi14"] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
        else:
            row["rsi14"] = 50.0


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_holiday_calendar(rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    sell_t3: set[str] = set()
    buy_t1: set[str] = set()
    for index in range(len(rows) - 1):
        gap_days = (rows[index + 1]["dt"] - rows[index]["dt"]).days
        if gap_days <= 3:
            continue
        buy_t1.add(rows[index]["date"])
        if index - 2 >= 0:
            sell_t3.add(rows[index - 2]["date"])
    return {"sell_t3": sell_t3, "buy_t1": buy_t1}


def get_next_trading_date(rows: list[dict[str, Any]], index: int) -> str | None:
    if index + 1 >= len(rows):
        next_date = rows[index]["dt"]
        while True:
            next_date = next_date + timedelta(days=1)
            if next_date.weekday() < 5:
                return next_date.isoformat()
    return rows[index + 1]["date"]


def has_entry_signal(row: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str]:
    entry = config["entry_rules"]
    if row["turnover_rate_pct"] < entry["min_turnover_rate_pct"]:
        return False, "换手率不足"
    if row["pct_change"] > entry["max_signal_day_pct_change"]:
        return False, "信号日涨幅过大，不追"
    if row["low"] > row["prev_low20"] * entry["near_20d_low_multiplier"]:
        return False, "未接近20日低点"
    if not (row["close"] > row["open"] and row["close"] > row["ma5"]):
        return False, "未收阳并站回5日线"
    if row["close"] <= row["ma60"] * entry["trend_floor"]["close_gt_ma60_multiplier"]:
        return False, "跌破长期趋势底"
    if row["rsi14"] >= entry["max_rsi14"]:
        return False, "RSI过热"
    return True, "接近20日低点后收阳并重新站回5日线"


def fee_config() -> dict[str, float]:
    return {
        "commission_rate": 0.0003,
        "commission_min": 5.0,
        "stamp_tax_rate_sell_only": 0.0005,
        "transfer_fee_rate": 0.00001,
    }


def buy_fee(gross: float, fees: dict[str, float]) -> float:
    return max(gross * fees["commission_rate"], fees["commission_min"]) + gross * fees["transfer_fee_rate"]


def sell_fee(gross: float, fees: dict[str, float]) -> float:
    return (
        max(gross * fees["commission_rate"], fees["commission_min"])
        + gross * fees["transfer_fee_rate"]
        + gross * fees["stamp_tax_rate_sell_only"]
    )


def max_buyable_shares(cash: float, price: float, fees: dict[str, float]) -> int:
    shares = int(cash // price // 100 * 100)
    while shares > 0:
        gross = shares * price
        if gross + buy_fee(gross, fees) <= cash:
            return shares
        shares -= 100
    return 0


def base_position_cash(account: dict[str, Any], row: dict[str, Any], config: dict[str, Any]) -> float:
    sizing = config.get("position_sizing", {})
    base_pct = to_float(sizing.get("base_position_pct", 60)) / 100
    base_pct = min(max(base_pct, 0), 1)
    account_equity = equity(account, row["close"])
    return min(account["cash"], account_equity * base_pct)


def init_account(args: argparse.Namespace, fees: dict[str, float]) -> dict[str, Any]:
    code = args.code.zfill(6)
    name = args.name
    return {
        "account_id": f"{code}_paper_{args.start_date.replace('-', '')}_{args.end_date.replace('-', '')}",
        "code": code,
        "name": name,
        "status": "active",
        "start_date": args.start_date,
        "end_date": args.end_date,
        "initial_cash": args.initial_cash,
        "cash": args.initial_cash,
        "shares": 0,
        "position": None,
        "pending_order": None,
        "processed_dates": [],
        "fee_model": {
            "commission_rate": fees["commission_rate"],
            "commission_min": fees["commission_min"],
            "stamp_tax_rate_sell_only": fees["stamp_tax_rate_sell_only"],
            "transfer_fee_rate": fees["transfer_fee_rate"],
            "note": "佣金按万三、单笔最低5元；印花税卖出0.05%；过户费按成交额0.001%双向估算。",
        },
        "last_update": None,
        "notes": [
            f"只模拟{name}({code})，不与其他股票混用账户。",
            "A股T+1：买入当天不触发卖出，次一交易日起处理止损/止盈。",
            "日线OHLC无法确定盘中先后顺序时，按保守口径优先处理止损。",
        ],
    }


def load_account(args: argparse.Namespace, fees: dict[str, float]) -> dict[str, Any]:
    if ACCOUNT_FILE.exists() and not args.reset:
        return load_json(ACCOUNT_FILE)
    return init_account(args, fees)


def append_journal(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "date",
        "action",
        "price",
        "shares",
        "gross",
        "fees",
        "cash_after",
        "shares_after",
        "equity_after",
        "reason",
    ]
    exists = JOURNAL_FILE.exists()
    with JOURNAL_FILE.open("a", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def journal_item(
    *,
    date: str,
    action: str,
    price: float,
    shares: int,
    gross: float,
    fees: float,
    cash_after: float,
    shares_after: int,
    equity_after: float,
    reason: str,
) -> dict[str, Any]:
    return {
        "date": date,
        "action": action,
        "price": round(price, 3),
        "shares": shares,
        "gross": round(gross, 2),
        "fees": round(fees, 2),
        "cash_after": round(cash_after, 2),
        "shares_after": shares_after,
        "equity_after": round(equity_after, 2),
        "reason": reason,
    }


def equity(account: dict[str, Any], close_price: float) -> float:
    return account["cash"] + account["shares"] * close_price


def execute_pending_buy(account: dict[str, Any], row: dict[str, Any], config: dict[str, Any], fees: dict[str, float]) -> dict[str, Any] | None:
    pending = account.get("pending_order")
    if not pending or pending.get("execute_date") != row["date"]:
        return None
    account["pending_order"] = None
    max_gap = config["entry_rules"]["next_open_gap_filter"]["max_gap_up_from_signal_close_pct"] / 100
    if row["open"] > pending["signal_close"] * (1 + max_gap):
        return journal_item(
            date=row["date"],
            action="放弃买入",
            price=row["open"],
            shares=0,
            gross=0,
            fees=0,
            cash_after=account["cash"],
            shares_after=account["shares"],
            equity_after=equity(account, row["close"]),
            reason="次日高开超过4.5%，不追买",
        )

    buy_cash = base_position_cash(account, row, config)
    shares = max_buyable_shares(buy_cash, row["open"], fees)
    if shares <= 0:
        return journal_item(
            date=row["date"],
            action="买入失败",
            price=row["open"],
            shares=0,
            gross=0,
            fees=0,
            cash_after=account["cash"],
            shares_after=account["shares"],
            equity_after=equity(account, row["close"]),
            reason="现金不足以买入一手",
        )

    gross = shares * row["open"]
    fee = buy_fee(gross, fees)
    account["cash"] -= gross + fee
    account["shares"] += shares
    exit_rules = config["exit_rules"]
    account["position"] = {
        "entry_date": row["date"],
        "entry_price": row["open"],
        "entry_shares": shares,
        "entry_cash_cost": gross + fee,
        "stop_price": row["open"] * (1 - exit_rules["initial_stop_loss_pct"] / 100),
        "protect_trigger_price": row["open"] * (1 + exit_rules["protect_trigger_profit_pct"] / 100),
        "protect_stop_price": row["open"] * (1 + exit_rules["protect_stop_profit_pct"] / 100),
        "target_price": row["open"] * (1 + exit_rules["target_take_profit_pct"] / 100),
        "protect_triggered": False,
        "peak_high": row["high"],
        "trail_stop_price": 0,
        "calendar_sleeve_cash": 0,
        "calendar_sleeve_shares": 0,
    }
    return journal_item(
        date=row["date"],
        action="买入",
        price=row["open"],
        shares=shares,
        gross=gross,
        fees=fee,
        cash_after=account["cash"],
        shares_after=account["shares"],
        equity_after=equity(account, row["close"]),
        reason=f"{pending['reason']}；按基础仓位{config.get('position_sizing', {}).get('base_position_pct', 60)}%执行",
    )


def sell_shares(account: dict[str, Any], row: dict[str, Any], price: float, shares: int, reason: str, fees: dict[str, float], action: str = "卖出") -> dict[str, Any]:
    shares = min(shares, account["shares"])
    gross = shares * price
    fee = sell_fee(gross, fees)
    account["cash"] += gross - fee
    account["shares"] -= shares
    if account["shares"] == 0:
        account["position"] = None
    return journal_item(
        date=row["date"],
        action=action,
        price=price,
        shares=shares,
        gross=gross,
        fees=fee,
        cash_after=account["cash"],
        shares_after=account["shares"],
        equity_after=equity(account, row["close"]),
        reason=reason,
    )


def process_position(account: dict[str, Any], row: dict[str, Any], index: int, rows: list[dict[str, Any]], config: dict[str, Any], fees: dict[str, float]) -> list[dict[str, Any]]:
    position = account.get("position")
    if not position:
        return []
    if row["date"] == position["entry_date"]:
        return []

    output: list[dict[str, Any]] = []
    exit_rules = config["exit_rules"]
    active_stop = position["stop_price"]
    if position["protect_triggered"]:
        active_stop = max(active_stop, position["protect_stop_price"], position.get("trail_stop_price", 0))

    if row["low"] <= active_stop:
        output.append(sell_shares(account, row, active_stop, account["shares"], "硬止损/保护止损", fees))
        return output

    if not position["protect_triggered"] and row["high"] >= position["protect_trigger_price"]:
        position["protect_triggered"] = True
        output.append(
            journal_item(
                date=row["date"],
                action="触发保护线",
                price=position["protect_trigger_price"],
                shares=0,
                gross=0,
                fees=0,
                cash_after=account["cash"],
                shares_after=account["shares"],
                equity_after=equity(account, row["close"]),
                reason="浮盈达到+4%，保护止损抬到+1.5%，启用动态保护",
            )
        )

    if row["high"] >= position["target_price"]:
        output.append(sell_shares(account, row, position["target_price"], account["shares"], "目标止盈达到+12%", fees))
        return output

    entry_index = next((cursor for cursor, item in enumerate(rows) if item["date"] == position["entry_date"]), index)
    hold_days = index - entry_index
    if position["protect_triggered"] and row["close"] < row["ma10"] * exit_rules["protected_ma10_close_break"]["threshold_multiplier"]:
        output.append(sell_shares(account, row, row["close"], account["shares"], "保护后收盘跌破MA10", fees))
        return output

    if not position["protect_triggered"] and row["close"] < row["ma20"] * exit_rules["pre_protect_ma20_backstop"]["threshold_multiplier"]:
        output.append(sell_shares(account, row, row["close"], account["shares"], "未触发保护前跌破MA20缓冲", fees))
        return output

    if hold_days >= exit_rules["max_hold_trading_days"]:
        output.append(sell_shares(account, row, row["close"], account["shares"], "到达10个交易日", fees))
        return output

    calendar = build_holiday_calendar(rows)
    overlay = config.get("calendar_overlay", {})
    sleeve_pct = to_float(overlay.get("sleeve_position_pct", 0)) / 100
    if overlay.get("enabled") and sleeve_pct > 0 and row["date"] in calendar["sell_t3"] and position["calendar_sleeve_shares"] == 0:
        sleeve_shares = int(position["entry_shares"] * sleeve_pct // 100 * 100)
        if sleeve_shares > 0:
            output.append(sell_shares(account, row, row["close"], sleeve_shares, "长假前T-3卖出50%袖子仓", fees, action="节前减仓"))
            if account.get("position"):
                account["position"]["calendar_sleeve_shares"] = sleeve_shares
                account["position"]["calendar_sleeve_cash"] += output[-1]["gross"] - output[-1]["fees"]
    elif overlay.get("enabled") and row["date"] in calendar["buy_t1"] and position["calendar_sleeve_cash"] > 0:
        cash_for_buyback = min(account["cash"], position["calendar_sleeve_cash"])
        shares = max_buyable_shares(cash_for_buyback, row["close"], fees)
        if shares > 0:
            gross = shares * row["close"]
            fee = buy_fee(gross, fees)
            account["cash"] -= gross + fee
            account["shares"] += shares
            position["calendar_sleeve_cash"] = 0
            position["calendar_sleeve_shares"] = 0
            output.append(
                journal_item(
                    date=row["date"],
                    action="节前买回",
                    price=row["close"],
                    shares=shares,
                    gross=gross,
                    fees=fee,
                    cash_after=account["cash"],
                    shares_after=account["shares"],
                    equity_after=equity(account, row["close"]),
                    reason="长假前T-1买回袖子仓",
                )
            )

    if account.get("position"):
        position["peak_high"] = max(position["peak_high"], row["high"])
        if position["protect_triggered"]:
            drawdown_pct = exit_rules["dynamic_trailing_stop"]["peak_high_drawdown_pct"] / 100
            position["trail_stop_price"] = max(position.get("trail_stop_price", 0), position["peak_high"] * (1 - drawdown_pct))
    return output


def maybe_create_signal(account: dict[str, Any], row: dict[str, Any], index: int, rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any] | None:
    if account.get("position") or account.get("pending_order"):
        return None
    ok, reason = has_entry_signal(row, config)
    if not ok:
        return journal_item(
            date=row["date"],
            action="等待",
            price=row["close"],
            shares=0,
            gross=0,
            fees=0,
            cash_after=account["cash"],
            shares_after=account["shares"],
            equity_after=equity(account, row["close"]),
            reason=f"无入场信号：{reason}",
        )
    execute_date = get_next_trading_date(rows, index)
    if not execute_date or execute_date > account["end_date"]:
        return journal_item(
            date=row["date"],
            action="出现信号但不下单",
            price=row["close"],
            shares=0,
            gross=0,
            fees=0,
            cash_after=account["cash"],
            shares_after=account["shares"],
            equity_after=equity(account, row["close"]),
        reason="下一交易日超出模拟盘结束日期",
        )
    account["pending_order"] = {
        "created_date": row["date"],
        "execute_date": execute_date,
        "signal_close": row["close"],
        "reason": reason,
    }
    return journal_item(
        date=row["date"],
        action="生成买入计划",
        price=row["close"],
        shares=0,
        gross=0,
        fees=0,
        cash_after=account["cash"],
        shares_after=account["shares"],
        equity_after=equity(account, row["close"]),
        reason=f"{reason}；计划 {execute_date} 开盘买入",
    )


def update_account(args: argparse.Namespace) -> dict[str, Any]:
    fees = fee_config()
    config = load_json(STRATEGY_FILE)
    rows = read_rows(DAILY_FILE, include_intraday=True)
    account = load_account(args, fees)
    if args.init_only:
        if rows:
            latest = rows[-1]
            account["last_price"] = latest["close"]
            account["last_equity"] = round(equity(account, latest["close"]), 2)
            account["floating_pnl"] = round(account["last_equity"] - account["initial_cash"], 2)
            account["floating_return_pct"] = round((account["last_equity"] / account["initial_cash"] - 1) * 100, 4)
        account["last_update"] = datetime.now().isoformat(timespec="seconds")
        write_json(ACCOUNT_FILE, account)
        print(json.dumps({"status": "initialized", "account": account}, ensure_ascii=False, indent=2))
        return account
    rows_by_date = {row["date"]: (index, row) for index, row in enumerate(rows)}
    as_of = args.as_of or rows[-1]["date"]
    if as_of not in rows_by_date:
        raise SystemExit(f"没有找到 {as_of} 的{args.name}日线数据，请先同步行情。")
    if as_of < account["start_date"] or as_of > account["end_date"]:
        raise SystemExit(f"{as_of} 不在模拟盘区间 {account['start_date']} ~ {account['end_date']} 内。")
    if as_of in account["processed_dates"] and not args.force:
        print(json.dumps({"status": "skipped", "reason": f"{as_of} 已处理", "account": account}, ensure_ascii=False, indent=2))
        return account
    if as_of in account["processed_dates"] and args.force:
        account["processed_dates"].remove(as_of)

    index, row = rows_by_date[as_of]
    journal_rows: list[dict[str, Any]] = []
    pending_action = execute_pending_buy(account, row, config, fees)
    if pending_action:
        journal_rows.append(pending_action)
    journal_rows.extend(process_position(account, row, index, rows, config, fees))
    signal_action = maybe_create_signal(account, row, index, rows, config)
    if signal_action:
        journal_rows.append(signal_action)

    account["processed_dates"].append(as_of)
    account["last_update"] = datetime.now().isoformat(timespec="seconds")
    account["last_price"] = row["close"]
    account["last_equity"] = round(equity(account, row["close"]), 2)
    account["floating_pnl"] = round(account["last_equity"] - account["initial_cash"], 2)
    account["floating_return_pct"] = round((account["last_equity"] / account["initial_cash"] - 1) * 100, 4)
    write_json(ACCOUNT_FILE, account)
    append_journal(journal_rows)
    print(json.dumps({"status": "updated", "as_of": as_of, "journal": journal_rows, "account": account}, ensure_ascii=False, indent=2))
    return account


def main() -> None:
    parser = argparse.ArgumentParser(description="更新冠捷科技模拟盘账户")
    parser.add_argument("--code", default="000727", help="股票代码，默认 000727")
    parser.add_argument("--name", default="冠捷科技", help="股票名称，默认 冠捷科技")
    parser.add_argument("--as-of", help="处理指定日期，默认处理最新行情日期")
    parser.add_argument("--initial-cash", type=float, default=60000.0)
    parser.add_argument("--start-date", default="2026-05-19")
    parser.add_argument("--end-date", default="2026-05-29")
    parser.add_argument("--reset", action="store_true", help="重置模拟盘账户")
    parser.add_argument("--init-only", action="store_true", help="只初始化账户，不处理任何交易日期")
    parser.add_argument("--force", action="store_true", help="允许重复处理指定日期；仅用于修正当天记录")
    args = parser.parse_args()
    args.code = args.code.zfill(6)
    configure_stock_paths(args.code)
    update_account(args)


if __name__ == "__main__":
    main()
