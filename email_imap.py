#!/usr/bin/env python3
"""
GitHub launch-code IMAP poller (Gmail).
Receives GitHub device/launch verification codes via iCloud Hide My Email
or direct delivery, polls Gmail IMAP, and extracts the code.

Reference email (2026-07-29):
  From:    GitHub <noreply@github.com>
  Subject: Your GitHub launch code
  Body:    Continue signing up for GitHub by entering the code below:
           19816756
  Link:    https://github.com/account_verifications/confirm/<uuid>/<code>
"""
from __future__ import annotations

import email
import imaplib
import re
import time
from dataclasses import dataclass
from email.header import decode_header
from typing import Optional

import config

# GitHub codes: 6-digit (device verification) OR 8-digit (account launch)
_CODE_RE = re.compile(r"\b(\d{6,8})\b")
# Device verification: "Verification code: 718188"
_DEVICE_CODE_RE = re.compile(r"Verification code[:\\s]+(\d{6})", re.I)
# Launch code: "Continue signing up ... code below: 19816756" / "launch code ... 19816756"
_LAUNCH_CODE_RE = re.compile(r"(?:launch code|entering the code|code below)[:\\s]+\D{0,30}(\d{6,8})", re.I)
# confirm link embeds the code as final path segment
_LINK_RE = re.compile(
    r"https://github\.com/account_verifications/confirm/"
    r"([0-9a-f-]+)/(\d{6,10})",
    re.I,
)
_FROM_GITHUB = "noreply@github.com"


@dataclass
class LaunchCode:
    code: str
    confirm_url: Optional[str] = None
    subject: str = ""
    to_addr: str = ""


