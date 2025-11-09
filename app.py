from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
import asyncio
import traceback
import os
import json
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta

app = FastAPI()

# templates
env = Environment(loader=FileSystemLoader("./templates"), autoescape=select_autoescape(["html"]))


@app.get("/", response_class=HTMLResponse)
async def index():
    tmpl = env.get_template("index.html")
    return HTMLResponse(tmpl.render())


@app.get("/api/fetch_week")
async def fetch_week(start: str | None = None, end: str | None = None):
    """
    週次の予約カレンダーを取得してHTMLスニペットや簡易JSONを返します。
    start/end は YYYY-MM-DD 形式（省略時はサーバー内で決定して Playwright に渡す実装想定）
    実際のページはクライアント側でカレンダーを描画するため、ここでは2段階で取得します:
     1) Playwright が利用可能ならブラウザでページを開いてレンダリング後の HTML を取得
     2) 利用不可なら単純に requests で取得したHTMLを返す（JSレンダリングされないため不完全）
    """
    try:
        # try using playwright if installed
        try:
            from playwright.async_api import async_playwright
        except Exception:
            async_playwright = None

        url = "https://eipro.jp/takachiho1/eventCalendars/index"

        if async_playwright is not None:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url)
                # wait a short while for JS to render calendar; adjust if needed
                await asyncio.sleep(2)
                # grab calendar container HTML (best-effort selector)
                content = await page.content()
                await browser.close()
                return JSONResponse({"ok": True, "source": "playwright", "html": content})

        # fallback: requests (no JS)
        import httpx

        resp = httpx.get(url, timeout=30)
        return JSONResponse({"ok": True, "source": "requests", "html": resp.text[:20000]})

    except Exception as e:
        tb = traceback.format_exc()
        return JSONResponse({"ok": False, "error": str(e), "trace": tb}, status_code=500)


def _read_recipients(path='recipients.txt'):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f.readlines()]
            return [l for l in lines if l and not l.startswith('#')]
    except FileNotFoundError:
        return []


def _write_recipients(lst: list[str], path='recipients.txt'):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            for e in lst:
                f.write(e.strip() + '\n')
        return True
    except Exception:
        return False


def _add_recipient(email: str, path='recipients.txt'):
    lst = _read_recipients(path)
    if email and email not in lst:
        lst.append(email)
        return _write_recipients(lst, path)
    return False


def _remove_recipient(email: str, path='recipients.txt'):
    lst = _read_recipients(path)
    if email and email in lst:
        lst = [e for e in lst if e != email]
        return _write_recipients(lst, path)
    return False


