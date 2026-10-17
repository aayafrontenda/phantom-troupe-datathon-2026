"""Sign-in for the web UI: cookie sessions for operators, supervisors and admins; user management for admins."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..auth import Principal, require_user, ui_access
from ..config import get_settings
from ..users import SESSION_COOKIE, USER_ROLES

router = APIRouter(prefix="/ui/api", tags=["auth"])


def _st(request: Request):
    return request.app.state.st


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    st = _st(request)
    if not st.limiter.allow(f"login:{request.client.host if request.client else 'x'}", cost=3):
        raise HTTPException(status_code=429, detail="Слишком много попыток входа")
    res = st.users.login(body.login, body.password, ip=request.client.host if request.client else None,
                         ua=request.headers.get("user-agent"))
    if res is None:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    token, user = res
    s = get_settings()
    response.set_cookie(SESSION_COOKIE, token, max_age=s.session_ttl_sec, httponly=True, samesite="lax",
                        secure=s.secure_cookies, path="/")
    return {"user": user}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    _st(request).users.logout(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request, p: Principal = Depends(ui_access)):
    st = _st(request)
    return {"user": p.public(), "analyzer": st.settings.analyzer, "version": st.settings.version,
            "features": {"clips": st.settings.make_clips, "telegram": bool(st.settings.telegram_bot_token),
                         "live_findings": st.settings.live_findings,
                         "retention_days": st.settings.video_retention_days}}


# ----------------------------------------------------------------------------- Telegram (own account)

def _me_user(request: Request, p: Principal) -> dict:
    if p.user_id is None:
        raise HTTPException(status_code=400, detail="Telegram is linked to a user account: sign in first")
    u = _st(request).users.get(p.user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return u


@router.get("/auth/telegram")
def telegram_status(request: Request, p: Principal = Depends(ui_access)):
    bot = _st(request).alerts.telegram
    u = _me_user(request, p) if p.user_id is not None else None
    return {"enabled": bot.enabled, "bot": bot.bot_username() if bot.enabled else None,
            "linked": bool(u and u.get("telegram")), "telegram": (u or {}).get("telegram"),
            "photos": _st(request).settings.telegram_photos}


@router.post("/auth/telegram/link")
def telegram_link(request: Request, p: Principal = Depends(ui_access)):
    bot = _st(request).alerts.telegram
    u = _me_user(request, p)
    if not bot.enabled:
        raise HTTPException(status_code=409, detail="Telegram bot is not configured (TELEGRAM_BOT_TOKEN)")
    name = bot.bot_username()
    if not name:
        raise HTTPException(status_code=503, detail="Telegram is unreachable from the server")
    code = bot.link_code(u["id"])
    return {"url": f"https://t.me/{name}?start={code}", "bot": name, "expires_in": 15 * 60}


@router.delete("/auth/telegram")
def telegram_unlink(request: Request, p: Principal = Depends(ui_access)):
    u = _me_user(request, p)
    _st(request).alerts.telegram.unlink(u["id"], p.name)
    return {"ok": True}


# ----------------------------------------------------------------------------- users (admin)

class UserIn(BaseModel):
    login: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=4, max_length=200)
    role: str = Field(pattern="^(operator|supervisor|admin)$")
    name: str = Field(min_length=1, max_length=100)
    camera_ids: list[str] | None = None


class UserPatch(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    role: str | None = Field(default=None, pattern="^(operator|supervisor|admin)$")
    active: bool | None = None
    password: str | None = Field(default=None, min_length=4, max_length=200)
    camera_ids: list[str] | None = None
    all_cameras: bool | None = None
    unlink_telegram: bool | None = None


@router.get("/users")
def users_list(request: Request, p: Principal = Depends(require_user("admin"))):
    return {"users": _st(request).users.list(), "roles": list(USER_ROLES)}


@router.post("/users", status_code=201)
def users_create(body: UserIn, request: Request, p: Principal = Depends(require_user("admin"))):
    st = _st(request)
    if st.users.by_login(body.login):
        raise HTTPException(status_code=409, detail="Пользователь с таким логином уже есть")
    return st.users.create(body.login, body.password, body.role, body.name, actor=p.name, camera_ids=body.camera_ids)


@router.patch("/users/{uid}")
def users_patch(uid: int, body: UserPatch, request: Request, p: Principal = Depends(require_user("admin"))):
    st = _st(request)
    u = st.users.get(uid)
    if u is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if u["role"] == "admin" and (body.active is False or (body.role and body.role != "admin")) \
            and st.users.count_active_admins() <= 1:
        raise HTTPException(status_code=409, detail="Нельзя убрать последнего администратора")
    fields = body.model_dump(exclude_none=True)
    if fields.pop("unlink_telegram", None):
        st.alerts.telegram.unlink(uid, p.name)
    if fields.pop("all_cameras", None):
        fields["camera_ids"] = None
    elif "camera_ids" not in body.model_fields_set:
        fields.pop("camera_ids", None)
    return st.users.update(uid, actor=p.name, **fields)
