#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS_FILE = ROOT / "data" / "reports.json"
DASHBOARD_FILE = ROOT / "data" / "dashboard.json"
DASHBOARDS_DIR = ROOT / "data" / "dashboards"
ASTRO_REPORTS_FILE = ROOT / "src" / "data" / "reports.json"
ASTRO_DASHBOARD_FILE = ROOT / "src" / "data" / "dashboard.json"
ASTRO_DASHBOARDS_DIR = ROOT / "src" / "data" / "dashboards"
ENCRYPTED_DIR = ROOT / "encrypted" / "articles"


class SyncError(Exception):
    pass


def load_reports() -> list[dict]:
    if not REPORTS_FILE.exists():
        REPORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORTS_FILE.write_text("[]\n", encoding="utf-8")
        print(f"created empty report index: {REPORTS_FILE}")
        return []
    data = json.loads(REPORTS_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SyncError(f"{REPORTS_FILE} 必须是数组")
    return data


def validate_payloads(reports: list[dict]) -> None:
    for report in reports:
        slug = report.get("slug")
        if not slug:
            raise SyncError("reports.json 中存在缺少 slug 的报告")
        payload = ENCRYPTED_DIR / f"{slug}.json"
        if not payload.exists():
            raise SyncError(f"缺少密文 payload：{payload}")


def sync_dashboard() -> None:
    if DASHBOARD_FILE.exists():
        dashboard = json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
    else:
        dashboard = {}
        print(f"dashboard not found, created empty dashboard: {DASHBOARD_FILE}")
    ASTRO_DASHBOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    ASTRO_DASHBOARD_FILE.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"synced: {ASTRO_DASHBOARD_FILE}")

    ASTRO_DASHBOARDS_DIR.mkdir(parents=True, exist_ok=True)
    if DASHBOARDS_DIR.exists():
        for source_file in DASHBOARDS_DIR.glob("*.json"):
            data = json.loads(source_file.read_text(encoding="utf-8"))
            target_file = ASTRO_DASHBOARDS_DIR / source_file.name
            target_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"synced: {target_file}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync public dashboard data and encrypted report index to Astro.")
    parser.add_argument("--dashboard-only", action="store_true", help="只同步公开看板数据，不校验密文文章 payload")
    parser.add_argument("--allow-missing-payloads", action="store_true", help="同步 reports.json 时跳过缺失密文 payload 的报告")
    args = parser.parse_args()
    try:
        reports = load_reports()
        if args.dashboard_only:
            sync_dashboard()
            return 0
        if args.allow_missing_payloads:
            reports = [report for report in reports if (ENCRYPTED_DIR / f"{report.get('slug')}.json").exists()]
        else:
            validate_payloads(reports)
        sorted_reports = sorted(reports, key=lambda item: (item.get("date", ""), item.get("source", "")), reverse=True)
        ASTRO_REPORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ASTRO_REPORTS_FILE.write_text(json.dumps(sorted_reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"synced: {ASTRO_REPORTS_FILE}")
        sync_dashboard()
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