def _read_line_tokens(path='line_tokens.txt'):
    """Read LINE Notify tokens, one per line. Lines starting with # are ignored."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f.readlines()]
            return [l for l in lines if l and not l.startswith('#')]
    except FileNotFoundError:
        return []


async def fetch_parsed_impl(start_date: str | None = None):
    """Wrapper that launches Playwright and returns parsed results.

    Internally this function still exists to preserve existing endpoints. New code
    extracts the DOM-evaluation logic into `fetch_parsed_with_page(page, start_date)`
    so a persistent poller can reuse a single browser/page.
    """
    from playwright.async_api import async_playwright

    url = "https://eipro.jp/takachiho1/eventCalendars/index"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until='networkidle', timeout=60000)
        # give extra time for any dynamic rendering
        await asyncio.sleep(1)

        results = await fetch_parsed_with_page(page, start_date)

        await browser.close()

    return results


async def fetch_parsed_with_page(page, start_date: str | None = None):
    """Evaluate the page DOM on an already-open Playwright `page` and return shapeA results.

    This function contains the DOM selection and post-processing logic previously
    embedded in `fetch_parsed_impl` so callers that manage the browser (poller)
    can reuse a single `page` instance.
    """
    # If a start_date (YYYY-MM-DD) is provided, try to switch the week selector
    if start_date:
        s1 = start_date.replace('-', '/')
        s2 = start_date
        try:
            js_sel = (
                '(function(){'
                "const s1='" + s1 + "'; const s2='" + s2 + "';"
                "const selects = Array.from(document.querySelectorAll('select'));"
                "for (const selEl of selects){ const opts = Array.from(selEl.options||[]); for(let i=0;i<opts.length;i++){ const o=opts[i]; const txt=(o.textContent||'').trim(); if(!txt) continue; if(txt.indexOf(s1)!==-1||txt.indexOf(s2)!==-1){ try{ selEl.selectedIndex=i; try{ selEl.value=o.value; }catch(e){} selEl.dispatchEvent(new Event('change',{bubbles:true})); if(window.jQuery){ try{ window.jQuery(selEl).val(o.value).trigger('change'); }catch(e){} } const sel2=document.querySelector('.select2-selection__rendered'); if(sel2) sel2.textContent=txt; return true;}catch(e){} } } }"
                "const els = Array.from(document.querySelectorAll('button,a,span')); for(const e of els){ const t=(e.textContent||'').trim(); if(t && (t.indexOf(s1)!==-1||t.indexOf(s2)!==-1)){ try{ e.click(); }catch(e){} return true; } } return false; })()"
            )
            ok = await page.evaluate(js_sel)
        except Exception:
            ok = False
        # allow time for calendar to reload
        if ok:
            await asyncio.sleep(1.5)

    # Evaluate a JS snippet that collects service_unit containers (inputs + computed styles)
    js = (
        "() => {"
        "const out=[];"
        "const inputs=Array.from(document.querySelectorAll('input.service_unit_service_start_datetime'));"
        "for(const inp of inputs){"
        "let container=inp.parentElement;"
        "for(let i=0;i<8 && container;i++,container=container.parentElement){ if((container.className||'').indexOf('service_unit')!==-1) break; }"
        "if(!container) container=inp.parentElement;"
        "const getVal=(cls)=>{ const el=container.querySelector(cls); return el? (el.value||el.innerText||'') : ''; };"
        "const start=inp.value||'';"
        "const end=getVal('.service_unit_service_end_datetime')||'';"
        "const service_cd=getVal('.service_unit_service_cd')||'';"
        "const multi=getVal('.service_unit_service_multi_edit_key')||'';"
        "const icon=container.querySelector('i')||container.querySelector('.service_icon i');"
        "const icon_class=icon?(icon.className||'') : '';"
        "const icon_color=icon?(icon.style&&icon.style.color?icon.style.color:'') : '';"
        "const bg=window.getComputedStyle(container).backgroundColor||'';"
        "out.push({start,end,service_cd,multi,icon_class,icon_color,bg,text:(container.innerText||'').slice(0,300)});"
        "}"
        "return out;"
        "}"
    )
    data = await page.evaluate(js)

    # post-process (same logic as before)
    results = []
    import re
    for item in data:
        start_raw = (item.get('start') or '').strip()
        end_raw = (item.get('end') or '').strip()
        text = (item.get('text') or '').strip()
        icon_class = (item.get('icon_class') or '').strip()
        icon_color = (item.get('icon_color') or '').strip()
        bg = (item.get('bg') or '').strip()

        date = None
        time = None
        m = re.search(r"(\d{4})[/-](\d{2})[/-](\d{2})[T\s]?(\d{2}):(\d{2})", start_raw)
        if m:
            date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            time = f"{m.group(4)}:{m.group(5)}"
        else:
            m2 = re.search(r"(\d{4}-\d{2}-\d{2})T?(\d{2}:\d{2})", start_raw)
            if m2:
                date = m2.group(1)
                time = m2.group(2)

        status = 'other'
        low_text = text
        if icon_class and 'fa-times' in icon_class:
            status = 'full'
        elif icon_color and ('#f803' in icon_color or 'rgb(248' in icon_color or 'red' in icon_color):
            status = 'full'
        elif bg and (('#C0C0C0' in bg) or ('rgb(192' in bg) or ('gray' in bg)):
            status = 'full'
        elif '〇' in low_text or '○' in low_text:
            status = 'available'
        elif icon_class and ('fa-circle' in icon_class or 'fa-check' in icon_class):
            status = 'available'
        elif '砂' in low_text or '砂時計' in low_text or (icon_class and 'hourglass' in icon_class):
            status = 'not_started'

        attrs = {
            'service_cd': item.get('service_cd') or '',
            'multi_edit_key': item.get('multi') or '',
            'icon_class': icon_class,
            'icon_color': icon_color,
            'bg': bg,
            'start_raw': start_raw,
            'end_raw': end_raw,
        }

        results.append({
            'date': date,
            'time': time,
            'status': status,
            'raw_text': text,
            'attrs': attrs,
        })

    # dedupe & sort
    seen = set()
    deduped = []
    for r in results:
        key = (r.get('date'), r.get('time'), r.get('attrs', {}).get('service_cd'), r.get('attrs', {}).get('start_raw'))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    def sort_key(x):
        d = x.get('date') or '9999-12-31'
        t = x.get('time') or '99:99'
        return (d, t)

    deduped.sort(key=sort_key)
    return deduped


# --- Notification helpers and background polling
NOTIFIED_PATH = os.environ.get('NOTIFIED_PATH', 'notified.json')
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', '60'))  # seconds

def _load_notified(path=NOTIFIED_PATH):
    """Load notified state.

    New format: JSON object mapping serialized slot-key -> last-known status
    (e.g. '{"[\"2025-11-09\", \"13:00\", \"service_cd\", \"...\"]": "available"}').

    Backwards compatibility: if the file is a list of lists (old format), convert
    entries to keys with status 'notified'.
    Returns a dict mapping key_str -> status.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            out = {}
            for item in data:
                try:
                    key_str = json.dumps(list(item), ensure_ascii=False)
                except Exception:
                    key_str = json.dumps(item, ensure_ascii=False)
                out[key_str] = 'notified'
            return out
        return {}
    except Exception:
        return {}

