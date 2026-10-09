"""On-disk cache of collector records, used as a fallback when a source fails."""

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel


class DiskCache:
    def __init__(
        self, root: Path, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._root = Path(root)
        self._clock = clock

    def _path(self, source: str, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self._root / source / f"{digest}.json"

    def put(self, source: str, key: str, records: Sequence[BaseModel]) -> None:
        path = self._path(source, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": self._clock().isoformat(),
            "records": [record.model_dump(mode="json") for record in records],
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)

    def get(
        self, source: str, key: str, record_type: type[BaseModel], max_age: timedelta
    ) -> list[BaseModel] | None:
        try:
            payload = json.loads(self._path(source, key).read_text(encoding="utf-8"))
            saved_at = datetime.fromisoformat(payload["saved_at"])
            if self._clock() - saved_at > max_age:
                return None
            return [record_type.model_validate(raw) for raw in payload["records"]]
        except (OSError, ValueError, KeyError):  # missing, corrupt, or schema-changed entries
            return None
