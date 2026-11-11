"""Accounts, free reviews and admin, kept in one SQLite file.

A free account gets DAILY_FREE_REVIEWS a day, counted per account and per phone from the jobs
table. A job that fails or gets no call doesn't count, and each job row goes after a day."""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

import google.auth.transport.requests
from google.auth.exceptions import TransportError
from google.oauth2 import id_token

DAILY_FREE_REVIEWS = 5
FIREBASE_PROJECT = "pocket-drs-app"
_DEVICE_RE = re.compile(r"[A-Za-z0-9_-]{8,128}")
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_DAY_S = 24 * 3600
_BACKUPS_KEPT = 7


def admin_emails() -> set[str]:
    raw = os.environ.get("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def valid_device(device_id: str | None) -> bool:
    return bool(device_id) and _DEVICE_RE.fullmatch(device_id) is not None


def clean_email(email: str | None) -> str | None:
    e = (email or "").strip().lower()
    return e if len(e) <= 254 and _EMAIL_RE.fullmatch(e) else None


def day_start(now: int) -> int:
    # one midnight for everyone, UTC; the clients show the reset in the phone's own time
    return now - now % _DAY_S


class AuthError(Exception):
    pass


class Refused(Exception):
    """A job this account can't start now, with the HTTP status and body to answer with."""

    def __init__(self, status: int, error: str, **extra: Any):
        super().__init__(error)
        self.status, self.body = status, {"error": error, **extra}


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
  plan TEXT NOT NULL DEFAULT 'free', created_at INTEGER NOT NULL, last_seen INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY, email TEXT NOT NULL, device_id TEXT NOT NULL, charged INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued', decision TEXT, created_at INTEGER NOT NULL, idem_key TEXT);
CREATE INDEX IF NOT EXISTS jobs_email ON jobs(email);
CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_idem ON jobs(email, idem_key) WHERE idem_key IS NOT NULL;
-- phones are counted from jobs now, and the old table kept every phone's id for ever
DROP TABLE IF EXISTS devices;
"""
# a review counts unless it failed or got no call
_COUNTED = ("SELECT COUNT(*) FROM jobs WHERE charged=1 AND status!='failed' AND IFNULL(decision,'')!='none' "
            "AND created_at>=? AND ")


class Accounts:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        with closing(self._db()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)

    def _db(self) -> sqlite3.Connection:
        # a fresh connection per call keeps threads apart; autocommit so BEGIN IMMEDIATE is ours to issue
        db = sqlite3.connect(self._path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        # one writer at a time, so two uploads can never both take the last use or both claim one key
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def _plan(self, email: str, stored: str | None) -> str:
        if email in admin_emails():
            return "admin"
        return "premium" if stored == "premium" else "free"

    def _touch(self, db: sqlite3.Connection, ident: dict[str, Any], now: int) -> None:
        db.execute(
            "INSERT INTO users(email, name, photo_url, created_at, last_seen) VALUES(?,?,?,?,?) "
            "ON CONFLICT(email) DO UPDATE SET name=excluded.name, photo_url=excluded.photo_url, "
            "last_seen=excluded.last_seen",
            (ident["email"], ident["name"], ident["photo_url"], now, now))

    def _me(self, db: sqlite3.Connection, email: str, device_id: str, now: int) -> dict[str, Any]:
        u = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        plan = self._plan(email, u["plan"] if u else None)
        start = day_start(now)
        # the phone counts too, so a second account on the same phone doesn't start the day afresh
        used = max(db.execute(_COUNTED + "email=?", (start, email)).fetchone()[0],
                   db.execute(_COUNTED + "device_id=?", (start, device_id)).fetchone()[0])
        return {
            "email": email, "name": u["name"] if u else "", "photo_url": u["photo_url"] if u else "",
            "plan": plan, "is_admin": plan == "admin", "daily_limit": DAILY_FREE_REVIEWS,
            "remaining": max(DAILY_FREE_REVIEWS - used, 0) if plan == "free" else None,
            "resets_at": start + _DAY_S,
        }

    def me(self, ident: dict[str, Any], device_id: str) -> dict[str, Any]:
        now = int(time.time())
        with closing(self._db()) as db:
            self._touch(db, ident, now)
            return self._me(db, ident["email"], device_id, now)

    def take_use(self, ident: dict[str, Any], device_id: str, job_id: str, key: str | None,
                 alive: Callable[[str], bool]) -> str:
        """Record the job and return the id to answer with (an earlier one for a repeated retry key),
        or raise Refused when the account has a job running or no free review left today."""
        now = int(time.time())
        email = ident["email"]
        with self._write() as db:
            self._touch(db, ident, now)
            row = db.execute("SELECT job_id, status, created_at FROM jobs WHERE email=? AND idem_key=?",
                             (email, key)).fetchone() if key else None
            if row is not None:
                if row["status"] != "failed" and now - row["created_at"] < _DAY_S and alive(row["job_id"]):
                    return row["job_id"]
                # a failed job doesn't count and an expired or wiped one can't be polled, so start afresh
                db.execute("UPDATE jobs SET idem_key=NULL WHERE job_id=?", (row["job_id"],))
            live = db.execute("SELECT job_id FROM jobs WHERE email=? AND status IN ('queued','running')",
                              (email,)).fetchone()
            if live is not None:
                raise Refused(409, "job_in_progress", job_id=live["job_id"])
            m = self._me(db, email, device_id, now)
            if m["remaining"] == 0:
                raise Refused(402, "daily_limit_reached", resets_at=m["resets_at"])
            db.execute("INSERT INTO jobs(job_id, email, device_id, charged, created_at, idem_key) VALUES(?,?,?,?,?,?)",
                       (job_id, email, device_id, int(m["plan"] == "free"), now, key))
            return job_id

    def record(self, job_id: str, status: str, decision: str | None = None) -> None:
        with closing(self._db()) as db:
            db.execute("UPDATE jobs SET status=?, decision=? WHERE job_id=?", (status, decision, job_id))

    def fail_unfinished(self) -> int:
        # the worker that owned these died with the last process, so they count as failed
        with closing(self._db()) as db:
            return db.execute("UPDATE jobs SET status='failed' WHERE status IN ('queued','running')").rowcount

    def delete_user(self, email: str) -> list[str]:
        """Remove the account and its jobs; returns the job ids whose folders must go too."""
        with self._write() as db:
            ids = [r[0] for r in db.execute("SELECT job_id FROM jobs WHERE email=?", (email,))]
            db.execute("DELETE FROM jobs WHERE email=?", (email,))
            db.execute("DELETE FROM users WHERE email=?", (email,))
        return ids

    def purge_jobs(self, before: int) -> None:
        with closing(self._db()) as db:
            db.execute("DELETE FROM jobs WHERE created_at<?", (before,))

    def backup(self) -> None:
        """One copy of the database per UTC day in backups/ next to it; the last week's are kept."""
        folder = self._path.parent / "backups"
        dest = folder / time.strftime("pocketdrs-%Y-%m-%d.db", time.gmtime())
        if dest.exists():
            return
        folder.mkdir(exist_ok=True)
        # written aside and renamed, so a restart mid-copy never leaves a half file that counts as done
        tmp = dest.with_suffix(".tmp")
        tmp.unlink(missing_ok=True)
        with closing(self._db()) as src, closing(sqlite3.connect(tmp)) as dst:
            src.backup(dst)
        os.replace(tmp, dest)
        for old in sorted(folder.glob("pocketdrs-*.db"))[:-_BACKUPS_KEPT]:
            old.unlink()

    # admin

    _USERS = "SELECT u.*, (SELECT COUNT(*) FROM jobs j WHERE j.email=u.email) AS jobs FROM users u "

    def _user(self, r: sqlite3.Row) -> dict[str, Any]:
        return {"email": r["email"], "name": r["name"], "plan": self._plan(r["email"], r["plan"]),
                "jobs": r["jobs"], "created_at": r["created_at"], "last_seen": r["last_seen"]}

    def list_users(self, q: str = "") -> list[dict[str, Any]]:
        with closing(self._db()) as db:
            rows = db.execute(self._USERS + "WHERE instr(u.email, ?) ORDER BY u.created_at DESC, u.email LIMIT 500",
                              (q.strip().lower(),)).fetchall()
        return [self._user(r) for r in rows]

    def update_user(self, email: str, plan: str) -> dict[str, Any]:
        now = int(time.time())
        with closing(self._db()) as db:
            # a row made before the person signs in lets premium be granted ahead of time
            db.execute("INSERT INTO users(email, created_at, last_seen) VALUES(?,?,?) ON CONFLICT(email) DO NOTHING",
                       (email, now, now))
            db.execute("UPDATE users SET plan=? WHERE email=?", (plan, email))
            return self._user(db.execute(self._USERS + "WHERE u.email=?", (email,)).fetchone())

    def list_jobs(self, email: str = "") -> list[dict[str, Any]]:
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT job_id, email, device_id, status, decision, created_at FROM jobs "
                "WHERE ?='' OR email=? ORDER BY created_at DESC, rowid DESC LIMIT 50", (email, email)).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, int]:
        today = day_start(int(time.time()))
        admins = list(admin_emails())
        marks = ",".join("?" * len(admins)) or "''"
        with closing(self._db()) as db:
            one = lambda sql, *a: db.execute(sql, a).fetchone()[0]  # noqa: E731
            return {
                "users": one("SELECT COUNT(*) FROM users"),
                "premium": one(f"SELECT COUNT(*) FROM users WHERE plan='premium' AND email NOT IN ({marks})", *admins),
                "jobs_today": one("SELECT COUNT(*) FROM jobs WHERE created_at>=?", today),
                "failed_today": one("SELECT COUNT(*) FROM jobs WHERE created_at>=? AND status='failed'", today),
            }


def default_accounts() -> Accounts:
    return Accounts(Path(os.environ.get("POCKET_DRS_DB", "/data/pocketdrs.db")))