def _save_notified(d: dict, path=NOTIFIED_PATH):
    """Persist notified state as a JSON object mapping key->status."""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _slot_key(item: dict):
    # unique key for a slot
    return (item.get('date'), item.get('time'), item.get('attrs', {}).get('service_cd'), item.get('attrs', {}).get('start_raw'))


def _key_to_str(key_tuple):
    try:
        return json.dumps(list(key_tuple), ensure_ascii=False)
    except Exception:
        return json.dumps(key_tuple, ensure_ascii=False)

def send_email(subject: str, body: str, recipients: list[str]):
    """Send email using available provider.

    Provider selection order:
      1) SendGrid HTTP API if SENDGRID_API_KEY is set
      2) Mailgun HTTP API if MAILGUN_API_KEY and MAILGUN_DOMAIN are set
      3) SMTP if SMTP_HOST/SMTP_PORT set
      4) Otherwise dry-run (write to notification.log)

    Returns True on success, False on failure (and logs details to notification.log).
    """
    # prepare common vars
    from_addr = os.environ.get('FROM_EMAIL') or os.environ.get('SMTP_USER') or 'noreply@example.com'

    # 1) SendGrid
    sendgrid_key = os.environ.get('SENDGRID_API_KEY')
    if sendgrid_key:
        try:
            import httpx
            payload = {
                "personalizations": [{"to": [{"email": r} for r in recipients]}],
                "from": {"email": from_addr},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}],
            }
            headers = {"Authorization": f"Bearer {sendgrid_key}", "Content-Type": "application/json"}
            resp = httpx.post("https://api.sendgrid.com/v3/mail/send", json=payload, headers=headers, timeout=20)
            if resp.status_code in (200, 202):
                # record success
                _append_history({
                    'ts': datetime.utcnow().isoformat(),
                    'method': 'sendgrid',
                    'recipients': recipients,
                    'subject': subject,
                    'status': 'success',
                    'detail': f'status={resp.status_code}'
                })
                return True
            else:
                with open('notification.log', 'a', encoding='utf-8') as f:
                    f.write(f"SendGrid send failed: status={resp.status_code} body={resp.text} Subject: {subject} To: {recipients}\n")
                _append_history({
                    'ts': datetime.utcnow().isoformat(),
                    'method': 'sendgrid',
                    'recipients': recipients,
                    'subject': subject,
                    'status': 'failed',
                    'detail': f'status={resp.status_code} body={resp.text}'
                })
                return False
        except Exception as e:
            with open('notification.log', 'a', encoding='utf-8') as f:
                f.write(f"SendGrid exception: {e} Subject: {subject} To: {recipients}\n")
            # fall through to try other providers

    # 2) Mailgun
    mailgun_key = os.environ.get('MAILGUN_API_KEY')
    mailgun_domain = os.environ.get('MAILGUN_DOMAIN')
    if mailgun_key and mailgun_domain:
        try:
            import httpx
            url = f"https://api.mailgun.net/v3/{mailgun_domain}/messages"
            auth = ("api", mailgun_key)
            data = {"from": from_addr, "to": recipients, "subject": subject, "text": body}
            resp = httpx.post(url, auth=auth, data=data, timeout=20)
            if resp.status_code in (200, 202):
                _append_history({
                    'ts': datetime.utcnow().isoformat(),
                    'method': 'mailgun',
                    'recipients': recipients,
                    'subject': subject,
                    'status': 'success',
                    'detail': f'status={resp.status_code}'
                })
                return True
            else:
                with open('notification.log', 'a', encoding='utf-8') as f:
                    f.write(f"Mailgun send failed: status={resp.status_code} body={resp.text} Subject: {subject} To: {recipients}\n")
                _append_history({
                    'ts': datetime.utcnow().isoformat(),
                    'method': 'mailgun',
                    'recipients': recipients,
                    'subject': subject,
                    'status': 'failed',
                    'detail': f'status={resp.status_code} body={resp.text}'
                })
                return False
        except Exception as e:
            with open('notification.log', 'a', encoding='utf-8') as f:
                f.write(f"Mailgun exception: {e} Subject: {subject} To: {recipients}\n")
            # fall through

    # 3) SMTP fallback (existing behavior)
    smtp_host = os.environ.get('SMTP_HOST')
    smtp_port = int(os.environ.get('SMTP_PORT', '0')) if os.environ.get('SMTP_PORT') else None
    smtp_user = os.environ.get('SMTP_USER')
    smtp_pass = os.environ.get('SMTP_PASS')

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = ', '.join(recipients)
    msg.set_content(body)

    if smtp_host and smtp_port:
        try:
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as s:
                    if smtp_user and smtp_pass:
                        s.login(smtp_user, smtp_pass)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as s:
                    s.ehlo()
                    try:
                        s.starttls()
                    except Exception:
                        pass
                    if smtp_user and smtp_pass:
                        s.login(smtp_user, smtp_pass)
                    s.send_message(msg)
            _append_history({
                'ts': datetime.utcnow().isoformat(),
                'method': 'smtp',
                'recipients': recipients,
                'subject': subject,
                'status': 'success',
                'detail': f'{smtp_host}:{smtp_port}'
            })
            return True
        except Exception as e:
            with open('notification.log', 'a', encoding='utf-8') as f:
                f.write(f"SMTP send failed: {e}\nSubject: {subject}\nTo: {recipients}\n")
            _append_history({
                'ts': datetime.utcnow().isoformat(),
                'method': 'smtp',
                'recipients': recipients,
                'subject': subject,
                'status': 'failed',
                'detail': str(e)
            })
            return False

    # 4) dry-run: append to log
    with open('notification.log', 'a', encoding='utf-8') as f:
        f.write(f"DRY-RUN send: Subject: {subject}\nTo: {recipients}\nBody:\n{body}\n---\n")
    _append_history({
        'ts': datetime.utcnow().isoformat(),
        'method': 'dry-run',
        'recipients': recipients,
        'subject': subject,
        'status': 'dry-run',
        'detail': ''
    })
    return False


