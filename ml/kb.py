from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from .config import get_settings


@lru_cache(maxsize=4)
def load_kb(path: str | None = None) -> dict:
    p = Path(path) if path else get_settings().kb_path
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def type_codes() -> list[str]:
    return list(load_kb()["violations"].keys())


def rule_of(code: str) -> dict:
    return load_kb()["violations"][code]


def refs_struct(code: str) -> list[dict]:
    kb = load_kb()
    out = []
    for ref in rule_of(code).get("refs", []):
        src = kb["sources"][ref["src"]]
        out.append({
            "document": src["short"],
            "act": src["act"],
            "point": ref.get("point", ""),
            "quote": ref.get("quote"),
            "paraphrase": ref.get("paraphrase"),
            "url": src.get("url", ""),
        })
    return out


def refs_text(code: str) -> str:
    by_doc: dict[str, list[str]] = {}
    for r in refs_struct(code):
        by_doc.setdefault(r["document"], [])
        if r["point"]:
            by_doc[r["document"]].append(r["point"])
    parts = [f"{', '.join(points)} - {doc}" if points else doc for doc, points in by_doc.items()]
    return "; ".join(parts)


def checklist_text() -> str:
    lines = []
    for code, v in load_kb()["violations"].items():
        lines.append(f"{code} - {v['type_name']}. Признак на видео: {v['visual']}.")
    return "\n".join(lines)


def build_description(code: str, observed: str) -> str:
    v = rule_of(code)
    observed = (observed or "").strip().rstrip(".")
    why = v.get("why", "").strip().rstrip(".")
    text = f"{observed}. Это может указывать на нарушение: {why}." if observed else f"{why[:1].upper()}{why[1:]}."
    ref = refs_text(code)
    if ref:
        text += f" Основание: {ref}."
    if v.get("norm_kind") == "internal":
        text += " Прямой публичной нормы не установлено."
    elif v.get("norm_kind") == "indirect":
        caveat = (v.get("caveat") or "").strip().rstrip(".")
        text += f" Норма косвенная: {caveat[:1].lower()}{caveat[1:]}." if caveat else " Норма косвенная, прямой публичной нормы нет."
    return text
