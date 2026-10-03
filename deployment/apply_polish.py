#!/usr/bin/env python3
"""Apply browser and favicon assets to the assembled demo image only."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
app = root / "app.py"
source = app.read_text(encoding="utf-8")
source = source.replace("'/style.css'):", "'/style.css','/favicon.svg'):")
source = source.replace("'/style.css','/health'", "'/style.css','/favicon.svg','/health'")
source = source.replace("name='app.js' if path=='/app.js' else 'style.css'", "name='app.js' if path=='/app.js' else 'style.css' if path=='/style.css' else 'favicon.svg'")
source = source.replace("'text/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8'", "'text/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8' if name.endswith('.css') else 'image/svg+xml'")
if source == app.read_text(encoding="utf-8"):
    raise SystemExit("could not apply favicon route to the expected Stage 4 server")
app.write_text(source, encoding="utf-8")

# Keep the lookup usable when the restaurant-details request is unavailable.
# Stage 4's lookup renderer otherwise rejects the entire reservation panel if
# this secondary metadata request fails, even though the reservation itself
# has already loaded successfully.
script = root / "app.js"
javascript = script.read_text(encoding="utf-8")
lookup_call = "api(`/restaurants/${encodeURIComponent(reservation.restaurant_id)}`).then(({data})=>{"
lookup_fallback = "window.__tablekeeperRestaurantDetailsUnavailable=false;api(`/restaurants/${encodeURIComponent(reservation.restaurant_id)}`).then(result=>{if(!result.response.ok){window.__tablekeeperRestaurantDetailsUnavailable=true;return {data:{name:'Restaurant details unavailable',tables:[]}};}return result;}).catch(()=>{window.__tablekeeperRestaurantDetailsUnavailable=true;return {data:{name:'Restaurant details unavailable',tables:[]}};}).then(({data})=>{"
if lookup_call not in javascript:
    raise SystemExit("could not patch the expected Stage 4 reservation lookup")
script.write_text(javascript.replace(lookup_call, lookup_fallback, 1), encoding="utf-8")

index = root / "index.html"
html = index.read_text(encoding="utf-8")
html = html.replace('<link rel="stylesheet" href="/style.css">', '<link rel="icon" type="image/svg+xml" href="/favicon.svg">\n  <link rel="stylesheet" href="/style.css">')
index.write_text(html, encoding="utf-8")

for filename, overlay in (("app.js", "polish.js"), ("style.css", "polish.css")):
    target = root / filename
    addition = (root / overlay).read_text(encoding="utf-8")
    target.write_text(target.read_text(encoding="utf-8") + "\n\n/* deployment polish overlay */\n" + addition, encoding="utf-8")
