"""Durable MySekai delivery state; independent of NoneBot for isolated tests.

SQLite commits happen before acknowledging HTTP, and after successful QQ sends.
A crash between a QQ send and its commit can redeliver (at-least-once delivery).
"""
import hmac
import json
import re
import sqlite3
import time
from pathlib import Path

from aiohttp import web

REGIONS = {"jp", "cn", "tw", "en"}
RETRY_SECONDS = (15, 60, 180, 300)


def validate_event(event, now_ms):
    if not isinstance(event, dict) or type(event.get("version")) is not int or event["version"] != 1:
        raise ValueError("unsupported event version")
    if not isinstance(event.get("event_id"), str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", event["event_id"]):
        raise ValueError("invalid event ID")
    if event.get("region") not in REGIONS:
        raise ValueError("unsupported region")
    if not isinstance(event.get("uid"), str) or not re.fullmatch(r"[0-9]{1,20}", event["uid"]):
        raise ValueError("UID must be a decimal string")
    for key in ("upload_time", "received_at"):
        if type(event.get(key)) is not int or not 0 < event[key] <= now_ms + 60000:
            raise ValueError("invalid timestamp")
    return {k: event[k] for k in ("version", "event_id", "region", "uid", "upload_time", "received_at")}


class DeliveryStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, handled INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                region TEXT NOT NULL, uid TEXT NOT NULL, qid INTEGER NOT NULL,
                cycle INTEGER NOT NULL, gid INTEGER NOT NULL, upload_time INTEGER NOT NULL,
                context TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                updated REAL NOT NULL, error TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (region, uid, qid, cycle)
            );
            CREATE INDEX IF NOT EXISTS jobs_due ON jobs(state, next_attempt);
        """)
        with self.db:
            self.db.execute("UPDATE jobs SET state='pending' WHERE state='running'")

    def close(self):
        self.db.close()

    def receive(self, event):
        payload = json.dumps(event, sort_keys=True, separators=(",", ":"))
        with self.db:
            existing = self.db.execute("SELECT payload FROM events WHERE id=?", (event["event_id"],)).fetchone()
            if existing:
                if existing[0] != payload:
                    raise ValueError("event ID conflicts with an existing event")
                return False
            self.db.execute("INSERT INTO events(id,payload,created) VALUES(?,?,?)", (event["event_id"], payload, time.time()))
        return True

    def events(self, limit=100):
        return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM events WHERE handled=0 ORDER BY created LIMIT ?", (limit,))]

    def handled(self, event_id):
        with self.db:
            self.db.execute("UPDATE events SET handled=1 WHERE id=?", (event_id,))

    @staticmethod
    def key(job):
        return tuple(job[k] for k in ("region", "uid", "qid", "cycle"))

    def state(self, region, uid, qid, cycle):
        row = self.db.execute("SELECT state FROM jobs WHERE region=? AND uid=? AND qid=? AND cycle=?", (region, uid, qid, cycle)).fetchone()
        return row[0] if row else None

    def enqueue(self, region, uid, qid, gid, cycle, upload_time, context, completed=False):
        if not completed and upload_time < cycle:
            return False
        key = (region, str(uid), int(qid), cycle)
        now = time.time()
        with self.db:
            row = self.db.execute("SELECT * FROM jobs WHERE region=? AND uid=? AND qid=? AND cycle=?", key).fetchone()
            if row:
                if row["state"] in ("done", "running"):
                    return False
                # New uploads or changed bindings/modes can unblock a terminal failure.
                changed = row['state'] == 'cancelled' or upload_time > row["upload_time"] or context != row["context"] or int(gid) != row["gid"]
                if row["state"] == "pending" or not changed:
                    return False
                self.db.execute("UPDATE jobs SET state='pending', attempts=0, next_attempt=0, gid=?, upload_time=?, context=?, updated=?, error='' WHERE region=? AND uid=? AND qid=? AND cycle=?", (gid, upload_time, context, now, *key))
                return True
            self.db.execute("INSERT INTO jobs(region,uid,qid,cycle,gid,upload_time,context,state,updated) VALUES(?,?,?,?,?,?,?,?,?)", (*key, int(gid), upload_time, context, "done" if completed else "pending", now))
        return not completed

    def claim(self, limit, now=None):
        now = time.time() if now is None else now
        with self.db:
            rows = self.db.execute("SELECT * FROM jobs WHERE state='pending' AND next_attempt<=? ORDER BY updated LIMIT ?", (now, limit)).fetchall()
            for row in rows:
                self.db.execute("UPDATE jobs SET state='running', attempts=attempts+1, updated=? WHERE region=? AND uid=? AND qid=? AND cycle=?", (now, *self.key(row)))
        return [dict(row, attempts=row["attempts"] + 1) for row in rows]

    def finish(self, job, state="done", error=""):
        with self.db:
            self.db.execute("UPDATE jobs SET state=?, error=?, updated=? WHERE region=? AND uid=? AND qid=? AND cycle=?", (state, error[:500], time.time(), *self.key(job)))

    def fail(self, job, error, terminal=False, now=None):
        now = time.time() if now is None else now
        attempts = job["attempts"]
        if terminal or attempts >= 5:
            self.finish(job, "failed", error)
            return False
        with self.db:
            self.db.execute("UPDATE jobs SET state='pending', error=?, next_attempt=?, updated=? WHERE region=? AND uid=? AND qid=? AND cycle=?", (error[:500], now + RETRY_SECONDS[attempts - 1], now, *self.key(job)))
        return True

    def next_delay(self):
        if self.db.execute("SELECT 1 FROM events WHERE handled=0 LIMIT 1").fetchone():
            return 0
        row = self.db.execute("SELECT min(next_attempt) FROM jobs WHERE state='pending'").fetchone()
        return max(0, row[0] - time.time()) if row[0] is not None else 3600

    def cleanup(self):
        cutoff = time.time() - 7 * 86400
        with self.db:
            self.db.execute("DELETE FROM events WHERE handled=1 AND created<?", (cutoff,))
            self.db.execute("DELETE FROM jobs WHERE cycle<? AND state!='running'", (int(cutoff * 1000),))

    def stats(self):
        return {row[0]: row[1] for row in self.db.execute("SELECT state,count(*) FROM jobs GROUP BY state")}


def create_webhook_app(store, secret, wake):
    if not secret:
        raise ValueError("MySekai webhook requires a nonempty secret")

    def authorized(request):
        return hmac.compare_digest(request.headers.get("Authorization", "").encode(), ("Bearer " + secret).encode())

    async def receive(request):
        if not authorized(request):
            raise web.HTTPUnauthorized()
        try:
            event = validate_event(await request.json(), int(time.time() * 1000))
            accepted = store.receive(event)
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text="invalid event")
        except sqlite3.Error:
            raise web.HTTPServiceUnavailable(text="event persistence failed")
        wake.set()
        return web.json_response({"status": "accepted" if accepted else "duplicate"})

    async def health(request):
        if not authorized(request):
            raise web.HTTPUnauthorized()
        return web.json_response({"status": "ok", "jobs": store.stats()})

    app = web.Application(client_max_size=16 * 1024)
    app.router.add_post("/internal/mysekai/uploaded", receive)
    app.router.add_get("/internal/mysekai/health", health)
    return app
