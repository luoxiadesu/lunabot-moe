# MySekai upload notifications

The uploader sends small events after saving MySekai captures. LunaBot persists
received events and delivery jobs in `data/sekai/msr_delivery.sqlite3` (SQLite WAL,
FULL synchronous commits). It acknowledges HTTP only after committing the event.
Drawing and QQ delivery run separately, with `msr_push_concurrency` workers.

## Configuration

```yaml
mysekai:
  msr_push_interval_seconds: 300
  msr_push_concurrency: 4
  webhook:
    enabled: true
    host: 10.42.0.1
    port: 11452
    secret: "<shared-secret>"
```

Use the host's private CNI bridge address only where reachable from the upload
Pod. Do not expose this listener through a public Ingress. Keep the existing
OneBot listener on localhost. Both services must use the same randomly generated
secret. Restart the bot when changing listener settings or its secret.

Change only upload-owned URLs in `config/sekai/gameapi.yaml` to the upload's
ClusterIP Service origin (this deployment: `http://10.43.105.78:8080`). Do not use
Pod IPs. Retain public URLs in phone capture modules. ClusterIP survives Pod
replacement but must be updated if the Service itself is recreated.

## Interface and delivery behavior

`POST /internal/mysekai/uploaded`, `Authorization: Bearer <shared-secret>`:

```json
{"version":1,"event_id":"unique-identifier","region":"cn","uid":"7488916117617056521","upload_time":1790841600000,"received_at":1790841600100}
```

Times are Unix milliseconds, UID is a string, maximum body is 16 KiB. Successful
and duplicate events return HTTP 200. Unauthorized requests return 401, malformed
or conflicting events 400, oversized bodies 413, and unavailable storage 503.
`GET /internal/mysekai/health` with the same authentication reports queue states.

Events outside the current resource cycle are acknowledged then ignored. Five
minute reconciliation and startup reconciliation recover missed notifications;
queries are deduplicated and exclude completed/running/pending users. No unused
subscription snapshots are sent. Slow reconciliation uses a fixed delay and does
not catch up missed timer ticks. No new Haruki polling is introduced.

The delivery key is region + game UID + QQ user + resource cycle. Existing JSON
push timestamps seed completed jobs to prevent duplicate sends during migration.
Current-cycle uploads older than ten minutes are allowed. Birthday boundaries
use the existing region refresh function. Source selection remains local/Haruki/
latest as chosen by the user, including external requests when fetching latest.

A QQ message ID confirms completion. Null results (offline bot, disabled group,
rate limit) do not count as success. Transient failures get at most five attempts
with delays 15/60/180/300 seconds. Terminal incomplete/invalid data waits for a
new upload or changed binding/mode. Cancellation due to permissions can be
reconsidered once eligible again. Jobs and processed events are retained seven
days. Unprocessed events survive restarts. Failures log locally and never spam
the group with retry messages.

Delivery is at-least-once: a crash after QQ accepted a message but before local
confirmation can cause a duplicate. Completion records use the data cycle rather
than wall-clock send time, so a late send cannot consume the next cycle.

## Validation and staged rollout

Run `python3 -m unittest discover -s tests -v` and compile the changed modules.
Tests load the queue independently and execute delivery functions with simulated
QQ APIs; they never send group messages. The upload repository contains separate
outbox, cache, HTTP integration and concurrency tests.

1. Back up both bot code files, runtime YAML configuration and prior push state;
   save the Kubernetes Deployment and old image reference securely.
2. Deploy the bot receiver first, initially keeping the existing polling interval.
   Both events and polling now use the same SQLite jobs and deduplication.
3. Build/load a uniquely tagged upload image into k3s, preserve `/app/data`, and
   enable its webhook environment settings using a Kubernetes Secret.
4. From the Pod, authenticate to the health endpoint; also confirm missing
   authentication is rejected. Do not create fake user uploads or send test QQ
   messages in production.
5. Set reconciliation to 300 seconds and upload URLs to the internal Service.
   The config reloads automatically. Monitor request counts, upload latency,
   process CPU, queue states and webhook failures for at least 15 minutes.
6. Wait for a natural upload to confirm real notification and delivery. Report
   that check as pending if no subscribed user uploads during observation.

## Rollback

Disable upload notifications, stop the bot, and export SQLite `state='done'`
records into the legacy `data/sekai/db.json` maps named
`{region}_msr_last_push_time`, keys `{uid}-{qid}`. Use `max(existing, cycle)`;
never replace the entire current DB with an old snapshot because other bot data
may have changed. Restore backed-up code and relevant YAML settings, restart the
bot and restore the old upload image if required. Keep the SQLite files and
outbox data. Do not delete the persistent volume or capture data.

A manually imported k3s image and Deployment patch can be replaced by a later
Zeabur redeploy. For subsequent platform releases include the new source and
webhook environment variables, preserving the Secret and existing volume.
