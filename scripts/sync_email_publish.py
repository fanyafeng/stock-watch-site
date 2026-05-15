#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EmailPublishSyncError(Exception):
    pass


def parse_date(value: str | None) -> dt.date:
    if value:
        return dt.date.fromisoformat(value)
    return dt.date.today()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def run_command(command: list[str], *, dry_run: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command))
    if dry_run:
        return subprocess.CompletedProcess(command, 0, "", "")
    completed = subprocess.run(command, cwd=ROOT, text=True)
    if check and completed.returncode != 0:
        raise EmailPublishSyncError(f"命令执行失败：{' '.join(command)}")
    return completed


def run_python(script: str, args: list[str], *, dry_run: bool = False) -> None:
    run_command([sys.executable, f"scripts/{script}", *args], dry_run=dry_run)


def current_branch(*, dry_run: bool = False) -> str:
    if dry_run:
        return "main"
    completed = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    branch = completed.stdout.strip()
    if not branch or branch == "HEAD":
        raise EmailPublishSyncError("当前不是普通分支，请使用 --branch 指定要 push 的分支")
    return branch


def git_config_value(key: str) -> str:
    completed = subprocess.run(
        ["git", "config", "--get", key],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def ensure_git_identity(*, dry_run: bool = False) -> None:
    if dry_run:
        return
    if not git_config_value("user.name"):
        run_command(["git", "config", "user.name", "stock-watch-bot"])
    if not git_config_value("user.email"):
        run_command(["git", "config", "user.email", "stock-watch-bot@users.noreply.github.com"])


def existing(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        key = rel(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def source_data_paths(date_text: str) -> list[Path]:
    paths: list[Path] = []
    for data_type in ("picks", "holdings", "posts", "comments"):
        paths.extend((ROOT / "data" / "sources").glob(f"*/{data_type}/{date_text}.csv"))
    return paths


def stageable_paths(date_text: str, *, include_source_config: bool = False) -> list[Path]:
    """Return the allowlist for data that may be committed before email sending.

    明文报告目录 build/tmp 和最终产物 dist 不在 allowlist 中；个人持仓原始 CSV 也不提交，
    只同步 encrypted/my 与 src/data/my_positions_index.json。
    """

    paths = [
        ROOT / "data" / "daily" / date_text,
        ROOT / "data" / "reports.json",
        ROOT / "data" / "dashboard.json",
        ROOT / "data" / "dashboards" / f"{date_text}.json",
        ROOT / "encrypted" / "articles" / f"daily_{date_text}.json",
        ROOT / "encrypted" / "my" / f"{date_text}.json",
        ROOT / "public" / "media" / date_text,
        ROOT / "src" / "data" / "reports.json",
        ROOT / "src" / "data" / "dashboard.json",
        ROOT / "src" / "data" / "dashboards" / f"{date_text}.json",
        ROOT / "src" / "data" / "my_positions_index.json",
        *source_data_paths(date_text),
    ]
    if include_source_config:
        paths.append(ROOT / "data" / "source_config.json")
    return existing(paths)


def has_staged_changes(*, dry_run: bool = False) -> bool:
    if dry_run:
        return True
    completed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    return completed.returncode != 0


def sync_report_data(args: argparse.Namespace, date_text: str) -> None:
    if not args.skip_market_flow:
        run_python(
            "fetch_market_flow.py",
            ["--date", date_text, "--mode", "loose"],
            dry_run=args.dry_run,
        )

    generate_args = ["--all", "--date", date_text]
    if args.strict_extra:
        generate_args.append("--strict-extra")
    if args.loose_source_data:
        generate_args.append("--loose-source-data")
    run_python("generate_report.py", generate_args, dry_run=args.dry_run)

    run_python("encrypt_article.py", ["--all", "--date", date_text], dry_run=args.dry_run)

    if not args.skip_my_positions:
        run_python(
            "encrypt_my_positions.py",
            ["--date", date_text, "--mode", args.my_positions_mode],
            dry_run=args.dry_run,
        )

    sync_args: list[str] = []
    if args.allow_missing_payloads:
        sync_args.append("--allow-missing-payloads")
    run_python("sync_reports_to_astro.py", sync_args, dry_run=args.dry_run)

    if not args.skip_build:
        run_command(["npm", "run", "build"], dry_run=args.dry_run)


def commit_and_push(args: argparse.Namespace, date_text: str) -> None:
    paths = stageable_paths(date_text, include_source_config=args.include_source_config)
    if not paths:
        print(f"没有找到 {date_text} 可同步的数据文件")
        return

    ensure_git_identity(dry_run=args.dry_run)
    run_command(["git", "add", "--", *[rel(path) for path in paths]], dry_run=args.dry_run)

    if not has_staged_changes(dry_run=args.dry_run):
        print("没有新的数据需要提交，跳过 commit/push")
        return

    message = args.message or f"chore: sync email data for {date_text}"
    run_command(["git", "commit", "-m", message], dry_run=args.dry_run)
    if args.no_push:
        print("已提交本地数据，因 --no-push 跳过远程同步")
        return

    branch = args.branch or current_branch(dry_run=args.dry_run)
    run_command(["git", "push", args.remote, branch], dry_run=args.dry_run)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare encrypted site data before sending email links, then commit and push the data allowlist.",
    )
    parser.add_argument("--date", help="日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--loose-source-data", action="store_true", help="来源 picks/holdings 缺失时不报错，用暂无数据占位")
    parser.add_argument("--strict-extra", action="store_true", help="大盘、时间线、帖子/评论等可选 CSV 缺失时直接报错")
    parser.add_argument("--skip-market-flow", action="store_true", help="跳过指数主力净流分时拉取")
    parser.add_argument("--skip-my-positions", action="store_true", help="跳过我的持仓加密")
    parser.add_argument("--my-positions-mode", choices=["strict", "loose"], default="loose", help="我的持仓数据缺失处理方式，默认 loose")
    parser.add_argument("--allow-missing-payloads", action="store_true", help="同步报告索引时跳过缺失密文 payload 的报告")
    parser.add_argument("--skip-build", action="store_true", help="跳过 npm run build 验证")
    parser.add_argument("--include-source-config", action="store_true", help="同时提交 data/source_config.json")
    parser.add_argument("--message", help="自定义提交信息")
    parser.add_argument("--remote", default="origin", help="git remote，默认 origin")
    parser.add_argument("--branch", help="git push 目标分支，默认当前分支")
    parser.add_argument("--no-push", action="store_true", help="只提交本地，不 push")
    parser.add_argument("--allow-existing-staged", action="store_true", help="允许把调用前已经 staged 的改动一起提交")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的命令，不修改文件或 git")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        date_text = parse_date(args.date).isoformat()
        if has_staged_changes(dry_run=False) and not args.allow_existing_staged:
            raise EmailPublishSyncError("检测到调用前已有 staged 改动。请先提交/取消暂存，或显式传入 --allow-existing-staged")
        sync_report_data(args, date_text)
        commit_and_push(args, date_text)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
