#!/usr/bin/env python3
"""
Tiny runner for cron: calls notify_once_for_starts for today and next week.
Usage (from project root):
  . .venv/bin/activate
  python scripts/run_notify.py

This script expects the project env vars (SMTP_*, FROM_EMAIL, etc.) to be set in the environment.
"""
import asyncio
from datetime import datetime, timedelta
import os

# Ensure current working directory is project root
os.chdir(os.path.dirname(os.path.dirname(__file__)))

from app import notify_once_for_starts


def main():
    today = datetime.utcnow().date()
    s1 = today.strftime('%Y-%m-%d')
    s2 = (today + timedelta(days=7)).strftime('%Y-%m-%d')
    print(f"Running notify for: {s1}, {s2}")
    try:
        res = asyncio.run(notify_once_for_starts([s1, s2]))
        print('Result:', res)
    except Exception as e:
        print('Error running notify:', e)


if __name__ == '__main__':
    main()
