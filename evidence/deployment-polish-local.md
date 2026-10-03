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
- A focused history-renderer check passed when no restaurant/table-label map exists: visible history uses `Table label unavailable`, raw IDs stay inside collapsed Technical details, and the timestamp remains `Jan 2, 2030, 10:00 AM (UTC+02:00)`.
- `node --check deployment/polish.js` and the deployment image build passed after the fixes.
- A fresh `docker build --no-cache -f Dockerfile.render -t tablekeeper-polish-local .` passed after adding the overlay assets to `.dockerignore`'s deployment allowlist; this confirms the new build inputs are present without relying on a prior image layer cache.
- The independent follow-up browser review is pending; see `evidence/deployment-polish-review/` for earlier screenshots and findings.

## Metadata-failure fallback follow-up

The independent browser run on `472499c` still timed out before showing the reservation when its restaurant-details request was aborted. To make the user-facing fallback independent of the browser fetch-wrapper behavior, the deployment assembler now patches only the packaged Stage 4 lookup promise: after a reservation has loaded, a failed restaurant-details lookup supplies a generic restaurant name and empty table list so Stage 4 can render the reservation. The overlay then displays `Table label unavailable` and formats history timestamps from the stored numeric offset. The protected Stage 4 source file remains unchanged.

- Temporary-directory overlay assembly passed and verified the specific lookup catch, favicon serving route, and favicon link.
- `node --check deployment/polish.js`, `git diff --check`, and the protected stage-tree diff passed.
- A no-cache Docker build was attempted but the Docker daemon did not respond; it was interrupted. This change therefore still needs independent packaged-browser verification on the new commit.

## Idempotent label fallback follow-up

The independent browser run on `13f43de` found that replacing the seating text from both the MutationObserver and retry interval caused a repeated child-list mutation. The fallback now marks the seating element after its first rewrite and skips later rewrites. This keeps the reservation panel stable while showing the unavailable-label text.

- Temporary-directory overlay assembly, packaged `app.js` and `polish.js` syntax, and a focused assertion that both fallback paths call the guarded helper passed.
- `node --check deployment/polish.js`, `git diff --check`, and the protected stage-tree comparison passed.
- Browser verification of HTTP/network metadata failure remains with the independent Verifier. Docker daemon remains unresponsive in this runtime.