def _decode(s) -> str:
    if s is None:
        return ""
    if isinstance(s, bytes):
        return s.decode("utf-8", errors="replace")
    parts = decode_header(s)
    out = []
    for frag, enc in parts:
        if isinstance(frag, bytes):
            out.append(frag.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(frag)
    return "".join(out)


def _extract(msg) -> Optional[LaunchCode]:
    subject = _decode(msg.get("Subject", ""))
    to_addr = _decode(msg.get("To", ""))
    body_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                try:
                    payload = part.get_payload(decode=True) or b""
                    body_parts.append(payload.decode("utf-8", errors="replace"))
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            body_parts.append(payload.decode("utf-8", errors="replace"))
        except Exception:
            pass
    body = "\n".join(body_parts)
    blob = subject + "\n" + body

    confirm_url = None
    code = None
    m = _LINK_RE.search(blob)
    if m:
        confirm_url = m.group(0)
        code = m.group(2)
    # Device verification: 6-digit "Verification code: 718188"
    if not code:
        for ctx in _DEVICE_CODE_RE.finditer(blob):
            code = ctx.group(1)
            break
    # Launch code: 8-digit "code below: 19816756"
    if not code:
        for ctx in _LAUNCH_CODE_RE.finditer(blob):
            code = ctx.group(1)
            break
    if not code:
        m2 = _CODE_RE.search(blob)
        if m2:
            code = m2.group(1)
    if not code:
        return None
    return LaunchCode(code=code, confirm_url=confirm_url, subject=subject, to_addr=to_addr)


def _connect() -> imaplib.IMAP4_SSL:
    if not config.IMAP_USER or not config.IMAP_APP_PASSWORD:
        raise RuntimeError("IMAP_USER / IMAP_APP_PASSWORD not set in .env")
    c = imaplib.IMAP4_SSL(config.IMAP_HOST)
    c.login(config.IMAP_USER, config.IMAP_APP_PASSWORD)
    c.select("INBOX")
    return c


def test_login() -> str:
    c = _connect()
    typ, data = c.status("INBOX", "(MESSAGES UNSEEN)")
    c.logout()
    return f"{typ} {data[0].decode() if data and data[0] else ''}"


def wait_code(
    target_email: str,
    timeout_s: int = 120,
    poll_s: int = 5,
    mark_seen: bool = True,
) -> Optional[LaunchCode]:
    """
    Poll Gmail for GitHub launch code addressed to target_email.
    Filters: FROM noreply@github.com + TO target + UNSEEN (then SINCE fallback).
    Prioritizes FRESH codes (last 60s) over older ones to avoid stale OTPs.
    """
    import datetime
    deadline = time.time() + timeout_s
    seen_ids = set()
    fresh_window_s = 120  # only accept codes from last 120s
    while time.time() < deadline:
        c = None
        try:
            c = _connect()
            # iCloud HME rewrites FROM to noreply_at_github_com_*@icloud.com
            # TO becomes "Hide My Email <target@icloud.com>"
            # SUBJECT always contains "launch code" — THE MOST RELIABLE SIGNAL
            criteria_list = [
                f'(SUBJECT "launch code")',  # PRIMARY: include SEEN + UNSEEN
                f'(UNSEEN SUBJECT "launch code")',
                f'(FROM "icloud.com" SUBJECT "launch")',
                f'(TO "{target_email}")',
                f'(FROM "{_FROM_GITHUB}" TO "{target_email}")',
                f'(UNSEEN FROM "{_FROM_GITHUB}")',
                f'(FROM "{_FROM_GITHUB}" SUBJECT "verify your device")',
            ]
            date_since = (datetime.datetime.now() - datetime.timedelta(minutes=30)).strftime('%d-%b-%Y')
            criteria_list_sinces = [
                f'(SINCE "{date_since}" SUBJECT "launch code")',
                f'(SINCE "{date_since}" UNSEEN SUBJECT "launch code")',
                f'(SINCE "{date_since}" FROM "icloud.com" SUBJECT "launch")',
                f'(SINCE "{date_since}" UNSEEN FROM "{_FROM_GITHUB}" TO "{target_email}")',
                f'(SINCE "{date_since}" FROM "{_FROM_GITHUB}" TO "{target_email}")',
                f'(SINCE "{date_since}" UNSEEN SUBJECT "verify your device")',
            ]
            for criteria in criteria_list_sinces + criteria_list:
                typ, data = c.search(None, criteria)
                if typ != "OK" or not data or not data[0]:
                    continue
                ids = data[0].split()
                for mid in reversed(ids[-20:]):  # newest last
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                    typ2, msgdata = c.fetch(mid, "(RFC822)")
                    if typ2 != "OK" or not msgdata or not msgdata[0]:
                        continue
                    raw = msgdata[0][1]
                    msg = email.message_from_bytes(raw)
                    try:
                        msg_date = email.utils.parsedate_to_datetime(msg.get("Date", ""))
                        if msg_date:
                            age_s = (datetime.datetime.now(tz=msg_date.tzinfo) - msg_date).total_seconds()
                            if age_s > fresh_window_s * 6:  # tolerate up to 12min old
                                continue
                    except Exception:
                        pass
                    to_hdr = _decode(msg.get("To", "")).lower()
                    subj = _decode(msg.get("Subject", "")).lower()
                    orig_to = _decode(msg.get("X-Original-To", "")).lower()
                    delivered = _decode(msg.get("Delivered-To", "")).lower()
                    envelope_to = _decode(msg.get("Envelope-To", "")).lower()
                    target_lo = target_email.lower()

                    target_found = (
                        target_lo in to_hdr
                        or target_lo in orig_to
                        or target_lo in delivered
                        or target_lo in envelope_to
                    )

                    if "launch code" in subj:
                        if not target_found:
                            continue
                    elif "verify your device" in subj:
                        if not target_found:
                            continue
                    else:
                        if not target_found:
                            continue

                    result = _extract(msg)
                    if result:
                        if mark_seen:
                            try:
                                c.store(mid, "+FLAGS", "\\Seen")
                            except Exception:
                                pass
                        c.logout()
                        return result
        except Exception as e:
            print(f"[imap] poll error: {type(e).__name__}: {e}")
        finally:
            if c:
                try:
                    c.logout()
                except Exception:
                    pass
        time.sleep(poll_s)
    return None


def fetch_device_code(target_email: str, timeout: int = 180) -> Optional[str]:
    """Alias for wait_code, returns code string or None."""
    lc = wait_code(target_email, timeout_s=timeout)
    return lc.code if lc else None


if __name__ == "__main__":
    import sys

    print("login:", test_login())
    if len(sys.argv) > 1:
        target = sys.argv[1]
        print(f"waiting code for {target} (60s)...")
        r = wait_code(target, timeout_s=60)
        print(r)