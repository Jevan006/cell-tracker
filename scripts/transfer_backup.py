"""
Transfer data between environments using the existing backup/restore endpoints.

Example:
  python scripts/transfer_backup.py \
    --source http://127.0.0.1:5000 \
    --target https://your-prod-app.example.com \
    --password your_admin_password \
    --out backup.json
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import mimetypes
import os
import sys
import urllib.parse
import urllib.request


def _login(base_url: str, password: str) -> urllib.request.OpenerDirector:
    login_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "login")
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    data = urllib.parse.urlencode({"password": password}).encode("utf-8")
    req = urllib.request.Request(login_url, data=data, method="POST")
    with opener.open(req) as resp:
        if resp.status not in (200, 302):
            raise RuntimeError(f"Login failed with status {resp.status}")
    return opener


def _download_backup(opener, base_url: str) -> bytes:
    backup_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "api/backup-data")
    with opener.open(backup_url) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Backup failed with status {resp.status}")
        return resp.read()


def _encode_multipart(field_name: str, filename: str, content: bytes):
    boundary = "----codex-boundary-9d5f6e"
    content_type = mimetypes.guess_type(filename)[0] or "application/json"
    body = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"{field_name}\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, boundary


def _upload_backup(opener, base_url: str, backup_bytes: bytes, filename: str):
    restore_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "api/restore-data")
    body, boundary = _encode_multipart("file", filename, backup_bytes)
    req = urllib.request.Request(restore_url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with opener.open(req) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
        if resp.status != 200:
            raise RuntimeError(f"Restore failed with status {resp.status}: {payload}")
        return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Transfer data via backup/restore endpoints.")
    parser.add_argument("--source", required=True, help="Source base URL (e.g. http://127.0.0.1:5000)")
    parser.add_argument("--target", required=True, help="Target base URL (e.g. https://prod.example.com)")
    parser.add_argument("--password", required=True, help="Admin password (used for both if specific passwords not provided)")
    parser.add_argument("--source-password", dest="source_password", help="Source admin password")
    parser.add_argument("--target-password", dest="target_password", help="Target admin password")
    parser.add_argument("--out", default="backup.json", help="Backup file path")
    args = parser.parse_args()

    source_password = args.source_password or args.password
    target_password = args.target_password or args.password

    source_opener = _login(args.source, source_password)
    backup_bytes = _download_backup(source_opener, args.source)
    with open(args.out, "wb") as f:
        f.write(backup_bytes)
    print(f"Backup saved to {args.out}")

    target_opener = _login(args.target, target_password)
    response = _upload_backup(target_opener, args.target, backup_bytes, os.path.basename(args.out))
    try:
        print(json.dumps(json.loads(response), indent=2))
    except json.JSONDecodeError:
        print(response)
    return 0


if __name__ == "__main__":
    sys.exit(main())
