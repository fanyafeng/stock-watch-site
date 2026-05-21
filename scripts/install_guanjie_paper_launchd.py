#!/usr/bin/env python3
from __future__ import annotations

import argparse
import plistlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = ROOT / "logs"

JOBS = [
    ("preopen", "com.yeguy.guanjie.paper.preopen", 9, 25, ["--stage", "preopen"]),
    ("intraday1000", "com.yeguy.guanjie.paper.intraday1000", 10, 0, ["--stage", "intraday"]),
    ("intraday1125", "com.yeguy.guanjie.paper.intraday1125", 11, 25, ["--stage", "intraday"]),
    ("intraday1430", "com.yeguy.guanjie.paper.intraday1430", 14, 30, ["--stage", "intraday"]),
    ("tail", "com.yeguy.guanjie.paper.tail", 14, 55, ["--stage", "tail"]),
    ("close", "com.yeguy.guanjie.paper.close", 15, 45, ["--stage", "close"]),
]


def plist_path(label: str) -> Path:
    return LAUNCH_AGENTS / f"{label}.plist"


def build_plist(label: str, hour: int, minute: int, args: list[str]) -> dict:
    return {
        "Label": label,
        "ProgramArguments": [
            "/usr/bin/python3",
            str(ROOT / "scripts" / "guanjie_paper_automation.py"),
            *args,
        ],
        "WorkingDirectory": str(ROOT),
        "StartCalendarInterval": [
            {"Weekday": weekday, "Hour": hour, "Minute": minute}
            for weekday in range(1, 6)
        ],
        "StandardOutPath": str(LOG_DIR / f"{label}.out.log"),
        "StandardErrorPath": str(LOG_DIR / f"{label}.err.log"),
        "RunAtLoad": False,
    }


def unload(label: str) -> None:
    path = plist_path(label)
    subprocess.run(["launchctl", "unload", str(path)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def install() -> None:
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for _, label, hour, minute, args in JOBS:
        unload(label)
        path = plist_path(label)
        with path.open("wb") as file_obj:
            plistlib.dump(build_plist(label, hour, minute, args), file_obj, sort_keys=False)
        subprocess.run(["launchctl", "load", str(path)], check=True)
        print(f"已安装：{label} -> {path}")


def uninstall() -> None:
    for _, label, _, _, _ in JOBS:
        unload(label)
        path = plist_path(label)
        if path.exists():
            path.unlink()
        print(f"已移除：{label}")


def main() -> None:
    parser = argparse.ArgumentParser(description="安装/卸载冠捷科技 + 山东玻纤双票模拟盘 launchd 定时任务")
    parser.add_argument("action", choices=["install", "uninstall"])
    args = parser.parse_args()
    if args.action == "install":
        install()
    else:
        uninstall()


if __name__ == "__main__":
    main()
