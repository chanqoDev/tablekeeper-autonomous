# Independent review: deployment polish

**Source commit reviewed:** `472499c700ebda0e08eb79d4aac92374539138c`
**Parent deployment candidate:** `10133108a051975c2699cb5e90b13b6a31ca2995`
**Review date:** 2026-10-03

## Result

**Not approved yet.** The normal lookup/history presentation and the local booking, recurring-series, and individual-cancellation flow passed on the packaged local app. The final fallback case for failed restaurant metadata did not pass the independent browser assertion: lookup returned the reservation (`GET /reservations/UX6Q3AR9` was HTTP 200), the test deliberately failed `GET /restaurants/demo_anker`, and Playwright timed out waiting for `[data-testid="reservation-detail"]`. Chrome logged `net::ERR_FAILED`. I could not confirm a visible reservation or history panel with “Table label unavailable” for this case. The source change in 472499c supplies an empty label map to the history formatter, but this browser result still requires investigation/retest.

The test used a disposable local SQLite database and `http://127.0.0.1:18768`; it did not touch the hosted demo. No push or redeploy occurred.

## Checks and evidence

- The local browser flow created a booking, created a three-visit recurring series, cancelled one visit, and showed the other visits still confirmed. Captures from that run are [desktop history](1013310-history-desktop.png), [375px history](1013310-history-mobile-375.png), [series desktop](1013310-series-desktop.png), [series at 375px](1013310-series-mobile-375.png), and [cancelled-visit history](1013310-cancelled-history.png). The source presentation was unchanged between 1013310 and the single-label-map change in 472499c; these captures were made against the 1013310 assembled package.
- A local GET of `/favicon.svg` returned HTTP 200 with `Content-Type: image/svg+xml`; the served SVG parsed with `viewBox="0 0 32 32"`. A 16px/32px favicon rendering capture exists from the earlier review at [favicon-16px-32px.png](favicon-16px-32px.png).
- Desktop and 375px history captures show readable table labels, Created/Reassigned events, friendly field names, accepted-term summaries, and collapsed Technical details. Keyboard opening/closing of the disclosure and full JSON were recorded in the earlier browser review [12b8597 report](verifier-review-2026-10-03-12b8597.json); the corresponding disclosure implementation is unchanged in these commits.
- No-zone timestamp formatting had passed the focused review of commit `12b85972c0ae01106b282dbe7dc8ce559e57ab93` for `2030-01-02T10:00:00+02:00`, producing `Jan 2, 2030, 10:00 AM (UTC+02:00)`. The formatter is unchanged in the commits under this review; a 12b8597 capture is [fallback timestamp](12b8597-fallback-timezone.png).
- `git diff --exit-code 10133108a051975c2699cb5e90b13b6a31ca2995 472499c700ebda0e08eb79d4aac92374539138c -- stage-1/ stage-2/ stage-3/ stage-4/` passed; protected stage trees are unchanged.
- The Docker CLI build could not be independently completed in this runtime because the local Docker daemon did not respond. I assembled the committed deployment assets locally and served them on port 18768. Builder reported a successful no-cache Docker build; this independent review does not claim one.

## Reproduction

1. Assemble the Render image inputs from the exact source commit: copy `stage-4/app.py`, `stage-4/index.html`, `stage-4/app.js`, `stage-4/style.css` and the deployment bootstrap/overlay/favicon files to a disposable app directory, then run `deployment/apply_polish.py <app-directory>`.
2. Start the packaged app with a disposable SQLite database and create a local booking.
3. Open `/lookup`, authenticate as the test owner, submit that booking reference, and deliberately fail the browser request to `/restaurants/demo_anker`.
4. On 472499c, the reservation-detail selector did not become visible within 10 seconds; the history panel and unavailable-label fallback therefore could not be confirmed.

## Review artifacts

The `1013310-*.png` files are the desktop/375px and mutation-flow captures. The failed 472499c fallback run did not produce a valid screenshot. Earlier timestamp, keyboard disclosure, and favicon artifacts are retained with the 12b8597 prefix.
