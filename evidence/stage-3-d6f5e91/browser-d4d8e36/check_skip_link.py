import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':375,'height':812})
    page.goto('http://host.docker.internal:18092/lookup',wait_until='networkidle')
    before=page.evaluate('''() => ({active:document.activeElement.tagName+':'+(document.activeElement.dataset.testid||document.activeElement.className),skipRect:(()=>{let x=document.querySelector('.skip-link').getBoundingClientRect();return {x:x.x,y:x.y,width:x.width,height:x.height}})(),skipTransform:getComputedStyle(document.querySelector('.skip-link')).transform})''')
    page.screenshot(path='/evidence/stage3-lookup-unfocused-375.png',full_page=True)
    page.keyboard.press('Tab')
    after=page.evaluate('''() => ({active:document.activeElement.tagName+':'+(document.activeElement.dataset.testid||document.activeElement.className),skipRect:(()=>{let x=document.querySelector('.skip-link').getBoundingClientRect();return {x:x.x,y:x.y,width:x.width,height:x.height}})(),skipTransform:getComputedStyle(document.querySelector('.skip-link')).transform})''')
    page.screenshot(path='/evidence/stage3-lookup-keyboard-focus-375.png',full_page=True)
    print(json.dumps({'unfocused':before,'afterTab':after}))
    browser.close()
