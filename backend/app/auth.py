"""API keys, roles and a small token-bucket rate limiter.

Roles: admin > jury > ui. The jury key comes from API_KEY (or storage/api_key.txt); extra keys can be
issued through /admin/api/keys and are stored hashed.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException, Query, Request

from .config import get_settings
from .db import Database

ROLE_RANK = {"ui": 0, "jury": 1, "admin": 2}


@dataclass
class Principal:
    role: str
    name: str
    key_prefix: str = ""

    def allows(self, role: str) -> bool:
        return ROLE_RANK.get(self.role, -1) >= ROLE_RANK[role]


class KeyStore:
    def __init__(self, db: Database):
        self.db = db
        s = get_settings()
        self._env_keys: dict[str, Principal] = {}
        jury = s.resolve_api_key()
        self._env_keys[jury] = Principal("jury", "jury", jury[:4])
        admin = s.resolve_admin_key()
        self._env_keys.setdefault(admin, Principal("admin", "admin", admin[:4]))
        if admin == jury:
            self._env_keys[jury] = Principal("admin", "jury+admin", jury[:4])

    @property
    def jury_key(self) -> str:
        return get_settings().resolve_api_key()

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def verify(self, key: str | None) -> Principal | None:
        if not key:
            return None
        for k, p in self._env_keys.items():
            if hmac.compare_digest(k, key):
                return p
        row = self.db.one("SELECT * FROM api_keys WHERE key_hash=? AND disabled=0", (self._hash(key),))
        if row is None:
            return None
        self.db.update("api_keys", "id", row["id"], {"last_used_at": time.time()})
        return Principal(row["role"], row["name"] or f"key-{row['id']}", row["prefix"])

    def create(self, role: str, name: str) -> tuple[str, int]:
        if role not in ROLE_RANK:
            raise ValueError(f"unknown role {role!r}")
        key = secrets.token_urlsafe(24)
        kid = self.db.insert("api_keys", {"key_hash": self._hash(key), "prefix": key[:4], "role": role,
                                          "name": name, "created_at": time.time()})
        return key, kid

    def list(self) -> list[dict]:
        rows = self.db.all("SELECT id, prefix, role, name, disabled, created_at, last_used_at FROM api_keys ORDER BY id")
        return rows

    def revoke(self, kid: int) -> bool:
        return self.db.update("api_keys", "id", kid, {"disabled": 1}) > 0


class RateLimiter:
    """Token bucket per subject (API key or client IP)."""

    def __init__(self, per_minute: int, burst: int | None = None):
        self.rate = per_minute / 60.0
        self.burst = burst or max(1, per_minute)
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, subject: str, cost: float = 1.0) -> bool:
        if self.rate <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(subject, (float(self.burst), now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens < cost:
                self._buckets[subject] = (tokens, now)
                return False
            self._buckets[subject] = (tokens - cost, now)
            return True


# ----------------------------------------------------------------------------- FastAPI deps

def _store(request: Request) -> KeyStore:
    return request.app.state.st.keys


def _extract(x_api_key: str | None, authorization: str | None, key_q: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return key_q


def require_role(role: str):
    def dep(request: Request,
            x_api_key: str | None = Header(default=None, alias="X-API-Key"),
            authorization: str | None = Header(default=None),
            key: str | None = Query(default=None)) -> Principal:
        p = _store(request).verify(_extract(x_api_key, authorization, key))
        if p is None:
            raise HTTPException(status_code=401, detail="Неверный или отсутствующий X-API-Key")
        if not p.allows(role):
            raise HTTPException(status_code=403, detail="Недостаточно прав для этой операции")
        request.state.principal = p
        return p
    return dep


def ui_access(request: Request,
              x_api_key: str | None = Header(default=None, alias="X-API-Key"),
              authorization: str | None = Header(default=None),
              key: str | None = Query(default=None)) -> Principal:
    """UI endpoints: open by default, any valid key when UI_REQUIRE_KEY=1."""
    raw = _extract(x_api_key, authorization, key)
    p = _store(request).verify(raw) if raw else None
    if get_settings().ui_require_key and p is None:
        raise HTTPException(status_code=401, detail="Нужен X-API-Key (UI_REQUIRE_KEY=1)")
    p = p or Principal("ui", "anonymous")
    request.state.principal = p
    return p


def rate_limit_subject(request: Request) -> str:
    p = getattr(request.state, "principal", None)
    if p is not None and p.key_prefix:
        return f"key:{p.name}:{p.key_prefix}"
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"
