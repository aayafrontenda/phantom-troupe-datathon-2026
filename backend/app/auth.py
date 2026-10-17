"""Who is calling: API keys (jury / admin / scripts) and user sessions (operator / supervisor / admin).

Key roles: ui < jury < admin (X-API-Key). User roles: operator < supervisor < admin (cookie session).
An admin key behaves like an admin user on the UI API, so scripts and tests can use it everywhere.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, Query, Request, WebSocket

from .config import get_settings
from .db import Database
from .users import SESSION_COOKIE, USER_RANK

ROLE_RANK = {"ui": 0, "jury": 1, "admin": 2}


@dataclass
class Principal:
    role: str                    # ui | jury | admin | operator | supervisor
    name: str
    key_prefix: str = ""
    user_id: int | None = None
    camera_ids: list[str] | None = None
    kind: str = "key"            # key | user | anon
    display_name: str = ""
    extra: dict = field(default_factory=dict)

    def allows(self, role: str) -> bool:
        """API-key role check (ui / jury / admin)."""
        rank = ROLE_RANK.get(self.role)
        if rank is None:  # user roles: only admins act as API admins
            rank = 2 if self.role == "admin" else 0
        return rank >= ROLE_RANK[role]

    @property
    def user_rank(self) -> int:
        return USER_RANK.get(self.role, 0)

    def allows_user(self, role: str) -> bool:
        return self.user_rank >= USER_RANK[role]

    def can_see_camera(self, cam_id: str) -> bool:
        return self.camera_ids is None or cam_id in self.camera_ids

    def public(self) -> dict:
        return {"name": self.display_name or self.name, "login": self.name, "role": self.role,
                "user_id": self.user_id, "camera_ids": self.camera_ids, "kind": self.kind}


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
                return Principal(p.role, p.name, p.key_prefix)
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
        return self.db.all("SELECT id, prefix, role, name, disabled, created_at, last_used_at FROM api_keys ORDER BY id")

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


# ----------------------------------------------------------------------------- resolution

def _user_principal(u: dict) -> Principal:
    return Principal(u["role"], u["login"], user_id=u["id"], camera_ids=u.get("camera_ids"), kind="user",
                     display_name=u["name"])


def _extract(x_api_key: str | None, authorization: str | None, key_q: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return key_q


def resolve_principal(st, cookies: dict, key: str | None, allow_open: bool = True) -> Principal | None:
    """An explicit API key first (a script is a script even from a signed-in browser), then the session cookie,
    then (UI only) the open-UI fallback for AUTH_REQUIRED=0."""
    p = st.keys.verify(key) if key else None
    if p is not None:
        if p.role == "admin":
            p.display_name = p.display_name or "API admin"
        return p
    user = st.users.resolve(cookies.get(SESSION_COOKIE))
    if user is not None:
        return _user_principal(user)
    if allow_open and not get_settings().auth_required:
        return Principal("admin", "dev", kind="anon", display_name="Developer")
    return None


def require_role(role: str):
    """API-key gate (jury API, admin API)."""
    def dep(request: Request,
            x_api_key: str | None = Header(default=None, alias="X-API-Key"),
            authorization: str | None = Header(default=None),
            key: str | None = Query(default=None)) -> Principal:
        st = request.app.state.st
        p = resolve_principal(st, request.cookies, _extract(x_api_key, authorization, key), allow_open=False)
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
    """UI API: a signed-in user, an API key, or (AUTH_REQUIRED=0) anyone as admin."""
    st = request.app.state.st
    p = resolve_principal(st, request.cookies, _extract(x_api_key, authorization, key))
    if p is None:
        raise HTTPException(status_code=401, detail="Требуется вход", headers={"X-Auth": "login"})
    request.state.principal = p
    return p


def require_user(role: str):
    """UI API gate by user role: operator < supervisor < admin. Keys with the admin role pass as admin."""
    def dep(request: Request, p: Principal = Depends(ui_access)) -> Principal:
        if not p.allows_user(role):
            raise HTTPException(status_code=403, detail="Недостаточно прав для этой операции")
        return p
    return dep


def ws_principal(ws: WebSocket) -> Principal | None:
    st = ws.app.state.st
    key = ws.query_params.get("key") or ws.headers.get("x-api-key")
    return resolve_principal(st, ws.cookies, key)


def rate_limit_subject(request: Request) -> str:
    p = getattr(request.state, "principal", None)
    if p is not None and p.kind == "user":
        return f"user:{p.name}"
    if p is not None and p.key_prefix:
        return f"key:{p.name}:{p.key_prefix}"
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"
