from __future__ import annotations

import json
from pathlib import Path


def build_report(data, template: Path, destination: Path):
    # application/json verhindert JS-Ausführung. < zusätzlich escapen, damit auch
    # ein bösartiges </script> im Interviewtext das Script-Element nicht schliesst.
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    payload = payload.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = template.read_text(encoding="utf-8").replace("__REPORT_DATA__", payload)
    destination.write_text(html, encoding="utf-8")
