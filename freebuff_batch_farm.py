#!/usr/bin/env python3
"""Batch Freebuff token farming via GitHub OAuth — generic, config-driven.

Fixes vs naive loop:
- Reads token from extract_freebuff.py OUTPUT (regex on UUID), not from
  credentials.json (which extract_freebuff.py OVERWRITES on every run).
- Appends each token to tokens.txt immediately.
- Skips accounts already farmed (emails seen in freebuff_credentials.json
  or listed in skipped.txt).

Usage:
  python3 freebuff_batch_farm.py                 # farm all pending accounts
  python3 freebuff_batch_farm.py --limit 5       # farm max 5 pending accounts
  python3 freebuff_batch_farm.py --skip a@b.c    # also skip this email

Prerequisites:
  - .env with IMAP_* credentials (see .env.example)
  - accounts.txt in repo root: email:password:username (one per line)
  - Playwright chromium installed
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_DIR))

import config
from email_imap import wait_code

TOOLS_DIR = REPO_DIR / "freebuff_tools"
TOKENS_FILE = config.TOKENS_FILE
ACCOUNTS_FILE = config.ACCOUNTS_FILE
SKIPPED_FILE = REPO_DIR / "skipped.txt"

TOKEN_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

os.environ.setdefault("DISPLAY", config.DISPLAY)

from playwright.sync_api import sync_playwright


def parse_accounts(path):
    accounts = []
    if not Path(path).exists():
        print(f"✗ {path} not found — buat dulu (format: email:password:username)")
        return accounts
    for line in Path(path).read_text().strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            parts = line.split("|")
        elif ":" in line:
            parts = line.split(":")
        else:
            continue
        email = parts[0].strip()
        password = parts[1].strip() if len(parts) > 1 else ""
        username = parts[2].strip() if len(parts) > 2 else ""
        accounts.append({"email": email, "password": password, "username": username})
    return accounts


def get_existing_tokens():
    if TOKENS_FILE.exists():
        return [t.strip() for t in TOKENS_FILE.read_text().strip().splitlines() if t.strip()]
    return []


def farm_one(playwright, account):
    email = account["email"]
    password = account["password"]
    username = account.get("username", "")
    log_path = REPO_DIR / "logs" / f"freebuff_{username or 'anon'}.txt"
    log_path.parent.mkdir(exist_ok=True)

    print(f"\n{'='*60}\nFarming: {username} | {email}\n{'='*60}")

    # 1) Start extract_freebuff.py login in background
    proc = subprocess.Popen(
        ["python3", "-u", "extract_freebuff.py", "login"],
        cwd=str(TOOLS_DIR),
        stdout=open(log_path, "w"),
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    # Wait for auth_code link
    auth_code = None
    for _ in range(20):
        time.sleep(2)
        if log_path.exists():
            content = log_path.read_text()
            m = re.search(r"auth_code=([A-Za-z0-9_-]+)", content)
            if m:
                auth_code = m.group(1)
                break
    if not auth_code:
        print(f"❌ No auth_code generated for {username}")
        proc.kill()
        return None

    login_url = f"https://www.codebuff.com/login?auth_code={auth_code}"
    print(f"Auth code: {auth_code}")

    # 2) Browser automation
    browser = playwright.chromium.launch(headless=config.HEADLESS)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    try:
        # Navigate to Codebuff login
        page.goto(login_url, timeout=30000)
        time.sleep(2)

        # Click "Continue with GitHub"
        page.get_by_role("button", name="Continue with GitHub").click()
        time.sleep(3)

        # Fill GitHub login form
        page.wait_for_selector('input[name="login"]', timeout=15000)
        page.fill('input[name="login"]', email)
        page.fill('input[name="password"]', password)
        page.click('input[type="submit"], button[type="submit"]')
        time.sleep(5)

        # Check for device verification
        page_content = page.content()

        if "verification code" in page_content.lower() or "device verification" in page_content.lower():
            print(f"📱 Device verification required. Polling IMAP for {email}...")

            result = wait_code(
                target_email=email,
                timeout_s=120,
                poll_s=5,
                mark_seen=True,
            )

            if result:
                code = result.code
                print(f"✅ IMAP code: {code}")

                for selector in ['input[placeholder="XXXXXX"]', 'input[name="otp"]', 'input[id="otp"]', 'input[autocomplete="off"]']:
                    try:
                        page.fill(selector, code, timeout=3000)
                        break
                    except Exception:
                        continue

                page.click('button:has-text("Verify")')
                time.sleep(5)
            else:
                print(f"❌ No IMAP code found for {email}")
                browser.close()
                proc.kill()
                return None

        # Check for Authorize page
        page_content = page.content()

        if "authorize" in page_content.lower():
            print(f"🔐 Authorize page found. Clicking Authorize...")
            try:
                page.click('button:has-text("Authorize")')
                time.sleep(5)
            except Exception:
                try:
                    page.click('input[name="authorize"]')
                    time.sleep(5)
                except Exception:
                    print(f"⚠️ Could not find authorize button")

        print(f"Final URL: {page.url}")

        # 3) Wait for token from extract_freebuff.py output
        print(f"⏳ Waiting for token from extract_freebuff.py...")
        token = None
        deadline = time.time() + 120
        while time.time() < deadline:
            if log_path.exists():
                content = log_path.read_text()
                m = TOKEN_RE.search(content)
                if m and ("登录成功" in content or "authToken" in content):
                    token = m.group(1)
                    break
            time.sleep(3)

        if token:
            print(f"✅ Token: {token}")
            TOKENS_FILE.parent.mkdir(exist_ok=True)
            with TOKENS_FILE.open("a") as f:
                f.write(token + "\n")
            return token
        else:
            print(f"❌ No token received")
            if log_path.exists():
                print(f"Log tail:\n{log_path.read_text()[-500:]}")
            return None

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        if log_path.exists():
            print(f"Log:\n{log_path.read_text()[-500:]}")
        return None
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            proc.kill()
            proc.wait()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description="Batch freebuff token farming via GitHub OAuth")
    ap.add_argument("--limit", type=int, default=0, help="max accounts to farm (0 = all)")
    ap.add_argument("--skip", action="append", default=[], help="skip this email (repeatable)")
    args = ap.parse_args()

    accounts = parse_accounts(ACCOUNTS_FILE)
    if not accounts:
        print("✗ Tidak ada akun untuk difarm. Cek accounts.txt")
        sys.exit(1)

    existing_tokens = get_existing_tokens()
    print(f"Existing tokens: {len(existing_tokens)}")
    print(f"Accounts in file: {len(accounts)}")

    # Skip: CLI --skip + freebuff_credentials.json emails + skipped.txt
    farmed_emails = set(args.skip)
    cred_path = TOOLS_DIR / "freebuff_credentials.json"
    if cred_path.exists():
        try:
            creds = json.loads(cred_path.read_text())
            for v in creds.values():
                if isinstance(v, dict):
                    farmed_emails.add(v.get("email", ""))
        except Exception:
            pass
    if SKIPPED_FILE.exists():
        for line in SKIPPED_FILE.read_text().splitlines():
            farmed_emails.add(line.strip())

    to_farm = [a for a in accounts if a["email"] not in farmed_emails]
    if args.limit > 0:
        to_farm = to_farm[: args.limit]
    print(f"To farm: {len(to_farm)}")
    for a in to_farm:
        print(f"  → {a['username']} | {a['email']}")

    if not to_farm:
        print("Nothing to farm!")
        return

    results = []
    with sync_playwright() as p:
        for i, acc in enumerate(to_farm):
            print(f"\n[{i+1}/{len(to_farm)}] Processing {acc['username']}")
            token = farm_one(p, acc)
            results.append({"account": acc["email"], "username": acc["username"], "token": token})

            if i < len(to_farm) - 1:
                print(f"⏳ Cooldown 10s...")
                time.sleep(10)

    # Summary
    print(f"\n{'='*60}\nBATCH SUMMARY\n{'='*60}")
    success = [r for r in results if r["token"]]
    failed = [r for r in results if not r["token"]]
    print(f"✅ Success: {len(success)}/{len(results)}")
    print(f"❌ Failed: {len(failed)}/{len(results)}")
    for r in results:
        status = "✅" if r["token"] else "❌"
        print(f"  {status} {r['username']} | {r['token'] or 'FAILED'}")

    # Deduplicate + rewrite tokens file
    all_tokens = list(dict.fromkeys(get_existing_tokens() + [r["token"] for r in success if r["token"]]))
    TOKENS_FILE.parent.mkdir(exist_ok=True)
    with TOKENS_FILE.open("w") as f:
        f.write("\n".join(all_tokens) + "\n")
    print(f"\nAll tokens ({len(all_tokens)}):")
    print(",".join(all_tokens))
    print(f"Saved to {TOKENS_FILE}")


if __name__ == "__main__":
    main()