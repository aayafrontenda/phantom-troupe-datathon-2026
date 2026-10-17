"""Translations for server-rendered pages (the printable report). UI strings live in frontend/src/i18n/strings.ts;
violation types and regulations in backend/i18n-kb.json (shared with the UI via /ui/api/i18n/kb)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

LANGS = ("ru", "kk", "en")
DEFAULT_LANG = "ru"
KB_FILE = Path(__file__).resolve().parents[1] / "i18n-kb.json"

REPORT = {
    "en": {
        "title": "Check report", "bar": "Check report - print it or save as PDF", "print": "Print / Save PDF", "back": "Back to the check",
        "h1": "Cash-desk video check", "generated": "Report generated", "check_id": "Check ID",
        "v_bad": "Signs of possible violations detected", "v_ok": "No violation detected",
        "v_bad_sub": "Findings: {n} · reviewed {r} of {n}", "v_ok_sub": "No visually observable sign of a cash-handling violation",
        "partial": "Partial result: the analysis reached its time limit before checking the whole recording.",
        "recording": "Recording", "file": "File", "duration": "Duration", "uploaded": "Uploaded", "analysis": "Analysis time", "sec": "s",
        "sha": "Video fingerprint (SHA-256)", "summary": "Summary", "time": "Time", "possible": "Possible violation", "decision": "Reviewer decision",
        "confirmed": "Confirmed", "rejected": "Not a violation", "none": "Not reviewed",
        "confirmed_long": "Confirmed as a violation", "none_long": "Not reviewed yet",
        "findings": "Findings", "frame_at": "Frame at", "seen": "What is seen and why it may be a violation",
        "why": "Why it may be a violation", "model_note": "Model’s note (in Russian)", "regulation": "Regulation",
        "quote_note": "quote from the Russian text", "confidence": "model confidence {p}%",
        "sign_name": "Reviewed by (name)", "sign_pos": "Position", "sign_date": "Date and signature",
        "foot": "This report is a hint for human review, not a final legal or disciplinary conclusion. The analysis covers only what is "
                "visible on the video; transaction records, reconciliations, amounts and identities are not established from video. "
                "All models run locally on the service; the video was not sent to external services.",
        "op_desc": "Operator’s wording", "ai_desc": "AI description", "decided_by": "Decided by", "comment": "Comment",
        "verification": "Supervisor verification", "v_agree": "Verified - agrees with the operator", "v_disagree": "Verified - disagrees with the operator",
        "v_none": "Not verified", "verified_by": "Verified by", "source_camera": "Camera", "footer_brand": "ForteBank · PhantomGuard",
        "hash": "Result hash {h} · service {v}.",
    },
    "ru": {
        "title": "Отчёт о проверке", "bar": "Отчёт о проверке - распечатайте или сохраните в PDF", "print": "Печать / PDF", "back": "Вернуться к проверке",
        "h1": "Проверка видео с кассы", "generated": "Отчёт сформирован", "check_id": "ID проверки",
        "v_bad": "Обнаружены признаки возможных нарушений", "v_ok": "Нарушение не обнаружено",
        "v_bad_sub": "Находок: {n} · решено {r} из {n}", "v_ok_sub": "Визуальных признаков нарушения работы с наличными не обнаружено",
        "partial": "Частичный результат: анализ упёрся в лимит времени и проверил не всю запись.",
        "recording": "Запись", "file": "Файл", "duration": "Длительность", "uploaded": "Загружено", "analysis": "Время анализа", "sec": "с",
        "sha": "Отпечаток видео (SHA-256)", "summary": "Сводка", "time": "Время", "possible": "Возможное нарушение", "decision": "Решение проверяющего",
        "confirmed": "Подтверждено", "rejected": "Не нарушение", "none": "Не рассмотрено",
        "confirmed_long": "Подтверждено как нарушение", "none_long": "Ещё не рассмотрено",
        "findings": "Находки", "frame_at": "Кадр", "seen": "Что видно и почему это может быть нарушением",
        "why": "Почему это может быть нарушением", "model_note": "Комментарий модели", "regulation": "Норма",
        "quote_note": "", "confidence": "уверенность модели {p}%",
        "sign_name": "Проверил (ФИО)", "sign_pos": "Должность", "sign_date": "Дата и подпись",
        "foot": "Отчёт - подсказка для проверяющего, а не окончательное юридическое или дисциплинарное заключение. Анализ охватывает "
                "только то, что видно на видео; проводки, сверки, суммы и личности по видео не устанавливаются. "
                "Все модели работают локально на сервисе; видео не передавалось во внешние сервисы.",
        "op_desc": "Формулировка оператора", "ai_desc": "Описание ИИ", "decided_by": "Решение принял", "comment": "Комментарий",
        "verification": "Проверка супервайзера", "v_agree": "Проверено - согласен с оператором", "v_disagree": "Проверено - не согласен с оператором",
        "v_none": "Не проверено", "verified_by": "Проверил", "source_camera": "Камера", "footer_brand": "ForteBank · PhantomGuard",
        "hash": "Хэш результата {h} · сервис {v}.",
    },
    "kk": {
        "title": "Тексеру есебі", "bar": "Тексеру есебі - басып шығарыңыз немесе PDF ретінде сақтаңыз", "print": "Басып шығару / PDF", "back": "Тексеруге оралу",
        "h1": "Касса бейнежазбасын тексеру", "generated": "Есеп жасалған уақыт", "check_id": "Тексеру ID",
        "v_bad": "Ықтимал бұзушылық белгілері анықталды", "v_ok": "Бұзушылық анықталмады",
        "v_bad_sub": "Табылғандар: {n} · {n} ішінен {r} шешілді", "v_ok_sub": "Қолма-қол ақшамен жұмыс бұзушылығының көзге көрінетін белгілері анықталмады",
        "partial": "Ішінара нәтиже: талдау уақыт шегіне жетіп, жазбаның бәрін тексермеді.",
        "recording": "Жазба", "file": "Файл", "duration": "Ұзақтығы", "uploaded": "Жүктелді", "analysis": "Талдау уақыты", "sec": "с",
        "sha": "Бейненің цифрлық ізі (SHA-256)", "summary": "Қорытынды", "time": "Уақыт", "possible": "Ықтимал бұзушылық", "decision": "Тексерушінің шешімі",
        "confirmed": "Расталды", "rejected": "Бұзушылық емес", "none": "Қаралмаған",
        "confirmed_long": "Бұзушылық ретінде расталды", "none_long": "Әлі қаралмаған",
        "findings": "Табылғандар", "frame_at": "Кадр", "seen": "Не көрінеді және неліктен бұл бұзушылық болуы мүмкін",
        "why": "Неліктен бұл бұзушылық болуы мүмкін", "model_note": "Модель жазбасы (орыс тілінде)", "regulation": "Норма",
        "quote_note": "орыс тіліндегі мәтіннен үзінді", "confidence": "модель сенімділігі {p}%",
        "sign_name": "Тексерген (аты-жөні)", "sign_pos": "Лауазымы", "sign_date": "Күні және қолы",
        "foot": "Бұл есеп - тексерушіге арналған көмекші құрал, түпкілікті заңдық немесе тәртіптік қорытынды емес. Талдау тек бейнеде "
                "көрінетін нәрсені қамтиды; өткізбелер, салыстырулар, сомалар мен тұлғалар бейне арқылы анықталмайды. "
                "Барлық модельдер сервисте жергілікті жұмыс істейді; бейне сыртқы сервистерге жіберілмеді.",
        "op_desc": "Оператордың тұжырымы", "ai_desc": "ЖИ сипаттамасы", "decided_by": "Шешім қабылдаған", "comment": "Пікір",
        "verification": "Супервайзер тексеруі", "v_agree": "Тексерілді - оператормен келіседі", "v_disagree": "Тексерілді - оператормен келіспейді",
        "v_none": "Тексерілмеген", "verified_by": "Тексерген", "source_camera": "Камера", "footer_brand": "ForteBank · PhantomGuard",
        "hash": "Нәтиже хэші {h} · сервис {v}.",
    },
}

_OBS_SPLIT = re.compile(r"\s*Это может указывать на нарушение:\s*")


def pick_lang(lang: str | None, accept_language: str | None = None) -> str:
    if lang in LANGS:
        return lang
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip()[:2].lower()
        if code in LANGS:
            return code
    return DEFAULT_LANG


@lru_cache(maxsize=1)
def kb() -> dict:
    try:
        return json.loads(KB_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"types": {}, "sources": {}}


def short_desc(d) -> str:
    """Description without the trailing norm reference (the regulation is shown separately)."""
    d = re.split(r"\s*Основание:", str(d or ""))[0]
    return re.sub(r"\s*Прямой публичной нормы не установлено\.?$", "", d).strip()


class Translator:
    def __init__(self, lang: str):
        self.lang = lang if lang in LANGS else DEFAULT_LANG
        self.s = REPORT[self.lang]

    def __call__(self, key: str, **kw) -> str:
        s = self.s.get(key, REPORT["en"].get(key, key))
        return s.format(**kw) if kw else s

    def _type(self, code: str | None) -> dict:
        return (kb()["types"].get(code or "") or {}).get(self.lang) or {}

    def type_name(self, v: dict) -> str:
        return (self.lang != "ru" and self._type(v.get("type_code")).get("name")) or v.get("type") or ""

    def caveat(self, v: dict) -> str | None:
        rule = v.get("rule") or {}
        return (self.lang != "ru" and self._type(v.get("type_code")).get("caveat")) or rule.get("caveat")

    def description(self, v: dict) -> dict:
        """{'why': str|None, 'observed': str|None, 'full': str} - in ru only 'full' is used."""
        full = short_desc(v.get("description"))
        why = self._type(v.get("type_code")).get("why") if self.lang != "ru" else None
        parts = _OBS_SPLIT.split(full)
        observed = parts[0].rstrip(".") if len(parts) > 1 else None
        return {"full": full, "why": why, "observed": observed}

    def doc(self, ref: dict) -> str:
        if self.lang == "ru":
            return ref.get("document", "")
        url = ref.get("url") or ""
        for src in kb()["sources"].values():
            m = src.get("match", "")
            if (url and m and m in url) or (not url and m == ""):
                return src.get(self.lang) or ref.get("document", "")
        return ref.get("document", "")

    def point(self, p: str | None) -> str:
        p = p or ""
        if not p or self.lang == "ru":
            return p
        if self.lang == "en":
            return re.sub(r"п\.\s*", "para. ", re.sub(r"пп\.\s*", "subpara. ", re.sub(r"ст\.\s*", "Art. ", p)))
        p = re.sub(r"ст\.\s*(\S+)", r"\1-бап", p)
        p = re.sub(r"пп\.\s*(\S+)", r"\1-тармақша", p)
        return re.sub(r"п\.\s*(\S+)", r"\1-тармақ", p)

    def url(self, u: str | None) -> str:
        u = u or ""
        return u.replace("/rus/docs/", "/kaz/docs/") if self.lang == "kk" else u
