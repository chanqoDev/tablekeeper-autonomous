# Independent review: deployment polish

**Source commit reviewed:** `448ebd3f501cac7a84013bf5bb1f67ccb4af6856`
**Review date:** 2026-10-03

## Result

**Passed.** I independently assembled and ran the deployment package from this exact source commit against a disposable local SQLite database. The metadata failure path now displays the reservation and history without a repeated DOM update loop.

## Verified checks

- Fresh browser contexts exercised both an HTTP 503 and a network rejection for `/restaurants/demo_anker` after a reservation response. Both showed the reservation detail and history, with `Table label unavailable` in the detail and history changes. The no-IANA-zone history timestamp was `Oct 3, 2026, 11:26 AM (UTC+02:00)`, matching the stored historical value `2026-10-03T11:26:20.548949+02:00`.
- Readable 375px fallback history rendered at `innerWidth=375`, `scrollWidth=375`. Desktop fallback rendered at 1440px without horizontal overflow. The captures are [fresh 375px fallback](448ebd3-fresh-http-503-375.png), [375px network rejection](448ebd3-fresh-network-abort-375.png), and [desktop fallback](448ebd3-fresh-http-503-desktop.png).
- The Technical details disclosure was collapsed initially, opened with Enter, closed with Space, and contained the original raw table ID (`anker_2`).
- Local UI booking succeeded. A three-visit weekly series was created; after cancelling visit two individually, API reads showed statuses `confirmed, cancelled, confirmed`.
- The favicon link resolved to `/favicon.svg`; GET returned 200 with `image/svg+xml`. Browser image decode succeeded, and the SVG rendered at both 16px and 32px in [the favicon capture](448ebd3-favicon-16px-32px.png).
- History screenshots show readable Created, Cancelled, and Reassigned events, friendly field names, accepted-term summaries, and readable table labels when available. When metadata is missing, the fallback is explicit. Earlier visual evidence is retained in [desktop history](1013310-history-desktop.png), [375px history](1013310-history-mobile-375.png), [cancelled history](1013310-cancelled-history.png), and [reassigned history](history-reassigned.png); event rendering did not change in this final commit.
- `node --check` passed on assembled `app.js` and `polish.js`. The protected stage trees compare unchanged from `10133108a051975c2699cb5e90b13b6a31ca2995` through this commit.

## Scope and deployment

All booking, series, and cancellation mutations used the local test database. No hosted user state was changed; no push or redeploy occurred.

The local Docker daemon did not respond during my Docker build attempt, so I verified the exact committed image inputs assembled by `deployment/apply_polish.py` rather than claiming an independent Docker image build. The existing deployment build command is `docker build -f Dockerfile.render -t <image-tag> .`; use the project's normal Render deployment process only after the owner chooses to deploy.
