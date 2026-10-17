"""Users (operator / supervisor / admin), password hashing and cookie sessions."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time

from .config import get_settings
from .db import Database, loads

log = logging.getLogger("backend.users")

USER_ROLES = ("operator", "supervisor", "admin")
USER_RANK = {"operator": 1, "supervisor": 2, "admin": 3}
SESSION_COOKIE = "cg_session"
_PBKDF_ROUNDS = 120_000


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), _PBKDF_ROUNDS)
    return f"pbkdf2${salt}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _algo, salt, _digest = stored.split("$", 2)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def _public(row: dict) -> dict:
    return {"id": row["id"], "login": row["login"], "name": row["name"], "role": row["role"],
            "active": bool(row["active"]), "camera_ids": loads(row.get("camera_ids")),
            "created_at": row["created_at"], "last_login_at": row.get("last_login_at")}


class UserStore:
    def __init__(self, db: Database):
        self.db = db
        self.session_ttl = get_settings().session_ttl_sec
        self.seed()

    # ------------------------------------------------------------------ seed
    def seed(self) -> None:
        """First start: create the users listed in SEED_USERS (login:password:role:name;...)."""
        if self.db.one("SELECT 1 AS x FROM users LIMIT 1"):
            return
        spec = get_settings().seed_users
        n = 0
        for item in spec.split(";"):
            parts = [p.strip() for p in item.split(":")]
            if len(parts) < 3 or not parts[0] or not parts[1]:
                continue
            login, password, role = parts[0], parts[1], parts[2]
            name = parts[3] if len(parts) > 3 and parts[3] else login
            if role not in USER_ROLES:
                log.warning("SEED_USERS: unknown role %r for %s, skipped", role, login)
                continue
            self.create(login, password, role, name, actor="seed")
            n += 1
        if n:
            log.info("seeded %d user(s) from SEED_USERS", n)

    # ------------------------------------------------------------------ crud
    def create(self, login: str, password: str, role: str, name: str, actor: str | None = None,
               camera_ids: list[str] | None = None) -> dict:
        if role not in USER_ROLES:
            raise ValueError(f"unknown role {role!r}")
        uid = self.db.insert("users", {"login": login.strip().lower(), "name": name.strip() or login, "role": role,
                                       "password_hash": hash_password(password), "active": 1,
                                       "camera_ids": camera_ids, "created_at": time.time()})
        self.db.audit("user.create", actor, str(uid), {"login": login, "role": role})
        return self.get(uid)  # type: ignore[return-value]

    def get(self, uid: int) -> dict | None:
        r = self.db.one("SELECT * FROM users WHERE id=?", (uid,))
        return _public(r) if r else None

    def by_login(self, login: str) -> dict | None:
        return self.db.one("SELECT * FROM users WHERE login=?", (login.strip().lower(),))

    def list(self) -> list[dict]:
        return [_public(r) for r in self.db.all("SELECT * FROM users ORDER BY role, login")]

    def update(self, uid: int, actor: str | None = None, **fields) -> dict | None:
        allowed: dict = {}
        if "name" in fields and fields["name"] is not None:
            allowed["name"] = fields["name"].strip()
        if "role" in fields and fields["role"] is not None:
            if fields["role"] not in USER_ROLES:
                raise ValueError(f"unknown role {fields['role']!r}")
            allowed["role"] = fields["role"]
        if "active" in fields and fields["active"] is not None:
            allowed["active"] = int(bool(fields["active"]))
        if "password" in fields and fields["password"]:
            allowed["password_hash"] = hash_password(fields["password"])
        if "camera_ids" in fields:
            allowed["camera_ids"] = fields["camera_ids"]
        if not allowed:
            return self.get(uid)
        self.db.update("users", "id", uid, allowed)
        if not allowed.get("active", 1):
            self.db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        self.db.audit("user.update", actor, str(uid), {k: ("***" if k == "password_hash" else v) for k, v in allowed.items()})
        return self.get(uid)

    def count_active_admins(self) -> int:
        r = self.db.one("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND active=1")
        return int((r or {}).get("n") or 0)

    # ------------------------------------------------------------------ sessions
    @staticmethod
    def _h(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def login(self, login: str, password: str, ip: str | None = None, ua: str | None = None) -> tuple[str, dict] | None:
        row = self.by_login(login)
        if row is None or not row["active"] or not check_password(password, row["password_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        now = time.time()
        self.db.insert("sessions", {"token_hash": self._h(token), "user_id": row["id"], "created_at": now,
                                    "expires_at": now + self.session_ttl, "ip": ip, "user_agent": (ua or "")[:200]})
        self.db.update("users", "id", row["id"], {"last_login_at": now})
        self.db.audit("user.login", row["login"], str(row["id"]), {"ip": ip})
        return token, _public(row)

    def logout(self, token: str | None) -> None:
        if token:
            self.db.execute("DELETE FROM sessions WHERE token_hash=?", (self._h(token),))

    def resolve(self, token: str | None) -> dict | None:
        if not token:
            return None
        now = time.time()
        s = self.db.one("SELECT * FROM sessions WHERE token_hash=? AND expires_at > ?", (self._h(token), now))
        if s is None:
            return None
        row = self.db.one("SELECT * FROM users WHERE id=? AND active=1", (s["user_id"],))
        if row is None:
            return None
        if s["expires_at"] - now < self.session_ttl / 2:  # sliding expiry
            self.db.update("sessions", "token_hash", s["token_hash"], {"expires_at": now + self.session_ttl})
        return _public(row)

    def purge_sessions(self) -> int:
        return self.db.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
