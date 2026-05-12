#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS_FILE = ROOT / "data" / "reports.json"
ASTRO_REPORTS_FILE = ROOT / "src" / "data" / "reports.json"
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


def main() -> int:
    try:
        reports = load_reports()
        validate_payloads(reports)
        sorted_reports = sorted(reports, key=lambda item: (item.get("date", ""), item.get("source", "")), reverse=True)
        ASTRO_REPORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ASTRO_REPORTS_FILE.write_text(json.dumps(sorted_reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"synced: {ASTRO_REPORTS_FILE}")
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
