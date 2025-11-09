#!/usr/bin/env python3
"""Test: ensure slot transitions full->available produce a notification.

This script monkeypatches `app.fetch_parsed_impl` and `app.send_email` to
simulate the site and capture whether notify is triggered. It runs two
iterations: first the slot is 'full' (no notify), then 'available' (notify).
"""
import asyncio
import json
import os
from datetime import datetime, timedelta

import app


TEST_KEY = [
    (datetime.utcnow().date() + timedelta(days=1)).strftime('%Y-%m-%d'),
    '09:00',
    'test-service-cd-123',
    f"{(datetime.utcnow().date() + timedelta(days=1)).strftime('%Y/%m/%d')} 09:00:00",
]


def make_item(status):
    date, time, service_cd, start_raw = TEST_KEY
    return {
        'date': date,
        'time': time,
        'status': status,
        'raw_text': f'status={status}',
        'attrs': {
            'service_cd': service_cd,
            'start_raw': start_raw,
        }
    }


async def run_test():
    starts = [TEST_KEY[0]]

    # Monkeypatch fetch_parsed_impl to return the item with given status
    async def fetch_full(start_date=None):
        return [make_item('full')]

    async def fetch_available(start_date=None):
        return [make_item('available')]

    # Capture send_email calls
    sent = {'calls': []}

    def fake_send_email(subject, body, recipients):
        print(f"fake_send_email called: subject={subject} recipients={recipients}")
        sent['calls'].append({'subject': subject, 'body': body, 'recipients': recipients})
        return True

    # Backup real functions
    real_fetch = app.fetch_parsed_impl
    real_send = app.send_email

    try:
        # Ensure a clean notified.json backup
        if os.path.exists(app.NOTIFIED_PATH):
            with open(app.NOTIFIED_PATH + '.bak', 'w', encoding='utf-8') as f:
                f.write(open(app.NOTIFIED_PATH, 'r', encoding='utf-8').read())

        # 1) First run: slot is full -> no notification expected
        app.fetch_parsed_impl = fetch_full
        app.send_email = fake_send_email
        print('Running first check (slot=full) ...')
        res1 = await app.notify_once_for_starts(starts)
        print('Result1:', res1)

        # 2) Second run: slot becomes available -> notification expected
        app.fetch_parsed_impl = fetch_available
        print('Running second check (slot=available) ...')
        res2 = await app.notify_once_for_starts(starts)
        print('Result2:', res2)

        print('\nSent calls:', sent['calls'])

        # Show notified.json content
        if os.path.exists(app.NOTIFIED_PATH):
            print('\nnotified.json content:')
            print(open(app.NOTIFIED_PATH, 'r', encoding='utf-8').read())

        # Show notifications.jsonl tail
        if os.path.exists('notifications.jsonl'):
            print('\nnotifications.jsonl tail:')
            with open('notifications.jsonl', 'r', encoding='utf-8') as f:
                lines = f.readlines()[-10:]
                for l in lines:
                    print(l.strip())

    finally:
        # restore
        app.fetch_parsed_impl = real_fetch
        app.send_email = real_send


if __name__ == '__main__':
    asyncio.run(run_test())
