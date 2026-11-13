"""Baseline fingerprints, stored in the project at .qa-mcp/baselines.json."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def page_key(url: str) -> str:
    try:
        u = urlsplit(url)
        if u.scheme == "file":
            return "file://" + Path(u.path).name
        if u.scheme and u.netloc:
            return f"{u.scheme}://{u.netloc}{u.path}"
    except ValueError:
        pass
    return url


class BaselineStore:
    def __init__(self, root: Path):
        self.file = Path(root) / ".qa-mcp" / "baselines.json"

    def load(self) -> dict:
        try:
            return json.loads(self.file.read_text("utf8"))
        except (OSError, ValueError):
            return {}

    def get(self, url: str, locator: str) -> dict | None:
        entry = self.load().get(page_key(url), {}).get(locator)
        return entry["fingerprint"] if entry else None

    def put(self, url: str, entries: dict[str, dict]) -> None:
        data = self.load()
        page = data.setdefault(page_key(url), {})
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for loc, fp in entries.items():
            page[loc] = {"fingerprint": fp, "capturedAt": now}
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf8")
