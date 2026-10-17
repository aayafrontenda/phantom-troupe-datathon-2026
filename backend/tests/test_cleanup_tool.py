"""tools/cleanup_demo.py removes test checks through the UI API with an admin key."""
from __future__ import annotations

import sys
from pathlib import Path

from backend.tests.conftest import make_app, upload, wait_done, wait_ready

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import cleanup_demo  # noqa: E402


def test_cleanup_demo_deletes_checks(tmp_path, video):
    with make_app(tmp_path, DEDUP="0", MOCK_DELAY="0.2") as (c, st):
        wait_ready(c)
        ids = [upload(c, video).json()["job_id"] for _ in range(2)]
        for jid in ids:
            wait_done(c, jid)
        key = st.settings.resolve_admin_key()
        lines: list[str] = []
        assert cleanup_demo.run(c, "http://testserver", key, False, [], out=lines.append) == 0
        assert lines[0].startswith("2 checks") and "dry run" in lines[0]
        assert len(c.get("/ui/api/jobs").json()["jobs"]) == 2
        lines.clear()
        assert cleanup_demo.run(c, "http://testserver", key, True, [], out=lines.append) == 0
        assert sum("-> deleted" in x for x in lines) == 2
        assert c.get("/ui/api/jobs").json()["jobs"] == []
