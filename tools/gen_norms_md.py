"""Генерирует docs/norms.md из ml/rules_kb.yaml (для пакета сдачи, раздел 8 ТЗ).

    python tools/gen_norms_md.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.kb import load_kb  # noqa: E402

KIND = {"direct": "прямая норма", "indirect": "косвенная норма", "internal": "внутренний регламент"}


def main() -> None:
    kb = load_kb(str(ROOT / "ml" / "rules_kb.yaml"))
    src = kb["sources"]
    lines = [
        "# Нормативные источники и сопоставление с нарушениями",
        "",
        "Файл сгенерирован из `ml/rules_kb.yaml` (`python tools/gen_norms_md.py`). Правьте YAML, не этот файл.",
        "",
        "## Использованные источники",
        "",
    ]
    for key, s in src.items():
        if key == "INTERNAL":
            continue
        url = f" — [{s['url']}]({s['url']})" if s.get("url") else ""
        lines.append(f"- **{s['act']}.** {s['title']}{url}")
        if s.get("note"):
            lines.append(f"  - {s['note']}")
    lines += [
        "",
        "## Принцип сопоставления",
        "",
        "1. Модель фиксирует только видимые действия (кто, что делает, где, когда).",
        "2. Наблюдение относится к типу из закрытого списка T01–T15; у каждого типа заранее заданы визуальный признак и нормы.",
        "3. В ответ попадают только ссылки из этого списка; где прямой публичной нормы нет, это указано явно.",
        "4. Вывод формулируется как «признак возможного нарушения» — окончательное решение за проверяющим.",
        "",
        "## Типы нарушений",
        "",
        "| Код | Тип | Что видно на видео | Норма | Вид нормы |",
        "| --- | --- | --- | --- | --- |",
    ]
    for code, v in kb["violations"].items():
        by: dict[str, list[str]] = {}
        for r in v.get("refs", []):
            by.setdefault(src[r["src"]]["label"], [])
            if r.get("point"):
                by[src[r["src"]]["label"]].append(r["point"])
        refs = [f"{', '.join(p)} — {lbl}" if p else lbl for lbl, p in by.items()]
        lines.append(f"| {code} | {v['type_name']} | {v['visual']} | {'; '.join(refs)} | {KIND.get(v.get('norm_kind'), '')} |")
    lines += ["", "## Цитаты", ""]
    for code, v in kb["violations"].items():
        lines.append(f"**{code}. {v['type_name']}**")
        lines.append("")
        for r in v.get("refs", []):
            s = src[r["src"]]
            if r.get("quote"):
                lines.append(f"- {r.get('point', '')}, {s['act']}: «{r['quote']}»")
            elif r.get("paraphrase"):
                lines.append(f"- {r.get('point', '')} {s['short']}: {r['paraphrase']} (пересказ)")
        if v.get("caveat"):
            lines.append(f"- Оговорка: {v['caveat']}")
        lines.append("")
    out = ROOT / "docs" / "norms.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"записано: {out}")


if __name__ == "__main__":
    main()
