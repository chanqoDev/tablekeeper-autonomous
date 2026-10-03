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