def send_line(message: str, tokens: list[str]):
    """Send a message via LINE Notify to each token in the list.

    tokens: list of LINE Notify access tokens.
    Returns True if at least one send succeeded, False otherwise.
    """
    if not tokens:
        with open('notification.log', 'a', encoding='utf-8') as f:
            f.write(f"DRY-RUN LINE send: message={message}\n---\n")
        return False

    success_any = False
    try:
        import httpx
    except Exception as e:
        with open('notification.log', 'a', encoding='utf-8') as f:
            f.write(f"LINE send failed (httpx not available): {e}\nMessage: {message}\n")
        return False

    for t in tokens:
        try:
            headers = {"Authorization": f"Bearer {t}"}
            data = {"message": message}
            resp = httpx.post('https://notify-api.line.me/api/notify', headers=headers, data=data, timeout=15)
            if resp.status_code == 200:
                success_any = True
                _append_history({
                    'ts': datetime.utcnow().isoformat(),
                    'method': 'line',
                    'tokens': [t[:8]],
                    'subject': None,
                    'message': message,
                    'status': 'success',
                    'detail': f'status={resp.status_code}'
                })
            else:
                with open('notification.log', 'a', encoding='utf-8') as f:
                    f.write(f"LINE send failed: status={resp.status_code} body={resp.text} token_prefix={t[:8]} Message: {message}\n")
                _append_history({
                    'ts': datetime.utcnow().isoformat(),
                    'method': 'line',
                    'tokens': [t[:8]],
                    'subject': None,
                    'message': message,
                    'status': 'failed',
                    'detail': f'status={resp.status_code} body={resp.text}'
                })
        except Exception as e:
            with open('notification.log', 'a', encoding='utf-8') as f:
                f.write(f"LINE exception: {e} token_prefix={t[:8]} Message: {message}\n")
            _append_history({
                'ts': datetime.utcnow().isoformat(),
                'method': 'line',
                'tokens': [t[:8]],
                'subject': None,
                'message': message,
                'status': 'failed',
                'detail': str(e)
            })

    return success_any


