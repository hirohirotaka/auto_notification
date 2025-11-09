#!/usr/bin/env python3
"""Persistent poller: reuse Playwright browser and check two weeks every POLL_INTERVAL seconds.

Run this directly (recommended in systemd service). It imports the notify helper
from `app.py` and reuses a single Playwright page for efficiency.

Usage: set environment variables (SMTP_*, FROM_EMAIL, POLL_INTERVAL optional) and run.
"""
import asyncio
import os
import signal
import time
from datetime import datetime, timedelta, timezone
import traceback

# import the page-based notify helper
from app import notify_once_with_page
from app import POLL_INTERVAL

STOP = False


def _install_signal_handlers():
    """Install simple signal handlers that set STOP flag.

    We avoid relying on asyncio loop.add_signal_handler because the loop
    used by asyncio.run may differ; using signal.signal works in most
    environments including simple containers.
    """
    def _handler(signum, frame=None):
        global STOP
        STOP = True

    try:
        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)
    except Exception:
        # some environments may restrict signal handling
        pass


def _load_env_file(path: str):
    """Load KEY=VAL lines from a file into os.environ (override existing).

    Ignores blank lines and lines starting with '#'. Values may be quoted.
    """
    if not path:
        return
    try:
        if not os.path.exists(path):
            return
        with open(path, 'r', encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith('#'):
                    continue
                if '=' not in ln:
                    continue
                k, v = ln.split('=', 1)
                k = k.strip()
                v = v.strip()
                # strip optional surrounding quotes
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                os.environ[k] = v
    except Exception:
        # don't crash the poller for a malformed env file
        pass


def load_env_files():
    """Load env files from system and user locations.

    System file: /etc/default/auto_notification
    User file: ~/.config/auto_notification/env
    """
    _load_env_file('/etc/default/auto_notification')
    _load_env_file(os.path.expanduser('~/.config/auto_notification/env'))


def _mask_val(k: str, v: str | None) -> str:
    if v is None or v == '':
        return ''
    sensitive = ('PASS', 'KEY', 'TOKEN', 'SECRET')
    if any(s in k.upper() for s in sensitive):
        # show short prefix only
        return v[:4] + '...'
    # for long values, keep them short in logs
    if len(v) > 64:
        return v[:64] + '...'
    return v


def dump_env_status(path: str = 'poller.log'):
    """Write a masked summary of relevant env keys to the poller log.

    This helps to debug whether the poller process actually has SMTP / API
    credentials in its environment. Values are masked to avoid leaking secrets
    into logs.
    """
    keys = [
        'SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASS', 'FROM_EMAIL',
        'SENDGRID_API_KEY', 'MAILGUN_API_KEY', 'MAILGUN_DOMAIN', 'POLL_INTERVAL'
    ]
    pairs = []
    for k in keys:
        v = os.environ.get(k)
        pairs.append(f"{k}={_mask_val(k, v)}")
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] env: " + ', '.join(pairs) + '\n')
    except Exception:
        # best-effort only
        pass


async def run_poller():
    global STOP
    backoff = 1
    max_backoff = 300
    url = "https://eipro.jp/takachiho1/eventCalendars/index"

    from playwright.async_api import async_playwright
    # load env from common locations so the poller picks up SMTP/API settings
    load_env_files()
    # write a masked summary of which env keys are present (helps debug dry-run)
    try:
        dump_env_status()
    except Exception:
        pass

    while not STOP:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                try:
                    await page.goto(url, wait_until='networkidle', timeout=60000)
                except Exception:
                    # proceed anyway; page navigation may or may not be required before selecting weeks
                    pass

                # reset backoff on successful create
                backoff = 1

                while not STOP:
                    tick_start = time.time()
                    try:
                        # reload env each iteration so changes to env files take effect without restarting
                        load_env_files()
                        # log what env keys are visible to this process (masked)
                        try:
                            dump_env_status()
                        except Exception:
                            pass
                        today = datetime.now(timezone.utc).date()
                        s1 = today.strftime('%Y-%m-%d')
                        s2 = (today + timedelta(days=7)).strftime('%Y-%m-%d')
                        res = await notify_once_with_page(page, [s1, s2])
                        with open('notification.log', 'a', encoding='utf-8') as f:
                            f.write(f"[{datetime.now(timezone.utc).isoformat()}] poll result: {res}\n")
                    except Exception as e:
                        with open('notification.log', 'a', encoding='utf-8') as f:
                            f.write(f"[{datetime.now(timezone.utc).isoformat()}] poll exception: {e}\n{traceback.format_exc()}\n")
                        # break to recreate browser/page with backoff
                        break

                    elapsed = time.time() - tick_start
                    interval = int(os.environ.get('POLL_INTERVAL', str(POLL_INTERVAL or 60)))
                    to_sleep = max(0, interval - elapsed)
                    # sleep in small chunks to be responsive to STOP
                    slept = 0
                    while slept < to_sleep and not STOP:
                        await asyncio.sleep(min(1, to_sleep - slept))
                        slept += min(1, to_sleep - slept)

                try:
                    await page.close()
                except Exception:
                    pass
                try:
                    await browser.close()
                except Exception:
                    pass

        except Exception as e:
            with open('notification.log', 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now(timezone.utc).isoformat()}] browser launch error: {e}\n{traceback.format_exc()}\n")

        if STOP:
            break

        # backoff before retrying to create browser
        await asyncio.sleep(backoff)
        backoff = min(max_backoff, backoff * 2)


def main():
    _install_signal_handlers()
    try:
        asyncio.run(run_poller())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
