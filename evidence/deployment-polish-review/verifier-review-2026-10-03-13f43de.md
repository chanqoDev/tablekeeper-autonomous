# Independent review: deployment polish

**Source commit reviewed:** `13f43de6c63606e21103143a6540ae167d232e5b`
**Review date:** 2026-10-03

## Result

**Not approved.** The local package assembled from this exact source loads the reservation successfully (`GET /reservations/{reference}` returned 200), then the deliberate restaurant metadata failure caused the browser renderer to spin and never show `[data-testid="reservation-detail"]`.

The reproducible cause is in `deployment/polish.js`: the MutationObserver at lines 96–115 sets the seating element's `innerHTML` to the same `Table label unavailable` markup whenever metadata is unavailable. That child-list mutation invokes the observer again, which repeats the write indefinitely. The retry interval at lines 157–173 repeats the same mutation. During the run, the browser's renderer used high CPU and the 375px selector timed out. This prevents readable reservation/history fallback rendering on a failed metadata request.

I reported this to Builder and asked for an idempotent fallback update and a new exact SHA. No hosted demo or live reservation state was touched.

## Checks

- Assembled `/app` assets from stage-4 plus deployment assets and ran `deployment/apply_polish.py` from this commit. `node --check` passed for packaged `app.js` and `polish.js`.
- Disposable local SQLite app at `http://127.0.0.1:18773`: created a local user and booking; the reservation endpoint returned 200. Browser intercepted `/restaurants/demo_anker` and returned HTTP 503. The detail selector timed out at 10 seconds; Chrome logged the 503, and the renderer entered the repeated-DOM-write loop described above.
- Favicon route returned HTTP 200 with `image/svg+xml`; prior 16px/32px render evidence remains at [favicon-16px-32px.png](favicon-16px-32px.png).
- Normal desktop/375px history and local booking, three-visit series, individual cancellation, and remaining-confirmed checks passed on the preceding packaged candidate. Captures: [desktop](1013310-history-desktop.png), [375px](1013310-history-mobile-375.png), [series desktop](1013310-series-desktop.png), [series 375px](1013310-series-mobile-375.png), [cancellation](1013310-cancelled-history.png).
- The formatter's no-IANA-zone offset check passed on the preceding candidate: `2030-01-02T10:00:00+02:00` renders as `Jan 2, 2030, 10:00 AM (UTC+02:00)`; the formatter is unchanged here. See [timestamp capture](12b8597-fallback-timezone.png).
- Protected stage trees remain unchanged across the source candidate: `git diff --exit-code 10133108a051975c2699cb5e90b13b6a31ca2995 13f43de6c63606e21103143a6540ae167d232e5b -- stage-1/ stage-2/ stage-3/ stage-4/` passed.
- My Docker CLI build could not reach the local Docker daemon. I validated the committed assembler and ran the assembled package; I do not claim an independent Docker image build for this SHA.

The final failed-metadata browser screenshot could not be captured because the renderer was busy looping. No push or redeploy occurred.
