"""Accounts, free reviews and admin, kept in one SQLite file.

A free account gets FREE_ANALYSES reviews, counted per account and per device. A use is taken
when a job is accepted and given back once if that job fails."""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import google.auth.transport.requests
from google.auth.exceptions import TransportError
from google.oauth2 import id_token

FREE_ANALYSES = 5
FIREBASE_PROJECT = "pocket-drs-app"
CONTACT_EMAIL = "kafleniraj@gmail.com"
_DEVICE_RE = re.compile(r"[A-Za-z0-9_-]{8,128}")
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# nepal has no daylight saving, so "today" for the owner is a fixed offset
_NPT = timezone(timedelta(hours=5, minutes=45))


def admin_emails() -> set[str]:
    raw = os.environ.get("ADMIN_EMAILS", CONTACT_EMAIL)
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def valid_device(device_id: str | None) -> bool:
    return bool(device_id) and _DEVICE_RE.fullmatch(device_id) is not None


def clean_email(email: str | None) -> str | None:
    e = (email or "").strip().lower()
    return e if len(e) <= 254 and _EMAIL_RE.fullmatch(e) else None


class AuthError(Exception):
    pass


# google's signing keys rotate slowly; keep each response for an hour instead of fetching it per call
class _CachedRequest(google.auth.transport.requests.Request):
    _ttl_s = 3600

    def __init__(self) -> None:
        super().__init__()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def __call__(self, url, method="GET", body=None, headers=None, timeout=10, **kwargs):  # type: ignore[override]
        if method != "GET" or body is not None:
            return super().__call__(url, method=method, body=body, headers=headers, timeout=timeout, **kwargs)
        with self._lock:
            hit = self._cache.get(url)
            if hit and time.monotonic() - hit[0] < self._ttl_s:
                return hit[1]
        resp = super().__call__(url, method=method, headers=headers, timeout=timeout, **kwargs)
        if resp.status == 200:
            with self._lock:
                self._cache[url] = (time.monotonic(), resp)
        return resp


_request = _CachedRequest()


def verify_token(auth_header: str | None) -> dict[str, Any]:
    """Return {email, name, photo_url} for a valid Firebase ID token, or raise AuthError."""
    parts = (auth_header or "").split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthError("no token")
    try:
        claims = id_token.verify_firebase_token(parts[1].strip(), _request, audience=FIREBASE_PROJECT,
                                                clock_skew_in_seconds=10)
    except TransportError:
        raise
    except Exception as e:  # noqa: BLE001 - expired, bad signature, wrong project
        raise AuthError(f"bad token: {e}") from e
    if not claims or claims.get("iss") != f"https://securetoken.google.com/{FIREBASE_PROJECT}":
        raise AuthError("wrong issuer")
    email = clean_email(claims.get("email"))
    if email is None:
        raise AuthError("no email on the account")
    if claims.get("email_verified") is not True:
        raise AuthError("email not verified")
    return {"email": email, "name": claims.get("name") or "", "photo_url": claims.get("picture") or ""}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  email TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', photo_url TEXT NOT NULL DEFAULT '',
  plan TEXT NOT NULL DEFAULT 'free', used INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL, last_seen INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS devices (
  device_id TEXT PRIMARY KEY, used INTEGER NOT NULL DEFAULT 0,
  last_email TEXT NOT NULL DEFAULT '', last_seen INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY, email TEXT NOT NULL, device_id TEXT NOT NULL,
  charged INTEGER NOT NULL, refunded INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'queued', created_at INTEGER NOT NULL, idem_key TEXT);
