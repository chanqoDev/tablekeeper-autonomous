import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path('/evidence')
BASE = 'http://host.docker.internal:18091'
report = {'routes': {}, 'errors': []}

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.on('pageerror', lambda error: report['errors'].append(str(error)))

    page.goto(BASE + '/signup', wait_until='networkidle')
    page.locator('[data-testid="signup-display-name"]').fill('Stage Three Reviewer')
    page.locator('[data-testid="signup-email"]').fill('review-stage3@example.invalid')
    page.locator('[data-testid="signup-password"]').fill('sample-password-123')
    page.locator('[data-testid="signup-submit"]').click()
    page.wait_for_url('**/')
    page.locator('[data-testid="current-user"]').wait_for()

    page.locator('[data-testid="restaurant-select"]').select_option('r_demo')
    page.locator('[data-testid="date-input"]').fill('2026-10-10')
    page.locator('[data-testid="party-size-input"]').fill('8')
    page.locator('#explain-seatings').check()
    page.locator('[data-testid="search-button"]').click()
    page.locator('[data-testid="availability-grid"]').wait_for()
    report['routes']['home'] = page.evaluate('''() => ({viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,slots:document.querySelectorAll('[data-testid^="slot-"]').length,allUnavailable:[...document.querySelectorAll('[data-testid^="slot-"]')].every(x=>x.dataset.available==='false'),reason:[...document.querySelectorAll('[data-testid^="slot-"] .slot-reason')].slice(0,2).map(x=>x.textContent),explainChecked:document.querySelector('#explain-seatings').checked})''')
    page.screenshot(path=str(OUT / 'stage3-home-explanations-desktop.png'), full_page=True)
    page.set_viewport_size({'width':375,'height':812})
    report['routes']['home']['mobile'] = page.evaluate('''() => ({viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth})''')
    page.screenshot(path=str(OUT / 'stage3-home-explanations-mobile-375.png'), full_page=True)

    page.set_viewport_size({'width':1440,'height':1000})
    page.locator('[data-testid="party-size-input"]').fill('5')
    page.locator('[data-testid="search-button"]').click()
    page.locator('[data-testid="slot-t_1+t_2-18:00"]').wait_for(state='visible')
    page.locator('[data-testid="slot-t_1+t_2-18:00"]').click()
    page.locator('[data-testid="booking-form"]').wait_for()
    page.screenshot(path=str(OUT / 'stage3-combined-booking-desktop.png'), full_page=True)
    page.set_viewport_size({'width':375,'height':812})
    report['routes']['booking_mobile'] = page.evaluate('''() => ({viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,summary:document.querySelector('[data-testid="booking-summary"]').textContent})''')
    page.screenshot(path=str(OUT / 'stage3-combined-booking-mobile-375.png'), full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    page.locator('[data-testid="booking-submit"]').click()
    page.locator('[data-testid="confirmation-reference"]').wait_for()
    reference=page.locator('[data-testid="confirmation-reference"]').text_content().strip()
    page.screenshot(path=str(OUT / 'stage3-combined-confirmation-desktop.png'), full_page=True)

    page.goto(BASE + '/lookup', wait_until='networkidle')
    page.locator('[data-testid="lookup-reference-input"]').fill(reference)
    page.locator('[data-testid="lookup-submit"]').click()
    page.locator('[data-testid="reservation-detail"]').wait_for()
    page.locator('#history-panel .history-list').wait_for()
    page.locator('#series-count').fill('2')
    page.locator('#series-interval').fill('1')
    page.locator('.series-form button[type="submit"]').click()
    page.locator('[data-testid="series-result"]').wait_for()
    report['routes']['lookup'] = page.evaluate('''() => ({viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,status:document.querySelector('[data-testid="reservation-status"]').textContent.trim(),tables:document.querySelector('[data-testid="reservation-tables"]').textContent,history:document.querySelectorAll('#history-panel .history-list > li').length,historyFields:[...document.querySelectorAll('#history-panel .history-list > li:first-child ul li')].map(x=>x.textContent.trim()),seriesOccurrences:document.querySelectorAll('[data-testid="series-result"] li').length,seriesText:document.querySelector('[data-testid="series-result"]').textContent})''')
    page.screenshot(path=str(OUT / 'stage3-history-series-desktop.png'), full_page=True)
    page.set_viewport_size({'width':375,'height':812})
    report['routes']['lookup']['mobile'] = page.evaluate('''() => ({viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth})''')
    page.screenshot(path=str(OUT / 'stage3-history-series-mobile-375.png'), full_page=True)

    report['reference']=reference
    browser.close()

(OUT / 'stage3-browser-review.json').write_text(json.dumps(report,indent=2)+'\n')
