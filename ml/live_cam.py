from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import REPO_DIR
from .detector import get_detector
from .live import LIVE_VLM_SEC, LiveRules
from .video import resize_max_side

PANEL_W = 430
COLORS = {"person": (80, 200, 80), "laptop": (230, 180, 60), "phone": (60, 60, 240), "drink": (60, 160, 240),
          "food": (60, 160, 240), "bag": (200, 80, 200)}
PERSON = {"sit": "сидит", "stand": "стоит", "none": "нет", "?": "?"}
SCREEN = {"app": "открыта программа", "lock": "экран блокировки", "dark": "тёмный", "closed": "закрыт", "?": "не видно"}
ACTION = {"drink": "пьёт / ест", "phone": "телефон в руке", "other": "работает", "none": "-"}


def _font(size: int):
    for p in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


F_TITLE, F_TEXT, F_SMALL = _font(19), _font(16), _font(14)


def _wrap(text: str, width: int = 48) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return lines + ([cur] if cur else [])


def render(frame: np.ndarray, dets, rules: LiveRules, log: list[dict], fps: float) -> np.ndarray:
    img = frame.copy()
    for d in dets:
        x1, y1, x2, y2 = (int(v) for v in d.box)
        c = COLORS.get(d.group, (180, 180, 180))
        cv2.rectangle(img, (x1, y1), (x2, y2), c, 2)
        cv2.putText(img, f"{d.label} {d.score:.2f}", (x1, max(14, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1, cv2.LINE_AA)
    desk = rules.desk
    if desk and desk.roi:
        x1, y1, x2, y2 = desk.roi
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 220, 255), 1)
        cv2.putText(img, "workplace", (x1 + 4, y1 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 255), 1, cv2.LINE_AA)

    h = max(img.shape[0], 560)
    canvas = np.full((h, img.shape[1] + PANEL_W, 3), 24, np.uint8)
    canvas[:img.shape[0], :img.shape[1]] = img
    pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    dr = ImageDraw.Draw(pil)
    x, y = img.shape[1] + 16, 12
    dr.text((x, y), "PhantomGuard · live", font=F_TITLE, fill=(255, 255, 255)); y += 28
    dr.text((x, y), f"{fps:.1f} кадр/с · модель каждые {LIVE_VLM_SEC:g} с", font=F_SMALL, fill=(160, 160, 160)); y += 26

    dr.text((x, y), "Рабочее место (модель):", font=F_TEXT, fill=(0, 220, 255)); y += 22
    st = desk.last_state() if desk else None
    if desk and not desk.enabled:
        dr.text((x, y), "VLM выключена - только детектор", font=F_SMALL, fill=(200, 200, 200)); y += 20
    elif not desk or not desk.roi:
        dr.text((x, y), "ищу рабочее место (ноутбук / сидящий человек)…", font=F_SMALL, fill=(200, 200, 200)); y += 20
    elif st is None:
        dr.text((x, y), "жду первый ответ модели…", font=F_SMALL, fill=(200, 200, 200)); y += 20
    else:
        age = time.time() - desk.t0 - st.t
        for k, v in [("кассир", PERSON.get(st.person, st.person)), ("клиент", PERSON.get(st.client, st.client)),
                     ("экран", SCREEN.get(st.screen, st.screen)), ("действие", ACTION.get(st.action, st.action)),
                     ("деньги на столе", "да" if st.cash else "нет"), ("сумка / пакет", "да" if st.bag else "нет"),
                     ("сейф", {True: "открыт", False: "закрыт", None: "не видно"}[st.safe_open])]:
            dr.text((x, y), f"{k}: {v}", font=F_SMALL, fill=(230, 230, 230)); y += 19
        dr.text((x, y), f"«{st.note}» · {age:.0f} с назад", font=F_SMALL, fill=(150, 150, 150)); y += 26

    active = rules.active()
    dr.text((x, y), "Активно: " + (", ".join(active) if active else "-"), font=F_TEXT,
            fill=(255, 120, 100) if any(c != "EMPTY" for c in active) else (120, 220, 120)); y += 30

    dr.text((x, y), "Тревоги:", font=F_TEXT, fill=(255, 255, 255)); y += 22
    for a in reversed(log[-7:]):
        when = time.strftime("%H:%M:%S", time.localtime(a["event_ts"]))
        col = (150, 150, 150) if a["severity"] == "info" else (255, 170, 80)
        dr.text((x, y), f"{when}  {a['code']}  {a['type']}"[:52], font=F_SMALL, fill=col); y += 18
        extra = f"подтверждено через {a['delay_sec']:.0f} с" + (f" · уверенность {a['confidence']:.2f}" if a.get("confidence") else "")
        dr.text((x + 14, y), extra, font=F_SMALL, fill=(140, 140, 140)); y += 22
        if y > h - 30:
            break
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cam", default="0", help="индекс камеры, файл или URL потока")
    ap.add_argument("--fps", type=float, default=4.0, help="кадров в секунду на детектор")
    ap.add_argument("--side", type=int, default=640, help="максимальная сторона кадра для анализа")
    ap.add_argument("--save-last", action="store_true", help="в конце файла сохранить окно в storage/live_cam/last.jpg")
    a = ap.parse_args()

    src = int(a.cam) if a.cam.isdigit() else a.cam
    cap = cv2.VideoCapture(src, cv2.CAP_DSHOW) if isinstance(src, int) and os.name == "nt" else cv2.VideoCapture(src)
    if not cap.isOpened():
        print(f"Не удалось открыть камеру {a.cam!r}")
        return 1
    import tkinter as tk
    from PIL import ImageTk

    is_file = isinstance(src, str) and os.path.exists(src)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    det, rules, log = get_detector(), LiveRules(), []
    shots = REPO_DIR / "storage" / "live_cam"
    s = {"next_t": 0.0, "last": time.time(), "fps": 0.0, "view": None}

    root = tk.Tk()
    root.title("PhantomGuard live - q / Esc: выход, s: снимок")
    label = tk.Label(root, bg="black")
    label.pack()

    def tick() -> None:
        ok, frame = cap.read()
        if not ok:
            if a.save_last and s["view"] is not None:
                shots.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(shots / "last.jpg"), s["view"])
                print(f"последний кадр окна: {shots / 'last.jpg'}", flush=True)
            root.destroy()
            return
        frame = resize_max_side(frame, a.side)
        now = time.time()
        if now >= s["next_t"]:
            s["next_t"] = now + 1 / a.fps
            dets = det([frame])[0]
            for al in rules.update(frame, dets):
                log.append(al)
                print(f"[{time.strftime('%H:%M:%S', time.localtime(al['event_ts']))}] {al['code']} {al['type']}: "
                      f"{al['message']}", flush=True)
            s["fps"], s["last"] = 0.8 * s["fps"] + 0.2 / max(1e-3, now - s["last"]), now
            s["view"] = render(frame, dets, rules, log, s["fps"])
            photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(s["view"], cv2.COLOR_BGR2RGB)))
            label.configure(image=photo)
            label.image = photo
        root.after(int(1000 / src_fps) if is_file else 5, tick)

    def snapshot(_=None) -> None:
        if s["view"] is not None:
            shots.mkdir(parents=True, exist_ok=True)
            p = shots / f"live_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
            cv2.imwrite(str(p), s["view"])
            print(f"снимок: {p}", flush=True)

    root.bind("<Escape>", lambda _: root.destroy())
    root.bind("q", lambda _: root.destroy())
    root.bind("s", snapshot)
    print("Камера открыта. q / Esc - выход, s - снимок окна.", flush=True)
    root.after(0, tick)
    root.mainloop()
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
