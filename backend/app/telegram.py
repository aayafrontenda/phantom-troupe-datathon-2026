from __future__ import annotations

import base64
import html
import json
import logging
import secrets
import threading
import time
from typing import Any

import httpx

from .config import Settings

log = logging.getLogger("backend.telegram")

LINK_TTL_SEC = 15 * 60
LANGS = ("ru", "kk", "en")
SEV_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪", "info": "⚪"}

T: dict[str, dict[str, str]] = {
    "ru": {
        "found": "Найдено возможное нарушение", "video": "видео {name}", "conf": "Уверенность ИИ: {p}%",
        "repeats": "Повторов: {n}", "decide": "Решение - на сайте.", "btn.open": "Открыть в PhantomGuard",
        "reject.head": "⚠️ Оператор отклонил находку ИИ", "reject.op": "Оператор: {who}", "reject.ai": "ИИ: {t}",
        "reject.text": "Формулировка оператора: {t}", "reject.comment": "Комментарий: {t}", "reject.q": "Проверьте решение на сайте.",
        "welcome": "Готово, {name}! Telegram привязан к PhantomGuard - {role}.\n\n{what}\n\n"
                   "/pending - что ждёт вас на сайте\n/status - сводка\n/lang - язык\n/stop - отключить",
        "what.operator": "Сюда приходят возможные нарушения с ваших камер и по вашим проверкам видео. Решение принимается на сайте.",
        "what.supervisor": "Сюда приходят находки ИИ, которые отклонил оператор. Проверка - на сайте, в разделе «Контроль».",
        "what.admin": "Администраторам уведомления не приходят.",
        "role.operator": "оператор", "role.supervisor": "супервайзер", "role.admin": "администратор",
        "hint": "Это бот PhantomGuard. Чтобы получать уведомления, откройте PhantomGuard → меню профиля → «Telegram» → «Подключить».",
        "bad_code": "Ссылка устарела или уже использована. Получите новую в PhantomGuard → «Telegram».",
        "stopped": "Telegram отключён от PhantomGuard. Подключить снова - в профиле PhantomGuard.",
        "lang.ask": "Выберите язык", "lang.set": "Язык: русский",
        "pending.none": "Нет находок, ожидающих решения.", "pending.head": "Ждут решения на сайте: {n}. Последние:",
        "verify.none": "Нет отклонённых находок без проверки.", "verify.head": "Отклонено операторами и не проверено: {n}. Последние:",
        "status.operator": "Ждут вашего решения: {pending}\nРешено вами за сутки: {today}",
        "status.supervisor": "Отклонено операторами, не проверено: {rej}\nЖдут проверки всего: {tov}",
        "status.admin": "Открытых событий: {open}",
    },
    "kk": {
        "found": "Ықтимал бұзушылық табылды", "video": "бейне {name}", "conf": "ЖИ сенімділігі: {p}%",
        "repeats": "Қайталау: {n}", "decide": "Шешім - сайтта.", "btn.open": "PhantomGuard-та ашу",
        "reject.head": "⚠️ Оператор ЖИ табылымын қабылдамады", "reject.op": "Оператор: {who}", "reject.ai": "ЖИ: {t}",
        "reject.text": "Оператор тұжырымы: {t}", "reject.comment": "Пікір: {t}", "reject.q": "Шешімді сайтта тексеріңіз.",
        "welcome": "Дайын, {name}! Telegram PhantomGuard-қа байланыстырылды - {role}.\n\n{what}\n\n"
                   "/pending - сайтта сізді не күтіп тұр\n/status - жиынтық\n/lang - тіл\n/stop - ажырату",
        "what.operator": "Мұнда сіздің камераларыңыздан және бейне тексерулеріңізден ықтимал бұзушылықтар келеді. Шешім сайтта қабылданады.",
        "what.supervisor": "Мұнда оператор қабылдамаған ЖИ табылымдары келеді. Тексеру - сайтта, «Бақылау-тексеру» бөлімінде.",
        "what.admin": "Әкімшілерге хабарлама келмейді.",
        "role.operator": "оператор", "role.supervisor": "супервайзер", "role.admin": "әкімші",
        "hint": "Бұл - PhantomGuard боты. Хабарламаларды алу үшін PhantomGuard → профиль мәзірі → «Telegram» → «Қосу» ашыңыз.",
        "bad_code": "Сілтеменің мерзімі өткен немесе ол қолданылған. PhantomGuard → «Telegram» ішінен жаңасын алыңыз.",
        "stopped": "Telegram PhantomGuard-тан ажыратылды. Қайта қосу - PhantomGuard профилінде.",
        "lang.ask": "Тілді таңдаңыз", "lang.set": "Тіл: қазақша",
        "pending.none": "Шешім күтетін табылымдар жоқ.", "pending.head": "Сайтта шешім күтуде: {n}. Соңғылары:",
        "verify.none": "Тексерілмеген қабылданбаған табылымдар жоқ.", "verify.head": "Операторлар қабылдамаған, тексерілмеген: {n}. Соңғылары:",
        "status.operator": "Сіздің шешіміңізді күтуде: {pending}\nТәулік ішінде шешкеніңіз: {today}",
        "status.supervisor": "Операторлар қабылдамаған, тексерілмеген: {rej}\nБарлығы тексеруді күтуде: {tov}",
        "status.admin": "Ашық оқиғалар: {open}",
    },
    "en": {
        "found": "Possible violation found", "video": "video {name}", "conf": "AI confidence: {p}%",
        "repeats": "Repeats: {n}", "decide": "Decide on the site.", "btn.open": "Open in PhantomGuard",
        "reject.head": "⚠️ An operator rejected an AI finding", "reject.op": "Operator: {who}", "reject.ai": "AI: {t}",
        "reject.text": "Operator's wording: {t}", "reject.comment": "Comment: {t}", "reject.q": "Check the decision on the site.",
        "welcome": "Done, {name}! Telegram is linked to PhantomGuard - {role}.\n\n{what}\n\n"
                   "/pending - what is waiting for you on the site\n/status - summary\n/lang - language\n/stop - disconnect",
        "what.operator": "You will get possible violations from your cameras and your video checks. Decisions are made on the site.",
        "what.supervisor": "You will get AI findings an operator rejected. Verification is on the site, in “Control”.",
        "what.admin": "Administrators get no notifications.",
        "role.operator": "operator", "role.supervisor": "supervisor", "role.admin": "administrator",
        "hint": "This is the PhantomGuard bot. To get notifications, open PhantomGuard → profile menu → “Telegram” → “Connect”.",
        "bad_code": "The link has expired or was already used. Get a new one in PhantomGuard → “Telegram”.",
        "stopped": "Telegram is disconnected from PhantomGuard. Connect again from your PhantomGuard profile.",
        "lang.ask": "Choose a language", "lang.set": "Language: English",
        "pending.none": "No findings awaiting a decision.", "pending.head": "Awaiting your decision on the site: {n}. Latest:",
        "verify.none": "No rejected findings left to verify.", "verify.head": "Rejected by operators, not verified: {n}. Latest:",
        "status.operator": "Awaiting your decision: {pending}\nDecided by you in 24 h: {today}",
        "status.supervisor": "Rejected by operators, not verified: {rej}\nAwaiting verification in total: {tov}",
        "status.admin": "Open events: {open}",
    },
}


