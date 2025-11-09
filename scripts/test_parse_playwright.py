from playwright.sync_api import sync_playwright
import json

url = 'https://eipro.jp/takachiho1/eventCalendars/index'

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.goto(url, wait_until='networkidle', timeout=60000)
    page.wait_for_timeout(1000)
    data = page.evaluate('''() => {
        const els = Array.from(document.querySelectorAll('[class*="service_unit"], .service_unit, [data-service-date], [data-service_start_datetime], [data-service_start_datetime]'));
        const out = [];
        els.forEach(e => {
            const attrs = {};
            for (let i=0;i<e.attributes.length;i++){
                const a = e.attributes[i];
                if (a.name.startsWith('data-')) attrs[a.name]=a.value;
            }
            out.push({
                text: e.innerText || '',
                attrs: attrs,
                tag: e.tagName,
                className: e.className || ''
            });
        });
            return out;
        }''')
    b.close()

# Post-process similar to server
import re
results = []
for item in data:
    attrs = item.get('attrs', {})
    text = (item.get('text') or '').strip()
    service_start = attrs.get('data-service_start_datetime') or attrs.get('data-service-start-datetime') or attrs.get('data-service_start_datetime') or attrs.get('data-service_date')
    date = None
    time = None
    if service_start:
        m = re.match(r"(\d{4}[-/]\d{2}[-/]\d{2})[T\s]?(\d{2}:\d{2})", service_start)
        if m:
            date = m.group(1)
            time = m.group(2)
        else:
            date = service_start
    status = 'other'
    ordable = attrs.get('data-ordable') or attrs.get('data-ordable')
    if ordable and ordable.lower() in ('1','true','t'):
        status = 'available'
    elif '〇' in text or '○' in text:
        status = 'available'
    elif '×' in text or '✕' in text or '×' in text:
        status = 'full'
    elif '砂' in text or '砂時計' in text or 'hourglass' in text:
        status = 'not_started'
    results.append({
        'date': date,
        'time': time,
        'status': status,
        'raw_text': text,
        'attrs': attrs,
    })

print(json.dumps({'ok': True, 'count': len(results), 'sample': results[:20]}, ensure_ascii=False, indent=2))
