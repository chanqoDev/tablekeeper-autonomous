# Tablekeeper demo deployment and restore

This runbook is for the Render demo service described by `render.yaml`. The deployment
image copies the verified Stage 4 runtime files and keeps its bootstrap script and public
demo restaurant fixture in `deployment/`. Startup seeds those restaurants only when the
state has no restaurants. It does not call `/_test/reset` and does not replace a populated
state.

## Review and deploy through the Render Blueprint

Do not deploy a candidate until its exact commit has passed the independent review. Render's
Blueprint workflow is described in the [Render Blueprint docs](https://render.com/docs/infrastructure-as-code).
Manual service deploys are described in [Render deploy docs](https://render.com/docs/deploys).

1. After review, publish the approved commit to the branch connected to the Tablekeeper
   Blueprint. Check that the Blueprint points to the intended repository, branch, and
   root-level `render.yaml`.
2. If Blueprint Auto Sync is disabled, open the Blueprint in the Render Dashboard, click
   **Manual Sync**, review the proposed changes, and apply the sync. If Auto Sync is enabled,
   confirm the sync corresponds to the reviewed commit. Confirm the web service uses the
   root `Dockerfile.render` and root build context, keeps the free plan, sets `PORT=10000`,
   and uses `/health` as its health check.
3. On the web service's **Deploys** page, use **Manual Deploy → Deploy a specific commit**
   to select the reviewed SHA, then click **Deploy Commit**. If Blueprint sync already
   deployed that exact SHA, verify the active deploy instead of starting a duplicate. Wait
   for the build and deploy to finish and for the health check to pass. Render disables
   Auto Deploy when deploying a specific commit from the Dashboard; re-enable it only if
   that matches the team's deployment policy.
4. Smoke-check `/health`, `/restaurants`, and public availability. Before allowing writes,
   verify the returned restaurant names and local opening slots are expected. Perform a
   controlled booking only if a real booking is intended; canceling it is subject to the
   configured cutoff.

Keep the Stage 4 app and its bundled assets offline-capable. Do not add runtime calls to
external services. Do not put exports, credentials, bearer tokens, or private backup
locations in Git or chat.

The demo's SQLite file is in the container's ephemeral filesystem. Treat every redeploy as
a possible state replacement: export the current state privately before deployment, and
restore the chosen complete export after the service is healthy if that state must continue.

## Safe full-state restore

`POST /_test/import` **replaces the entire service state**. It does not merge. A chosen
export therefore needs to contain every account, token, reservation, receipt, policy,
history entry, series, closure, and plan that should remain after restore. A successful
import removes data that is absent from that chosen export. Never treat import as a way to
restore only restaurants.

1. Choose a new private local filename for a pre-restore export. Restrict it to the
   operator with `umask 077`; do not reuse or overwrite an older backup. For example:

   ```sh
   umask 077
   PRIVATE_EXPORT_FILE="$(mktemp "${TMPDIR:-/tmp}/tablekeeper-pre-restore.XXXXXX")"
   curl --fail --silent --show-error \
     --output "$PRIVATE_EXPORT_FILE" \
     "${DEMO_URL:?set DEMO_URL}/_test/export"
   ```

   The export can contain credentials and session tokens. Keep the file private, do not
   print its contents, and do not commit or attach it to a room message.
2. Stop application writes before choosing the state to restore. The service has no
   application-level maintenance switch. Activate an operator-controlled upstream traffic
   gate that rejects all public write requests while allowing the operator's import and
   health checks. Pause booking and account-creation clients and wait for in-flight requests
   to finish. Confirm the gate is blocking writes before continuing. Pausing clients alone
   is not a write barrier; if no traffic gate is available, do not claim writes are stopped
   or proceed with the restore.
3. Reconcile records made after the pre-restore export. Review the affected booking,
   account, and operator activity through the service and decide which records must survive.
   If any newer records must be retained, take a second private full export after writes
   have stopped and prefer that as the chosen state. Do not hand-edit the opaque `state`
   object or assume import will merge post-export records. If a required record is missing
   from the chosen complete export and cannot be preserved through a supported application
   workflow, stop and resolve that before importing.
4. Select the complete export to restore and assign its private filename to
   `CHOSEN_EXPORT_FILE`. Review the choice without printing the sensitive payload. The
   chosen file must be a complete Tablekeeper export with `track: "tablekeeper"` and
   `format_version: 1`.
5. While writes remain paused, import the chosen full export:

   ```sh
   curl --silent --show-error --output /dev/null \
     --write-out '%{http_code}\n' \
     --header 'Content-Type: application/json' \
     --data-binary "@$CHOSEN_EXPORT_FILE" \
     "${DEMO_URL:?set DEMO_URL}/_test/import"
   ```

   Require HTTP `204`. Any other status means the import was not accepted; keep writes
   paused and investigate before resuming service.
6. Check `GET /health` returns HTTP `200`. Then verify expected restaurants and safe,
   non-sensitive summaries through the API: reservations, policies/availability, and
   booking lookup for known references. Do not print account credentials, tokens, or full
   export data to shared logs.
7. Resume writes only after the restored state is confirmed. Retain or securely dispose of
   the private exports according to the operator's retention policy.

The import endpoint is unauthenticated test control. Keep the traffic gate active during
import and verification, then remove it only after the restored state is confirmed. This
runbook does not authorize an import or deployment by itself.
