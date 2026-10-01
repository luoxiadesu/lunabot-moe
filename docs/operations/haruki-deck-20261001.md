# Haruki deck engine migration — 2026-10-01

Production host: `47.91.23.232`; bot: `/bot/lunabot`.
Engine source: https://github.com/Team-Haruki/sekai-deck-recommend-cpp
Installed release: `haruki-sekai-deck-recommend-cpp==0.4.2`.
The previous `sekai-deck-recommend-cpp==0.2.21` distribution was uninstalled before
installation because both packages own the same `sekai_deck_recommend_cpp` module.
Official cp311 x86_64 manylinux wheel was used. The upstream C++ repository was
inspected without modifying it; local checkout is `/home/luoxia/dev/sekai-deck-recommend-cpp`.

## Behavior and adapter changes

Existing commands, response images, server port 45556, worker count 4, default
DFS+GA algorithm choice and time budgets are retained. New native result fields
remain available, while the bot continues to display its existing fields.

- Added schema version 2 to data synchronization. Six additional activity
  limit/honor/combo/note tables are synced from the selected region masterdata
  source. HTTP 404 represents an absent optional table; other errors back off.
- Incomplete/non-finite scoring data is excluded rather than made zero. KR song
  707 currently has six incomplete difficulty rows; all other data initializes.
- Fixed batch result aggregation accidentally using the final request's options
  for every result's sort/limit.
- Serialized cache/recommend RPCs per worker to prevent concurrent callers from
  consuming one another's responses. Crashed/timed-out workers are killed/reaped
  and respawned with new queues. A bounded parent cache restores user data.
- Empty/undersized pools return an empty result before entering C++; this preserves
  all-character challenge batches even when the user owns no cards for a character.
- Unchanged data checks no longer rewrite `deckrec.json` every 30 seconds.
- FastAPI lifespan starts/stops workers and checks the engine distribution version.
  `GET /health` reports engine version and live worker counts.
- `DECK_ENGINE_THREADS=1` is set via
  `/etc/systemd/system/lunabot-deck-recommender.service.d/haruki-engine.conf` to
  avoid adding nested parallelism to four existing worker processes.

## Validation and limits

Upstream Python binding tests: 28 passed using the official wheel.
Adapter tests: 10 passed locally and on server, including failed-process recovery,
timeout recovery, concurrent cache requests, metadata handling, schema migration,
option compatibility and actual bot result sorting with mixed request targets.
Existing MySekai delivery tests: 19 passed.

An isolated service on localhost:45557 with copied data ran 24 CN/JP requests:
multi/solo/auto, MySekai, challenge/challenge_auto, DFS/GA/DFS_GA, power, bonus,
random-song metadata and World Bloom. All passed; insufficient-card cases returned
empty results. Five regions' native master/music data loads also passed.
The same 24 requests passed against the production localhost:45556 service after
cutover. Results were checked for card uniqueness/count, positive power and
expected response fields. Actual LunaBot client functions were exercised against
the new service without loading plugins or sending QQ messages: multi, MySekai
and challenge parsed DFS+GA results; bonus parsed DFS results. An initial synthetic
bonus+GA request correctly returned "Bonus target only supports DFS algorithm";
LunaBot's real bonus-command parser already selects DFS, and the corrected client
verification passed. This was a test-input mismatch, not a changed user command.

These are integration/structural checks, not proof that every event's game score
is identical to the client. The maintained engine intentionally includes new
scoring rules. Observed per-request computation ranged from milliseconds to
hundreds of milliseconds in the tested inputs; this excludes image rendering,
upstream user-data downloads, and larger/peak searches.

A direct unguarded 0.4.2 call with a JP account owning no cards for challenge
character 1 segfaulted in an isolated interpreter. Production was unaffected.
The adapter precheck prevents that tested case and process isolation handles
other native failures, but the upstream wheel should not be called directly on
arbitrary inputs without equivalent safeguards.

## Deployment and rollback

Migration staging and backup: `/bot/lunabot-deck-migration-20261001`.
`backup/` contains the old Python package and dist-info, old bot/service source,
service config and compressed recommendation data. No user captures were altered.
`smoke.py` and `smoke-results.json` retain the read-only integration procedure and
summarized outcomes; private user data was never copied into the Git repository.

Both bot and recommendation service were stopped before changing the shared
virtualenv. Validated data was copied, schema markers invalidated once, and both
services started. The bot completed schema-2 synchronization for JP, EN, TW, KR,
CN; the KR retry loop recovered. Production reports four live workers, version
0.4.2, with no automatic service restarts. The temporary service was stopped.

Rollback helper: `/bot/lunabot-deck-migration-20261001/rollback.py` (syntax-checked,
not executed). It stops both services, removes the new distribution, restores the
old package/source/data/config and starts both services. MySekai Webhook state and
user uploads are untouched. Review later changes before restoring old snapshots.
The service retains its existing crash restart and daily restart scheduling.
After synchronization, a 40-second observation confirmed unchanged update polls
did not touch the metadata DB's mtime. No subsequent bot data-sync failures,
production native process crashes, or worker timeouts were observed. Local and
server SHA256 hashes match for the four runtime implementation files.