def tr(lang: str | None, key: str, **kw: Any) -> str:
    s = T.get(lang or "ru", T["ru"]).get(key) or T["ru"].get(key, key)
    return s.format(**kw) if kw else s


def _lang_of(code: str | None) -> str:
    code = (code or "").lower()[:2]
    return code if code in ("kk", "en") else "ru"


def _tc(t: Any) -> str:
    return f"{int(t // 60):02d}:{t % 60:04.1f}" if isinstance(t, (int, float)) else ""


def _e(s: Any) -> str:
    return html.escape(str(s or ""), quote=False)


class TelegramBot:
    def __init__(self, settings: Settings):
        self.s = settings
        self.token = settings.telegram_bot_token
        self.api = f"https://api.telegram.org/bot{self.token}"
        self.groups = {"operator": settings.telegram_chat_operator, "supervisor": settings.telegram_chat_supervisor}
        self.st = None
        self.username: str | None = None
        self._getme_failed_at = 0.0
        self.transport: httpx.BaseTransport | None = None
        self._codes: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def attach(self, state) -> None:
        self.st = state

    def start(self) -> None:
        if not self.enabled or not self.s.telegram_poll:
            return
        self._thread = threading.Thread(target=self._poll, name="telegram-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(3)

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(timeout=timeout, transport=self.transport)

    def call(self, method: str, timeout: float = 20, files: dict | None = None, **payload) -> dict:
        with self._client(timeout) as c:
            if files:
                data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in payload.items()}
                r = c.post(f"{self.api}/{method}", data=data, files=files)
            else:
                r = c.post(f"{self.api}/{method}", json=payload)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 400 or not body.get("ok", False):
            raise RuntimeError(f"telegram {method}: {r.status_code} {str(body.get('description') or r.text)[:200]}")
        return body.get("result") or {}

    def bot_username(self) -> str | None:
        if self.username is None and self.enabled and time.time() - self._getme_failed_at > 60:
            try:
                self.username = self.call("getMe", timeout=8).get("username")
            except Exception as e:
                self._getme_failed_at = time.time()
                log.warning("telegram getMe failed: %s", e)
        return self.username

    def link_code(self, user_id: int) -> str:
        code = secrets.token_urlsafe(12).replace("-", "a").replace("_", "b")
        now = time.time()
        with self._lock:
            self._codes = {k: v for k, v in self._codes.items() if v[1] > now}
            self._codes[code] = (user_id, now + LINK_TTL_SEC)
        return code

    def _take_code(self, code: str) -> int | None:
        with self._lock:
            v = self._codes.pop(code, None)
        return v[0] if v and v[1] > time.time() else None

    def unlink(self, user_id: int, actor: str | None = None) -> None:
        self.st.db.update("users", "id", user_id, {"tg_user_id": None, "tg_chat_id": None, "tg_username": None,
                                                   "tg_lang": None, "tg_linked_at": None})
        self.st.db.audit("telegram.unlink", actor, str(user_id))

    def _user_by_tg(self, tg_user_id: int | None) -> dict | None:
        if tg_user_id is None:
            return None
        return self.st.db.one("SELECT * FROM users WHERE tg_user_id=? AND active=1", (tg_user_id,))

    def _linked(self) -> list[dict]:
        from .db import loads
        rows = self.st.db.all("SELECT * FROM users WHERE active=1 AND tg_chat_id IS NOT NULL")
        for r in rows:
            r["camera_ids"] = loads(r.get("camera_ids"))
        return rows

    def has_targets(self, role: str) -> bool:
        if not self.enabled or self.st is None or role != "operator":
            return False
        return bool(self.groups.get(role)) or any(u["role"] == role for u in self._linked())

    def _recipients(self, role: str, camera_id: str | None = None, owner: str | None = None) -> list[tuple[int | str, str]]:
        out: dict[str, tuple[int | str, str]] = {}
        for u in self._linked():
            if u["role"] != role:
                continue
            if camera_id is None and owner is not None:
                ok = u["login"] == owner
            else:
                ok = camera_id is None or u["camera_ids"] is None or camera_id in u["camera_ids"]
            if ok:
                out[str(u["tg_chat_id"])] = (u["tg_chat_id"], u.get("tg_lang") or "ru")
        if self.groups.get(role):
            out.setdefault(str(self.groups[role]), (self.groups[role], "ru"))
        return list(out.values())

    def _open(self, lang: str, link: str | None) -> list[list[dict]]:
        base = (self.s.public_url or "").rstrip("/")
        if base.startswith("https://") and link:
            return [[{"text": tr(lang, "btn.open"), "url": base + link}]]
        return []

    def _send(self, chat: int | str, text: str, keyboard: list[list[dict]] | None = None,
              photo_b64: str | None = None) -> dict:
        markup = {"inline_keyboard": keyboard or []}
        if photo_b64 and self.s.telegram_photos:
            return self.call("sendPhoto", files={"photo": ("frame.jpg", base64.b64decode(photo_b64), "image/jpeg")},
                             chat_id=chat, caption=text[:1024], parse_mode="HTML", reply_markup=markup)
        return self.call("sendMessage", chat_id=chat, text=text[:4096], parse_mode="HTML", reply_markup=markup,
                         disable_web_page_preview=True)

    def _type_name(self, code: str, name: str | None, lang: str) -> str:
        if lang == "ru":
            return name or code
        from .i18n import Translator
        return Translator(lang).type_name({"type_code": code, "type": name})

    def alert_text(self, a: dict, lang: str, head: bool = True) -> str:
        code = a.get("type_code") or "T99"
        where = a.get("camera_name") or a.get("camera_id") or (tr(lang, "video", name=a["filename"]) if a.get("filename") else "")
        sev = a.get("severity") or "medium"
        lines = [f"{SEV_ICON.get(sev, '⚪')} <b>{_e(tr(lang, 'found'))}</b>" if head else "",
                 f"<b>{_e(code)} · {_e(self._type_name(code, a.get('type_name'), lang))}</b>"]
        if where:
            lines.append("📍 " + _e(where) + (f" · {_tc(a.get('t_sec'))}" if a.get("t_sec") is not None else ""))
        if a.get("message"):
            lines.append(_e(str(a["message"])[:500]))
        if isinstance(a.get("confidence"), (int, float)):
            lines.append("🤖 " + _e(tr(lang, "conf", p=round(a["confidence"] * 100))))
        if (a.get("count") or 1) > 1:
            lines.append("🔁 " + _e(tr(lang, "repeats", n=a["count"])))
        if head:
            lines.append(f"<i>{_e(tr(lang, 'decide'))}</i>")
        return "\n".join(x for x in lines if x)

    def send_alert(self, alert: dict, role: str, level: int) -> int:
        if self.st is None or role != "operator":
            return 0
        owner = None
        if alert.get("job_id") and not alert.get("camera_id"):
            job = self.st.db.one("SELECT created_by, source FROM jobs WHERE job_id=?", (alert["job_id"],)) or {}
            if job.get("source") == "jury":
                return 0
            owner = job.get("created_by") or ""
        link = f"/findings/{alert['finding_id']}" if alert.get("finding_id") else alert.get("link")
        sent, errors = 0, []
        for chat, lang in self._recipients("operator", alert.get("camera_id"), owner):
            try:
                self._send(chat, self.alert_text(alert, lang), self._open(lang, link), alert.get("evidence_b64"))
                sent += 1
            except Exception as e:
                errors.append(str(e))
        if errors and not sent:
            raise RuntimeError("; ".join(errors)[:300])
        return sent

    def on_finding_decided(self, f: dict, actor) -> None:
        if not self.enabled or self.st is None or f.get("decision") != "reject" or actor.role != "operator":
            return
        if f.get("job_id"):
            job = self.st.db.one("SELECT source FROM jobs WHERE job_id=?", (f["job_id"],)) or {}
            if job.get("source") == "jury":
                return
        threading.Thread(target=self._notify_reject, args=(f["id"],), name="telegram-reject", daemon=True).start()

    def _notify_reject(self, fid: int) -> None:
        f = self.st.findings.get(fid, with_frames=True)
        if not f or f.get("decision") != "reject":
            return
        photo = (f.get("frames") or [{}])[0].get("image_base64")
        for chat, lang in self._recipients("supervisor", f.get("camera_id")):
            try:
                self._send(chat, self.reject_text(f, lang), self._open(lang, f"/findings/{fid}"), photo)
            except Exception as e:
                log.warning("telegram reject notice to %s failed: %s", chat, e)

    def reject_text(self, f: dict, lang: str) -> str:
        code = f.get("type_code") or "T99"
        where = f.get("camera_name") or (tr(lang, "video", name=f.get("filename")) if f.get("filename") else f.get("job_id") or "")
        lines = [f"<b>{_e(tr(lang, 'reject.head'))}</b>", f"<b>{_e(code)} · {_e(self._type_name(code, f.get('type_name'), lang))}</b>",
                 "📍 " + _e(where) + (f" · {_tc(f.get('t_sec'))}" if f.get("t_sec") is not None else ""),
                 _e(tr(lang, "reject.op", who=f.get("decided_by_name") or f.get("decided_by")))]
        if f.get("description_ai"):
            lines.append(_e(tr(lang, "reject.ai", t=str(f["description_ai"])[:400])))
        if f.get("description_edit"):
            lines.append(_e(tr(lang, "reject.text", t=str(f["description_edit"])[:400])))
        if f.get("decision_comment"):
            lines.append(_e(tr(lang, "reject.comment", t=f["decision_comment"])))
        if isinstance(f.get("confidence"), (int, float)):
            lines.append("🤖 " + _e(tr(lang, "conf", p=round(f["confidence"] * 100))))
        lines.append(f"<i>{_e(tr(lang, 'reject.q'))}</i>")
        return "\n".join(lines)

    def _poll(self) -> None:
        self.bot_username()
        self._register_commands()
        offset = 0
        while not self._stop.is_set():
            try:
                with self._client(40) as c:
                    r = c.get(f"{self.api}/getUpdates", params={
                        "timeout": 25, "offset": offset, "allowed_updates": json.dumps(["message", "callback_query"])})
                if r.status_code == 409:
                    log.warning("telegram: another server polls this bot token (409); set TELEGRAM_POLL=0 on one of them")
                    self._stop.wait(30)
                    continue
                for upd in r.json().get("result", []):
                    offset = upd["update_id"] + 1
                    try:
                        self.handle_update(upd)
                    except Exception:
                        log.exception("telegram update %s failed", upd.get("update_id"))
            except Exception as e:
                log.warning("telegram poll error: %s", e)
                self._stop.wait(5)

    def _register_commands(self) -> None:
        names = {"ru": ("Что ждёт решения", "Сводка", "Язык", "Отключить"),
                 "kk": ("Шешім күтуде", "Жиынтық", "Тіл", "Ажырату"),
                 "en": ("Awaiting decision", "Summary", "Language", "Disconnect")}
        for lang, d in names.items():
            cmds = [{"command": c, "description": t} for c, t in zip(("pending", "status", "lang", "stop"), d)]
            try:
                self.call("setMyCommands", commands=cmds, **({} if lang == "ru" else {"language_code": lang}))
            except Exception as e:
                log.debug("setMyCommands %s failed: %s", lang, e)

    def handle_update(self, upd: dict) -> None:
        if upd.get("message"):
            self._on_message(upd["message"])
        elif upd.get("callback_query"):
            self._on_callback(upd["callback_query"])

    def _reply(self, chat: int, text: str, keyboard: list[list[dict]] | None = None) -> None:
        try:
            self._send(chat, _e(text), keyboard)
        except Exception as e:
            log.warning("telegram reply failed: %s", e)

    def _on_message(self, msg: dict) -> None:
        chat = msg.get("chat") or {}
        if chat.get("type") != "private":
            return
        frm = msg.get("from") or {}
        cmd, _, arg = (msg.get("text") or "").strip().partition(" ")
        cmd = cmd.split("@")[0].lower()
        arg = arg.strip()
        user = self._user_by_tg(frm.get("id"))
        lang = (user or {}).get("tg_lang") or _lang_of(frm.get("language_code"))
        if cmd == "/start" and arg:
            return self._link(chat["id"], frm, arg)
        if user is None:
            return self._reply(chat["id"], tr(lang, "hint"))
        if cmd == "/stop":
            self.unlink(user["id"], user["login"])
            return self._reply(chat["id"], tr(lang, "stopped"))
        if cmd == "/lang":
            if arg in LANGS:
                self.st.db.update("users", "id", user["id"], {"tg_lang": arg})
                return self._reply(chat["id"], tr(arg, "lang.set"))
            return self._reply(chat["id"], tr(lang, "lang.ask"),
                               [[{"text": "Русский", "callback_data": "l:ru"}, {"text": "Қазақша", "callback_data": "l:kk"},
                                 {"text": "English", "callback_data": "l:en"}]])
        if cmd == "/status":
            return self._reply(chat["id"], self._status(user, lang))
        if cmd == "/pending":
            return self._pending(user, chat["id"], lang)
        return self._reply(chat["id"], self._welcome(user))

    def _link(self, chat_id: int, frm: dict, code: str) -> None:
        uid = self._take_code(code)
        lang = _lang_of(frm.get("language_code"))
        if uid is None:
            return self._reply(chat_id, tr(lang, "bad_code"))
        with self.st.db.tx() as t:
            t.execute("UPDATE users SET tg_user_id=NULL, tg_chat_id=NULL, tg_username=NULL, tg_linked_at=NULL "
                      "WHERE tg_user_id=? AND id<>?", (frm.get("id"), uid))
            t.execute("UPDATE users SET tg_user_id=?, tg_chat_id=?, tg_username=?, tg_lang=?, tg_linked_at=? WHERE id=?",
                      (frm.get("id"), chat_id, frm.get("username"), lang, time.time(), uid))
        user = self._user_by_tg(frm.get("id"))
        self.st.db.audit("telegram.link", user["login"], str(uid), {"username": frm.get("username")})
        return self._reply(chat_id, self._welcome(user))

    def _on_callback(self, cq: dict) -> None:
        user = self._user_by_tg((cq.get("from") or {}).get("id"))
        _, _, lang = (cq.get("data") or "").partition("l:")
        if user is not None and lang in LANGS:
            self.st.db.update("users", "id", user["id"], {"tg_lang": lang})
        try:
            self.call("answerCallbackQuery", callback_query_id=cq["id"], text=tr(lang if lang in LANGS else "ru", "lang.set"))
        except Exception as e:
            log.debug("answerCallbackQuery failed: %s", e)

    def _welcome(self, user: dict) -> str:
        lang = user.get("tg_lang") or "ru"
        return tr(lang, "welcome", name=user["name"], role=tr(lang, "role." + user["role"]), what=tr(lang, "what." + user["role"]))

    @staticmethod
    def _camera_ids(user: dict) -> list[str] | None:
        from .db import loads
        return loads(user.get("camera_ids"))

    def _status(self, user: dict, lang: str) -> str:
        counts = self.st.findings.counts(self._camera_ids(user))
        if user["role"] == "operator":
            today = (self.st.db.one("SELECT COUNT(*) AS n FROM findings WHERE decided_by=? AND decided_at>?",
                                    (user["login"], time.time() - 86400)) or {}).get("n", 0)
            return tr(lang, "status.operator", pending=counts["pending"], today=today)
        if user["role"] == "supervisor":
            return tr(lang, "status.supervisor", rej=counts["rejected_unverified"], tov=counts["to_verify"])
        return tr(lang, "status.admin", open=self.st.alerts.summary().get("open", 0))

    def _pending(self, user: dict, chat: int, lang: str) -> None:
        cams = self._camera_ids(user)
        if user["role"] == "operator":
            data, empty, head = self.st.findings.list(decision="pending", camera_ids=cams, limit=5), "pending.none", "pending.head"
        else:
            data, empty, head = self.st.findings.list(decision="reject", verified=False, camera_ids=cams, limit=5), "verify.none", "verify.head"
        if not data["total"]:
            return self._reply(chat, tr(lang, empty))
        self._reply(chat, tr(lang, head, n=data["total"]))
        for f in data["findings"]:
            text = self.alert_text({**f, "message": f.get("description_edit") or f.get("description_ai"),
                                    "severity": self.st.alerts.severity_of(f.get("type_code"))}, lang, head=False)
            try:
                self._send(chat, text, self._open(lang, f"/findings/{f['id']}"))
            except Exception as e:
                log.warning("telegram pending failed: %s", e)
        return None
