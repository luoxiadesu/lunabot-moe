# Sekai Deck Recommend Service for LunaBot

### Usage

1. Install dependencies (Python 3.8+ required):

```bash
pip install -r requirements.txt
```

2. Configure the service by editing the `config.yaml`.

3. Run the service:

```bash
python serve.py
```

4. Add the service to LunaBot by updating the bot's configuration file `config/sekai/sekai.yaml`

### Haruki engine migration (0.4.2)

Both the bot and this service use `haruki-sekai-deck-recommend-cpp==0.4.2` from
[Team-Haruki](https://github.com/Team-Haruki/sekai-deck-recommend-cpp). The Python
import remains `sekai_deck_recommend_cpp`. **Uninstall the old
`sekai-deck-recommend-cpp` distribution before installing the new package**:
they own the same import directory and cannot safely coexist in one environment.
Python 3.10+ is required; official Linux wheels avoid compiling on production.

The existing compressed HTTP interfaces remain `/update_data`, `/cache_userdata`
and `/recommend`. `GET /health` reports engine distribution/version, data schema
and live worker count. The bot's normal commands, default algorithms and time
budgets are retained; new algorithms such as `dfs_ga`/`rl` are accepted by the
engine, but are not silently made the default. Internal C++ threading stays at
one thread per worker (`DECK_ENGINE_THREADS=1`).

`data_schema_version=2` forces the one-time synchronization of additional activity
bonus/limit and note/combo master tables even when the game's version has not
changed. Missing optional files (HTTP 404) are sent as empty arrays for that
region; transient HTTP errors abort synchronization and back off per region.
Scoring data with null, non-finite or malformed required fields is excluded from
both native input and the synthetic random-song average, with a warning listing
omitted songs. Incomplete song/difficulty queries return a clear error instead
of substituting zero scoring values. Unchanged updates no longer rewrite the DB.

Each worker processes one RPC at a time, including user-data cache broadcasts.
On a native crash or timeout, the process and both queues are rebuilt; the bounded
parent cache can restore user data into the replacement worker. Requests in flight
fail clearly and subsequent requests can continue. Undersized candidate pools
return an empty deck list before entering C++, preserving multi-character batches.
The engine itself is used unmodified; a direct unguarded request to 0.4.2 with an
empty challenge character pool was observed to crash in isolated migration tests.

Tests (after installing service requirements):

```bash
python -m unittest discover -s tests -p test_deck_adapter.py -v  # repository root
```

Before production replacement, test on another localhost port with a copy of the
data directory. Back up the old wheel/package, source, config and recommendation
data; stop bot and service before replacing their shared Python distribution.
Restore the old package and source together when rolling back. User captures
remain untouched throughout migration.
