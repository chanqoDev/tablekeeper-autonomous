# Deployment polish local checks

These checks were run against a disposable local Docker container built from the deployment image. No request was sent to the hosted demo, and the test booking state lived only in that container's temporary SQLite database.

- `docker build -f Dockerfile.render -t tablekeeper-polish-local .` — passed.
- `node --check deployment/polish.js` — passed.
- `python3 -m py_compile deployment/apply_polish.py deployment/bootstrap_demo.py` — passed.
- `git diff --check` — passed.
- `git diff --exit-code -- stage-1/ stage-2/ stage-3/ stage-4/` — passed; protected stage source remained unchanged.
- Overlay assembly check — verified public `/favicon.svg` routing with SVG MIME type, the HTML favicon link, and appended UI/CSS overlay assets.
- Local packaged API flow — health, asset serving, signup, booking, three-visit recurring series creation, cancellation of one occurrence, and the other two occurrences remaining confirmed all passed. History API still returned the original event and accepted-term snapshot.

Desktop and 375px browser review is assigned to the independent Verifier against the committed image. This file records Builder checks only.

## Follow-up checks

After the independent review identified a UTC offset label mismatch, the no-IANA-zone formatter was corrected to preserve the stored wall-clock and show the timestamp's numeric UTC offset. After the review also exercised a failed restaurant metadata request, the lookup overlay was extended to keep the reservation history visible with explicit unavailable details and table labels.

- A focused Node check passed for the offset example `2030-01-02T08:00:00+02:00`, rendered as `Jan 2, 2030, 8:00 AM (UTC+02:00)`.
- A focused fetch-wrapper check passed for network failures and HTTP 503 responses on lookup restaurant metadata, while preserving normal failure handling on other routes.
- `node --check deployment/polish.js` and the deployment image build passed after the fixes.
- A fresh `docker build --no-cache -f Dockerfile.render -t tablekeeper-polish-local .` passed after adding the overlay assets to `.dockerignore`'s deployment allowlist; this confirms the new build inputs are present without relying on a prior image layer cache.
- The independent follow-up browser review is pending; see `evidence/deployment-polish-review/` for earlier screenshots and findings.
