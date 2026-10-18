from __future__ import annotations

import json
import re

import httpx

from .config import get_settings
from .kb import checklist_text, type_codes
from .config import ML_DIR

PROMPT_TEMPLATE = (ML_DIR / "prompts" / "checklist_ru.txt").read_text(encoding="utf-8")


class VLMError(RuntimeError):
    pass


def build_prompt(frame_times: list[float], hints: list[str]) -> str:
    return PROMPT_TEMPLATE.format(
        n_frames=len(frame_times),
        frame_times=", ".join(f"{t:.1f}" for t in frame_times),
        hints="; ".join(hints) if hints else "нет",
        checklist=checklist_text(),
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise VLMError(f"VLM вернула не JSON: {text[:200]}")
        return json.loads(m.group(0))


class VLMClient:
    def __init__(self, timeout: float | None = None):
        s = get_settings()
        self.backend = s.vlm_backend
        self.url = s.vlm_url.rstrip("/")
        self.model = s.vlm_model
        self.timeout = timeout or s.vlm_timeout
        self.http = httpx.Client(timeout=self.timeout)

    @property
    def enabled(self) -> bool:
        return self.backend in ("ollama", "openai")

    def ping(self) -> bool:
        try:
            if self.backend == "ollama":
                return self.http.get(f"{self.url}/api/tags", timeout=3).status_code == 200
            if self.backend == "openai":
                return self.http.get(f"{self.url}/v1/models", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False
        return False

    def ask(self, prompt: str, images_b64: list[str]) -> str:
        if self.backend == "ollama":
            r = self.http.post(f"{self.url}/api/chat", json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt, "images": images_b64}],
                "stream": False,
                "think": False,
                "format": "json",
                "keep_alive": -1,
                "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 600},
            })
            r.raise_for_status()
            return r.json()["message"]["content"]
        if self.backend == "openai":
            content = [{"type": "text", "text": prompt}] + [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in images_b64
            ]
            r = self.http.post(f"{self.url}/v1/chat/completions", json={
                "model": self.model,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0,
                "max_tokens": 600,
            })
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        raise VLMError(f"VLM_BACKEND={self.backend} не поддерживается")

    def check_window(self, frame_times: list[float], images_b64: list[str], hints: list[str]) -> dict:
        raw = self.ask(build_prompt(frame_times, hints), images_b64)
        data = _extract_json(raw)
        valid = set(type_codes())
        findings = []
        for f in data.get("findings") or []:
            code = str(f.get("code", "")).strip().upper()
            if code not in valid:
                continue
            try:
                frame = int(f.get("frame", 1))
                conf = float(f.get("confidence", 0))
            except (TypeError, ValueError):
                continue
            frame = min(max(frame, 1), len(frame_times))
            findings.append({"code": code, "frame": frame, "confidence": conf,
                             "observed": str(f.get("observed", "")).strip()})
        return {"scene": str(data.get("scene", "")), "findings": findings, "raw": raw}