def _append_history(entry: dict, path='notifications.jsonl'):
    """Append a JSON line to notifications.jsonl. Keeps most recent entries write-only."""
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass


@app.get('/api/history')
async def api_history(limit: int | None = 100):
    """Return recent notification history (most recent first)."""
    path = 'notifications.jsonl'
    out = []
    try:
        if not os.path.exists(path):
            return JSONResponse({"ok": True, "history": []})
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        # read last `limit` lines
        lines = lines[-limit:]
        for ln in reversed(lines):
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return JSONResponse({"ok": True, "history": out})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

async def notify_once_for_starts(starts: list[str]):
    """Check specified start dates (YYYY-MM-DD), return summary and send notifications for newly available slots.
    Returns dict with summary.
    """
    recipients = _read_recipients()
    if not recipients:
        # nothing to do, but return candidates
        recipients = []

    prev = _load_notified()  # dict: key_str -> last_status
    new_notified = dict(prev)
    produced = []

    for s in starts:
        try:
            items = await fetch_parsed_impl(s)
        except Exception:
            continue
        for c in items:
            key_tuple = _slot_key(c)
            key_str = _key_to_str(key_tuple)
            current_status = (c.get('status') or '')
            prev_status = prev.get(key_str)

            # if it's currently not full (available/other) and the previous
            # recorded status was 'full' or absent or different, treat as new
            if current_status != 'full':
                if prev_status != current_status:
                    produced.append(c)
            # always update recorded status to current
            new_notified[key_str] = current_status

    # if there are new produced, send email
    if produced and recipients:
        subj = f"予約枠の空き候補が見つかりました ({len(produced)}件)"
        lines = []
        for p in produced:
            lines.append(f"{p.get('date')} {p.get('time')}  status={p.get('status')} service_cd={p.get('attrs',{}) .get('service_cd')}\n  text={p.get('raw_text')}\n")
        body = "\n".join(lines)
        send_email(subj, body, recipients)

    # persist new_notified dict
    _save_notified(new_notified)

    return {'new_count': len(produced), 'notified': [_slot_key(x) for x in produced], 'recipients': recipients}


async def notify_once_with_page(page, starts: list[str]):
    """Variant of notify_once_for_starts that reuses an existing Playwright `page`.

    This mirrors notify_once_for_starts but calls `fetch_parsed_with_page` to avoid
    launching a new browser for each check.
    """
    recipients = _read_recipients()
    if not recipients:
        recipients = []

    prev = _load_notified()
    new_notified = dict(prev)
    produced = []

    for s in starts:
        try:
            items = await fetch_parsed_with_page(page, s)
        except Exception as e:
            with open('notification.log', 'a', encoding='utf-8') as f:
                f.write(f'fetch_with_page error for {s}: {e}\n')
            continue
        for c in items:
            key_tuple = _slot_key(c)
            key_str = _key_to_str(key_tuple)
            current_status = (c.get('status') or '')
            prev_status = prev.get(key_str)
            if current_status != 'full':
                if prev_status != current_status:
                    produced.append(c)
            new_notified[key_str] = current_status

    if produced and recipients:
        subj = f"予約枠の空き候補が見つかりました ({len(produced)}件)"
        lines = []
        for p in produced:
            lines.append(f"{p.get('date')} {p.get('time')}  status={p.get('status')} service_cd={p.get('attrs',{}) .get('service_cd')}\n  text={p.get('raw_text')}\n")
        body = "\n".join(lines)
        send_email(subj, body, recipients)

    _save_notified(new_notified)

    return {'new_count': len(produced), 'notified': [_slot_key(x) for x in produced], 'recipients': recipients}

