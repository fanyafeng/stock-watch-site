#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "data" / "source_config.json"
TMP_DIR = ROOT / "build" / "tmp"
ENCRYPTED_DIR = ROOT / "encrypted" / "articles"
ITERATIONS = 200000


class EncryptError(Exception):
    pass


def build_password_for_date(date_obj: dt.date) -> str:
    reverse_month = 12 - date_obj.month
    password = f"xiaofan{reverse_month:02d}{date_obj.day:02d}"
    return password


def parse_date(value: str | None) -> dt.date:
    if value:
        return dt.date.fromisoformat(value)
    return dt.date.today()


def load_source_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        raise EncryptError(f"未找到来源配置文件：{CONFIG_FILE}")
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def resolve_sources(config: dict[str, Any], source: str | None, all_sources: bool) -> list[dict[str, Any]]:
    enabled = {item["id"]: item for item in config.get("sources", []) if item.get("enabled", True)}
    if source:
        if source not in enabled:
            raise EncryptError(f"未知或未启用的来源：{source}")
        return [enabled[source]]
    ids = list(enabled.keys()) if all_sources else config.get("default_sources", [])
    resolved = [enabled[source_id] for source_id in ids if source_id in enabled]
    if not resolved:
        raise EncryptError("没有可加密的 enabled 来源")
    return resolved


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


def encrypt_article(source_id: str, date_obj: dt.date) -> Path:
    date_text = date_obj.isoformat()
    input_file = TMP_DIR / f"{source_id}_{date_text}.html"
    if not input_file.exists():
        raise EncryptError(f"未找到明文报告 {input_file}，请先运行 generate_report.py")

    password = build_password_for_date(date_obj)
    plaintext = input_file.read_bytes()
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = derive_key(password, salt)
    ciphertext = AESGCM(key).encrypt(iv, plaintext, None)
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
    out_file = ENCRYPTED_DIR / f"{source_id}_{date_text}.json"
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"encrypted: {out_file}")
    return out_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Encrypt generated report HTML for static publishing.")
    parser.add_argument("--source", help="只加密指定来源")
    parser.add_argument("--date", help="报告日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--all", action="store_true", help="加密所有 enabled 来源")
    args = parser.parse_args()

    try:
        date_obj = parse_date(args.date)
        config = load_source_config()
        sources = resolve_sources(config, args.source, args.all)
        for source in sources:
            encrypt_article(source["id"], date_obj)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
