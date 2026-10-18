from __future__ import annotations

import base64

VERDICTS = {"violation", "no_violation"}
STATUSES = {"processing", "done", "failed"}


def validate_job(resp: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(resp.get("job_id"), str):
        errs.append("job_id должен быть строкой")
    st = resp.get("status")
    if st not in STATUSES:
        errs.append(f"status={st!r} не из {sorted(STATUSES)}")
    if st == "done":
        errs += validate_result(resp)
    return errs


def validate_result(res: dict) -> list[str]:
    errs: list[str] = []
    v = res.get("verdict")
    if v not in VERDICTS:
        errs.append(f"verdict={v!r} не из {sorted(VERDICTS)}")
    viols = res.get("violations")
    if not isinstance(viols, list):
        return errs + ["violations должен быть списком"]
    if v == "no_violation" and viols:
        errs.append("verdict=no_violation, но violations не пуст")
    if v == "violation" and not viols:
        errs.append("verdict=violation, но violations пуст")
    for i, x in enumerate(viols):
        p = f"violations[{i}]"
        if not isinstance(x.get("type"), str) or not x.get("type"):
            errs.append(f"{p}.type - непустая строка")
        if not isinstance(x.get("timecode_sec"), (int, float)):
            errs.append(f"{p}.timecode_sec - число")
        if not isinstance(x.get("description"), str) or not x.get("description"):
            errs.append(f"{p}.description - непустая строка")
        fr = x.get("evidence_frames")
        if not isinstance(fr, list) or not (1 <= len(fr) <= 3):
            errs.append(f"{p}.evidence_frames - 1–3 кадра")
            continue
        for j, f in enumerate(fr):
            if not isinstance(f.get("timestamp_sec"), (int, float)):
                errs.append(f"{p}.evidence_frames[{j}].timestamp_sec - число")
            b = f.get("image_base64")
            if not isinstance(b, str):
                errs.append(f"{p}.evidence_frames[{j}].image_base64 - строка")
                continue
            try:
                head = base64.b64decode(b[:64] + "=" * (-len(b[:64]) % 4))
                if not head.startswith(b"\xff\xd8"):
                    errs.append(f"{p}.evidence_frames[{j}] - не JPEG")
            except Exception:
                errs.append(f"{p}.evidence_frames[{j}] - некорректный base64")
    return errs
