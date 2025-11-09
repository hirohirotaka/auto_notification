#!/usr/bin/env python3
"""Simple monitor: follow poller.log and notifications.jsonl and emit alerts.

Run as a background process (systemd service or nohup) to continuously watch
for SMTP failures, dry-run patterns, and summarize activity.

This script writes its own `monitor.log` in the project root.
"""
import time
import os
import re
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
POLLER_LOG = os.path.join(PROJECT_ROOT, 'poller.log')
NOTIF_LOG = os.path.join(PROJECT_ROOT, 'notifications.jsonl')
MONITOR_LOG = os.path.join(PROJECT_ROOT, 'monitor.log')

SMTP_FAIL_RE = re.compile(r'SMTP send failed|smtp.*failed', re.I)
DRY_RUN_RE = re.compile(r'DRY-RUN send|"method"\s*:\s*"dry-run"', re.I)
SMTP_SUCCESS_RE = re.compile(r'"method"\s*:\s*"smtp"\s*,.*"status"\s*:\s*"success"', re.I)


def _now():
    return datetime.utcnow().isoformat() + 'Z'


def _write(msg: str):
    line = f"[{_now()}] {msg}\n"
    print(line, end='')
    try:
        with open(MONITOR_LOG, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass


def follow_file(path, callback, sleep=0.5):
    """Follow file like tail -F. Calls callback(line) for each new line.
    If file doesn't exist yet, waits until it's created.
    """
    last_inode = None
    fh = None
    while True:
        try:
            if fh is None:
                if not os.path.exists(path):
                    time.sleep(sleep)
                    continue
                fh = open(path, 'r', encoding='utf-8', errors='ignore')
                fh.seek(0, os.SEEK_END)
                last_inode = os.fstat(fh.fileno()).st_ino

            line = fh.readline()
            if line:
                callback(line)
            else:
                # detect rotation (inode changed)
                try:
                    cur_inode = os.stat(path).st_ino
                    if cur_inode != last_inode:
                        fh.close()
                        fh = None
                        last_inode = None
                        continue
                except FileNotFoundError:
                    fh = None
                time.sleep(sleep)
        except Exception as e:
            _write(f"follow_file error for {path}: {e}")
            try:
                if fh:
                    fh.close()
            except Exception:
                pass
            fh = None
            time.sleep(1)


def monitor_loop():
    stats = {
        'dry_run_events': [],  # list of (ts_iso, line)
        'smtp_fail_events': [],
        'smtp_success': [],
    }

    def handle_poller_line(line):
        if DRY_RUN_RE.search(line):
            stats['dry_run_events'].append((datetime.utcnow(), line.strip()))
            _write('ALERT: DRY-RUN detected in poller.log')
        if SMTP_FAIL_RE.search(line):
            stats['smtp_fail_events'].append((datetime.utcnow(), line.strip()))
            _write('ALERT: SMTP failure detected in poller.log')

    def handle_notif_line(line):
        if DRY_RUN_RE.search(line):
            stats['dry_run_events'].append((datetime.utcnow(), line.strip()))
            _write('ALERT: DRY-RUN detected in notifications.jsonl')
        if SMTP_SUCCESS_RE.search(line):
            stats['smtp_success'].append((datetime.utcnow(), line.strip()))
        if '"method"' in line and 'failed' in line.lower():
            _write('ALERT: notification entry indicates failed send')

    # start followers in separate threads (simple polling loop here, not threads)
    # We'll interleave reads: spin up two non-blocking followers using small sleeps
    from threading import Thread
    t1 = Thread(target=follow_file, args=(POLLER_LOG, handle_poller_line), daemon=True)
    t2 = Thread(target=follow_file, args=(NOTIF_LOG, handle_notif_line), daemon=True)
    t1.start()
    t2.start()

    _write('monitor started')

    try:
        while True:
            # every 60s produce a summary for last 10 minutes
            cutoff = datetime.utcnow() - timedelta(minutes=10)
            dry_recent = [e for e in stats['dry_run_events'] if e[0] >= cutoff]
            smtp_fail_recent = [e for e in stats['smtp_fail_events'] if e[0] >= cutoff]
            smtp_ok_recent = [e for e in stats['smtp_success'] if e[0] >= cutoff]

            summary = f"summary(last10m): dry_run={len(dry_recent)} smtp_fail={len(smtp_fail_recent)} smtp_ok={len(smtp_ok_recent)}"
            _write(summary)

            # if too many dry-runs or failures, emit a stronger alert
            if len(smtp_fail_recent) >= 1:
                _write('CRITICAL: SMTP failures seen in last 10m')
            if len(dry_recent) >= 5:
                _write('WARNING: many dry-run events in last 10m')

            # truncate old events to keep memory small
            cutoff2 = datetime.utcnow() - timedelta(hours=6)
            stats['dry_run_events'] = [e for e in stats['dry_run_events'] if e[0] >= cutoff2]
            stats['smtp_fail_events'] = [e for e in stats['smtp_fail_events'] if e[0] >= cutoff2]
            stats['smtp_success'] = [e for e in stats['smtp_success'] if e[0] >= cutoff2]

            time.sleep(60)
    except KeyboardInterrupt:
        _write('monitor stopped')


if __name__ == '__main__':
    monitor_loop()
