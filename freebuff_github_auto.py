#!/usr/bin/env python3
"""Freebuff token extractor — GitHub OAuth fully automated (generic paths).

Flow:
  1. Run extract_freebuff.py login (get auth_code link)
  2. Browser: Codebuff → Continue with GitHub → fill email+password
  3. GitHub sends device verification code to the account's inbox
     (iCloud HME + forwarding, or direct delivery)
  4. Auto-poll IMAP for GitHub verification code
  5. Enter code in browser → GitHub redirects back to Codebuff
  6. extract_freebuff.py polling detects auth → saves token

Usage:
  python3 freebuff_github_auto.py --email you@example.com --password 's3cret'

Prerequisites:
  - config.py + .env (IMAP credentials) in this repo
  - Playwright + chromium installed (pip install playwright && playwright install chromium)
"""
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Local imports (repo-relative, no hardcoded /root paths)
import config
from email_imap import wait_code

REPO_DIR = Path(__file__).resolve().parent
TOOLS_DIR = REPO_DIR / "freebuff_tools"
OUT_FILE = REPO_DIR / "auth_link.txt"


def start_extract_login():
    """Start extract_freebuff.py login in background, return (proc, link)."""
    out_file = str(OUT_FILE)
    # Remove old credentials so it generates a new fingerprint
    cred_file = TOOLS_DIR / "freebuff_credentials.json"
    if cred_file.exists():
        cred_file.unlink()

    proc = subprocess.Popen(
        ["python3", "-u", "extract_freebuff.py", "login"],
        cwd=str(TOOLS_DIR),
        stdout=open(out_file, "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    # Wait for the login URL to appear
    print("⏳ Waiting for extract_freebuff.py to generate login link...")
    for i in range(30):
        time.sleep(2)
        try:
            content = open(out_file).read()
            m = re.search(r"(https://www\.codebuff\.com/login\?auth_code=\S+)", content)
            if m:
                link = m.group(1).strip()
                print(f"✅ Got login link: {link[:80]}...")
                return proc, link
        except Exception:
            pass
    print("❌ Timeout waiting for login link")
    proc.kill()
    return None, None


def main():
    parser = argparse.ArgumentParser(description="Freebuff GitHub OAuth auto")
    parser.add_argument("--email", required=True, help="GitHub email")
    parser.add_argument("--password", required=True, help="GitHub password")
    args = parser.parse_args()

    print("🚀 Freebuff GitHub OAuth Auto")
    print(f"   Email: {args.email}")
    print(f"   IMAP: {config.IMAP_USER}")
    print()

    proc, login_url = start_extract_login()
    if not proc:
        sys.exit(1)

    print(f"\n📋 LOGIN_LINK={login_url}")
    print(f"📋 EMAIL={args.email}")
    print(f"📋 PASSWORD={args.password}")
    print(f"📋 PROC_PID={proc.pid}")

    # Parent (orchestrator / Hermes / worker) drives the browser with these vars;
    # this process polls IMAP for the GitHub device-verification code.
    print("\n" + "=" * 60)
    print("⏳ Waiting 15s for GitHub to send verification email...")
    print("=" * 60)
    time.sleep(15)

    code = wait_code(args.email, timeout_s=180)
    if code:
        print(f"\n📋 VERIFICATION_CODE={code.code}")
    else:
        print("\n❌ No code found. Manual intervention needed.")
        proc.terminate()
        sys.exit(1)

    # Keep polling extract_freebuff.py until it finishes
    print("\n⏳ Waiting for extract_freebuff.py to detect auth...")
    for i in range(60):
        time.sleep(5)
        try:
            content = open(str(OUT_FILE)).read()
            if "authToken" in content or "凭证已保存" in content or "登录成功" in content:
                print("✅ Token extracted!")
                m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", content)
                if m:
                    print(f"📋 TOKEN={m.group(1)}")
                break
        except Exception:
            pass

    try:
        proc.terminate()
    except Exception:
        pass


if __name__ == "__main__":
    main()