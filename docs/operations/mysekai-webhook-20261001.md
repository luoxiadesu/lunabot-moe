# MySekai Webhook deployment — 2026-10-01

Production host: `47.91.23.232`. Bot directory: `/bot/lunabot`.
Upload namespace: `environment-69fc7550e5ed304c1d8452c1`.
Upload Deployment/Service: `service-69fceacaa96f65f4370df127`.

- Bot receiver: `http://10.42.0.1:11452/internal/mysekai/uploaded`.
- Bot-to-upload origin: `http://10.43.105.78:8080`.
- Public uploads remain at `https://upload.luoxiadesu.com`.
- Secret: Kubernetes `lunabot-mysekai-webhook`, key `token`; matching token in
  bot runtime YAML. Values are not stored in either source repository.
- Image: `docker.io/lunabot-local/sekai-upload:mysekai-webhook-20261001`, imported
  into k3s. Manifest index digest:
  `sha256:702a2e8f873dfd5a75d16a938346d22b388846394bae7b0697d626d78b64e6ee`.
- Reconciliation: 300 seconds; original interval was 3 seconds.
- Backup: `/bot/lunabot-backups/mysekai-webhook-20261001-191032`.
- Backup locator: `/root/lunabot-webhook-backup-path`.
- Final bot source installed at approximately 11:17 UTC. Notification rollout
  completed around 11:13 UTC; polling/internal-origin cutover at 11:14 UTC.

## Verification

Local tests cover bot persistence, queue deduplication, retry limits, permissions
and cycle changes, QQ null returns, source selection, reconciliation, rollback
record failures, and process interruption. Upload tests include race detection,
outbox retry/recovery, redirects/timeouts, source routes, save failures, and
cache invalidation. Go-to-Python integration was exercised locally with both
actual HTTP services and no QQ calls.

Production receiver authenticates requests from the upload Pod. Missing tokens
return 401 and malformed authenticated callbacks return 400. Both public and
internal upload health endpoints return 200. SQLite integrity check passed.

13 existing current-cycle completion records were preserved. One further natural
upload succeeded through the queue during the polling transition. Three subsequent
natural uploads were notified through Webhook, persisted and sent successfully
on attempt 1. The first two upload-to-receiver times were 5.6 ms and 5.3 ms; their
upload-to-QQ-confirmed times including rendering were 12.47 s and 9.03 s.
The third notification arrived in 5.1 ms and delivery completed in 11.4 s,
also without retries. Timestamp queries were
confirmed to originate from `10.42.0.1`; no subscription PUTs remained.

A 45-second idle sample measured upload below CPU tick resolution (displayed as
0.0% of one core) and bot at 1.111%. These are short samples, not a guarantee
for active image rendering or actual upload processing. Warm timestamp queries
were logged as 0 ms (rounded); pre-change CN query average was about 384 ms.

The 15.5-minute observation recorded 8 timestamp queries total (including
cutover/restart queries), 3 delivered notifications, no webhook errors, no
pending/failed jobs and no upload container restarts. The normal background
rate is 2 queries every 5 minutes: about 576/day instead of 115,200/day
(99.5% fewer background requests), plus actual uploads/deliveries.

Final observation evidence is stored beside the server backup:
`observation-summary.json`, `cpu-sample.json`, and
`natural-upload-validation.json`.

## Rollback

A syntax-checked rollback helper is saved as `rollback.py` inside the server
backup. The repository copy is `docs/operations/rollback_mysekai_webhook.py`.
Run with `/bot/lunabot/venv/bin/python` on the production host only when rollback
is intended. It restores the old upload image, stops bot, merges successful SQLite
jobs into the current legacy JSON DB, restores old code/config, and starts bot.
It leaves captures, SQLite history, the outbox and Kubernetes Secret intact.

The helper restores saved configuration files in full. Review intervening config
changes before using it later. Future Zeabur rebuilds must include the new upload
source/configuration; a platform redeploy can overwrite a manually patched image.