_bg_task = None
_bg_task_cancel = False

async def _background_loop():
    global _bg_task_cancel
    while not _bg_task_cancel:
        try:
            # compute two starts: today and +7 days
            today = datetime.utcnow().date()
            s1 = today.strftime('%Y-%m-%d')
            s2 = (today + timedelta(days=7)).strftime('%Y-%m-%d')
            await notify_once_for_starts([s1, s2])
        except Exception as e:
            with open('notification.log', 'a', encoding='utf-8') as f:
                f.write(f'Background error: {e}\n')
        await asyncio.sleep(POLL_INTERVAL)


@app.get('/api/fetch_parsed')
async def fetch_parsed(start: str | None = None):
    try:
        data = await fetch_parsed_impl(start)
        return JSONResponse({"ok": True, "source": "playwright", "data": data})
    except Exception as e:
        import traceback as _tb
        return JSONResponse({"ok": False, "error": str(e), "trace": _tb.format_exc()}, status_code=500)


@app.get('/api/notify_now')
async def api_notify_now(start: str | None = None):
    """Immediate notification run. If start provided, it'll be used and also next week will be checked.
    Returns summary of notifications (new_count, notified keys, recipients).
    """
    try:
        starts = []
        if start:
            starts.append(start)
            # also check next week
            try:
                d = datetime.strptime(start, '%Y-%m-%d').date()
                starts.append((d + timedelta(days=7)).strftime('%Y-%m-%d'))
            except Exception:
                pass
        else:
            today = datetime.utcnow().date()
            starts = [ today.strftime('%Y-%m-%d'), (today + timedelta(days=7)).strftime('%Y-%m-%d') ]

        res = await notify_once_for_starts(starts)
        return JSONResponse({"ok": True, "result": res})
    except Exception as e:
        import traceback as _tb
        return JSONResponse({"ok": False, "error": str(e), "trace": _tb.format_exc()}, status_code=500)


@app.get('/api/recipients')
async def api_recipients():
    lst = _read_recipients()
    return JSONResponse({"ok": True, "count": len(lst), "recipients": lst})


@app.post('/api/recipients')
async def api_add_recipient(request: Request):
    """Add a recipient. JSON body: {"email": "addr@example.com"} """
    try:
        data = await request.json()
        email = (data.get('email') or '').strip()
        if not email:
            return JSONResponse({"ok": False, "error": "email required"}, status_code=400)
        ok = _add_recipient(email)
        if ok:
            return JSONResponse({"ok": True, "added": email})
        else:
            return JSONResponse({"ok": False, "error": "already exists or write failed"}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.delete('/api/recipients')
async def api_delete_recipient(email: str | None = None):
    """Delete a recipient using query param ?email=..."""
    try:
        if not email:
            return JSONResponse({"ok": False, "error": "email required"}, status_code=400)
        ok = _remove_recipient(email)
        if ok:
            return JSONResponse({"ok": True, "removed": email})
        else:
            return JSONResponse({"ok": False, "error": "not found or write failed"}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get('/api/check')
async def api_check(start: str | None = None):
    """解析して status != 'full' の候補を返す（通知対象候補）。UIは変更しないので、ここで確認できるようにする。"""
    try:
        data = await fetch_parsed_impl(start)
        notify = [d for d in data if (d.get('status') or '') != 'full']
        recips = _read_recipients()
        return JSONResponse({"ok": True, "candidates": notify, "recipients": recips})
    except Exception as e:
        import traceback as _tb
        return JSONResponse({"ok": False, "error": str(e), "trace": _tb.format_exc()}, status_code=500)


@app.on_event('startup')
async def _startup():
    global _bg_task
    # create sample recipients.txt if missing
    if not os.path.exists('recipients.txt'):
        with open('recipients.txt', 'w', encoding='utf-8') as f:
            f.write('# Add one email per line, for example:\n# your@email.example\n')
    # start background notifier
    if _bg_task is None:
        _bg_task = asyncio.create_task(_background_loop())


@app.on_event('shutdown')
async def _shutdown():
    global _bg_task_cancel, _bg_task
    _bg_task_cancel = True
    if _bg_task:
        try:
            await _bg_task
        except Exception:
            pass