CREATE INDEX IF NOT EXISTS jobs_email ON jobs(email);
CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created_at);
"""


class Accounts:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(path)
        with closing(self._db()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
            # databases made before retry keys existed get the column added; their old rows stay as they are
            if "idem_key" not in [r[1] for r in db.execute("PRAGMA table_info(jobs)")]:
                db.execute("ALTER TABLE jobs ADD COLUMN idem_key TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS jobs_idem ON jobs(email, idem_key) WHERE idem_key IS NOT NULL")

    def _db(self) -> sqlite3.Connection:
        # a fresh connection per call keeps threads apart; autocommit so BEGIN IMMEDIATE is ours to issue
        db = sqlite3.connect(self._path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def _plan(self, email: str, stored: str | None) -> str:
        if email in admin_emails():
            return "admin"
        return "premium" if stored == "premium" else "free"

    def _touch(self, db: sqlite3.Connection, ident: dict[str, Any], device_id: str | None, now: int) -> None:
        db.execute(
            "INSERT INTO users(email, name, photo_url, created_at, last_seen) VALUES(?,?,?,?,?) "
            "ON CONFLICT(email) DO UPDATE SET name=excluded.name, photo_url=excluded.photo_url, "
            "last_seen=excluded.last_seen",
            (ident["email"], ident["name"], ident["photo_url"], now, now))
        if device_id:
            db.execute(
                "INSERT INTO devices(device_id, last_email, last_seen) VALUES(?,?,?) "
                "ON CONFLICT(device_id) DO UPDATE SET last_email=excluded.last_email, last_seen=excluded.last_seen",
                (device_id, ident["email"], now))

    def _me(self, db: sqlite3.Connection, email: str, device_id: str | None) -> dict[str, Any]:
        u = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        d = db.execute("SELECT used FROM devices WHERE device_id=?", (device_id,)).fetchone() if device_id else None
        plan = self._plan(email, u["plan"] if u else None)
        used = u["used"] if u else 0
        device_used = d["used"] if d else 0
        free = plan == "free"
        return {
            "email": email, "name": u["name"] if u else "", "photo_url": u["photo_url"] if u else "",
            "plan": plan, "is_admin": plan == "admin", "free_limit": FREE_ANALYSES,
            "used": used, "remaining": max(FREE_ANALYSES - used, 0) if free else None,
            "device_used": device_used,
            "device_remaining": max(FREE_ANALYSES - device_used, 0) if free else None,
            "contact_email": CONTACT_EMAIL,
        }

    def me(self, ident: dict[str, Any], device_id: str | None) -> dict[str, Any]:
        with closing(self._db()) as db:
            self._touch(db, ident, device_id, int(time.time()))
            return self._me(db, ident["email"], device_id)

    def can_start(self, email: str, device_id: str) -> bool:
        with closing(self._db()) as db:
            m = self._me(db, email, device_id)
        return m["remaining"] != 0 and m["device_remaining"] != 0

    @staticmethod
    def _keyed(db: sqlite3.Connection, email: str, key: str | None, now: int) -> str | None:
        """The job this retry key already started, if it is under a day old and did not fail."""
        if not key:
            return None
        row = db.execute("SELECT job_id, status, created_at FROM jobs WHERE email=? AND idem_key=?",
                         (email, key)).fetchone()
        if row is None:
            return None
        if row["status"] != "failed" and now - row["created_at"] < 24 * 3600:
            return row["job_id"]
        # a failed or expired job gave its use back, so the same key may start a fresh one
        db.execute("UPDATE jobs SET idem_key=NULL WHERE job_id=?", (row["job_id"],))
        return None

    def find_keyed(self, email: str, key: str | None) -> str | None:
        with closing(self._db()) as db:
            row = db.execute("SELECT job_id, status, created_at FROM jobs WHERE email=? AND idem_key=?",
                             (email, key)).fetchone() if key else None
        if row and row["status"] != "failed" and time.time() - row["created_at"] < 24 * 3600:
            return row["job_id"]
        return None

    def forget_key(self, email: str, key: str) -> None:
        with closing(self._db()) as db:
            db.execute("UPDATE jobs SET idem_key=NULL WHERE email=? AND idem_key=?", (email, key))

    def take_use(self, ident: dict[str, Any], device_id: str, job_id: str, key: str | None = None) -> str | None:
        """Record the job and take one free use if needed. Returns the job id to answer with (an earlier
        one for a repeated retry key), or None when no free use is left."""
        now = int(time.time())
        db = self._db()
        try:
            # one writer at a time, so two uploads can never both take the last use or both claim one key
            db.execute("BEGIN IMMEDIATE")
            self._touch(db, ident, device_id, now)
            earlier = self._keyed(db, ident["email"], key, now)
            if earlier:
                db.execute("COMMIT")
                return earlier
            m = self._me(db, ident["email"], device_id)
            charged = 1 if m["plan"] == "free" else 0
            if charged and (m["remaining"] == 0 or m["device_remaining"] == 0):
                db.execute("COMMIT")
                return None
            db.execute("INSERT INTO jobs(job_id, email, device_id, charged, created_at, idem_key) "
                       "VALUES(?,?,?,?,?,?)", (job_id, ident["email"], device_id, charged, now, key))
            if charged:
                db.execute("UPDATE users SET used=used+1 WHERE email=?", (ident["email"],))
                db.execute("UPDATE devices SET used=used+1 WHERE device_id=?", (device_id,))
            db.execute("COMMIT")
            return job_id
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def finish(self, job_id: str, status: str) -> None:
        """Store how a job ended; a failed one gives its use back, and only ever once."""
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT email, device_id, charged, refunded FROM jobs WHERE job_id=?",
                             (job_id,)).fetchone()
            if row is not None:
                db.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))
                if status == "failed" and row["charged"] and not row["refunded"]:
                    db.execute("UPDATE jobs SET refunded=1 WHERE job_id=?", (job_id,))
                    # a reset in between may already have zeroed the count, so never go below 0
                    db.execute("UPDATE users SET used=MAX(used-1,0) WHERE email=?", (row["email"],))
                    db.execute("UPDATE devices SET used=MAX(used-1,0) WHERE device_id=?", (row["device_id"],))
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def fail_unfinished(self) -> int:
        # the worker that owned these died with the last process, so they count as failed
        with closing(self._db()) as db:
            ids = [r[0] for r in db.execute("SELECT job_id FROM jobs WHERE status IN ('queued','running')")]
        for jid in ids:
            self.finish(jid, "failed")
        return len(ids)

    # admin

    def list_users(self, q: str = "") -> list[dict[str, Any]]:
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT u.*, (SELECT COUNT(*) FROM jobs j WHERE j.email=u.email) AS jobs FROM users u "
                "WHERE u.email LIKE ? ORDER BY u.created_at DESC, u.email LIMIT 500",
                (f"%{q.strip().lower()}%",)).fetchall()
        return [{"email": r["email"], "name": r["name"], "plan": self._plan(r["email"], r["plan"]),
                 "used": r["used"], "jobs": r["jobs"], "created_at": r["created_at"], "last_seen": r["last_seen"]}
                for r in rows]

    def update_user(self, email: str, plan: str | None, reset_used: bool) -> dict[str, Any]:
        now = int(time.time())
        with closing(self._db()) as db:
            # a row made before the person signs in lets premium be granted ahead of time
            db.execute("INSERT INTO users(email, created_at, last_seen) VALUES(?,?,?) ON CONFLICT(email) DO NOTHING",
                       (email, now, now))
            if plan is not None:
                db.execute("UPDATE users SET plan=? WHERE email=?", (plan, email))
            if reset_used:
                db.execute("UPDATE users SET used=0 WHERE email=?", (email,))
                # their phones count too, or the person stays blocked after a reset
                db.execute("UPDATE devices SET used=0 WHERE device_id IN (SELECT device_id FROM jobs WHERE email=?)",
                           (email,))
        return next(u for u in self.list_users(email) if u["email"] == email)

    def list_devices(self, q: str = "") -> list[dict[str, Any]]:
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT * FROM devices WHERE device_id LIKE ? OR last_email LIKE ? "
                "ORDER BY last_seen DESC LIMIT 500", (f"%{q.strip()}%", f"%{q.strip().lower()}%")).fetchall()
        return [dict(r) for r in rows]

    def reset_device(self, device_id: str) -> bool:
        with closing(self._db()) as db:
            return db.execute("UPDATE devices SET used=0 WHERE device_id=?", (device_id,)).rowcount == 1

    def stats(self) -> dict[str, int]:
        start = datetime.now(_NPT).replace(hour=0, minute=0, second=0, microsecond=0)
        today = int(start.timestamp())
        admins = list(admin_emails())
        marks = ",".join("?" * len(admins)) or "''"
        with closing(self._db()) as db:
            one = lambda sql, *a: db.execute(sql, a).fetchone()[0]  # noqa: E731
            return {
                "users": one("SELECT COUNT(*) FROM users"),
                "premium": one(f"SELECT COUNT(*) FROM users WHERE plan='premium' AND email NOT IN ({marks})", *admins),
                "jobs_today": one("SELECT COUNT(*) FROM jobs WHERE created_at>=?", today),
                "jobs_total": one("SELECT COUNT(*) FROM jobs"),
                "failed_today": one("SELECT COUNT(*) FROM jobs WHERE created_at>=? AND status='failed'", today),
            }


def default_accounts() -> Accounts:
    return Accounts(Path(os.environ.get("POCKET_DRS_DB", "/data/pocketdrs.db")))
