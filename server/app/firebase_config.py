from __future__ import annotations

import os
from pathlib import Path
from typing import Final

import firebase_admin
from firebase_admin import auth, credentials, firestore

_DEFAULT_SERVICE_ACCOUNT_PATH: Final[Path] = Path(__file__).resolve().parents[1] / "firebase-service-account.json"

_app: firebase_admin.App | None = None
_db: firestore.Client | None = None


def _service_account_path() -> Path:
    raw = (os.environ.get("FIREBASE_SERVICE_ACCOUNT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _DEFAULT_SERVICE_ACCOUNT_PATH


def initialize_firebase() -> firestore.Client:
    """Initialize Firebase Admin SDK + Firestore client.

    Local dev requires a service account key at:
      - $FIREBASE_SERVICE_ACCOUNT, or
      - server/firebase-service-account.json

    In production (Cloud Run, etc.), Application Default Credentials can be used.
    """

    global _app, _db

    if _db is not None:
        return _db

    sa_path = _service_account_path()
    if sa_path.exists():
        cred = credentials.Certificate(str(sa_path))
        _app = firebase_admin.initialize_app(cred)
    else:
        # Allow ADC only when it is likely configured.
        has_adc = bool((os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()) or bool(
            (os.environ.get("K_SERVICE") or "").strip()
        )
        if not has_adc:
            raise RuntimeError(
                "Firebase Admin SDK not configured. "
                f"Missing service account file at {sa_path}. "
                "Set FIREBASE_SERVICE_ACCOUNT to the key path or place the key at server/firebase-service-account.json."
            )
        _app = firebase_admin.initialize_app()

    _db = firestore.client()
    return _db


def get_firestore() -> firestore.Client:
    if _db is None:
        return initialize_firebase()
    return _db


def verify_user_token(id_token: str) -> str | None:
    """Return Firebase Auth uid if token is valid; otherwise None."""
    token = (id_token or "").strip()
    if not token:
        return None
    try:
        decoded = auth.verify_id_token(token)
    except Exception:
        return None

    uid = decoded.get("uid")
    return uid if isinstance(uid, str) and uid else None
