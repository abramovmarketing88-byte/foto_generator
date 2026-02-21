from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


class LocalStorage:
    def __init__(self, root_dir: str):
        self.root = Path(root_dir)
        self.raw_dir = self.root / "raw"
        self.results_dir = self.root / "results"

    def ensure_dirs(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def user_raw_dir(self, user_id: int) -> Path:
        path = self.raw_dir / str(user_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def user_results_dir(self, user_id: int) -> Path:
        path = self.results_dir / str(user_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def build_raw_photo_path(self, user_id: int, extension: str = ".jpg") -> Path:
        return self.user_raw_dir(user_id) / f"{uuid4().hex}{extension}"

    def build_result_path(self, user_id: int, job_id: int, extension: str = ".jpg") -> Path:
        return self.user_results_dir(user_id) / f"job_{job_id}_{uuid4().hex}{extension}"

    def cleanup_older_than_days(self, days: int) -> int:
        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        removed_count = 0

        for base_dir in (self.raw_dir, self.results_dir):
            if not base_dir.exists():
                continue

            for path in base_dir.rglob("*"):
                if not path.is_file():
                    continue
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if modified < threshold:
                    path.unlink(missing_ok=True)
                    removed_count += 1

        return removed_count

    def remove_user_data(self, user_id: int) -> None:
        for path in (self.raw_dir / str(user_id), self.results_dir / str(user_id)):
            if path.exists():
                shutil.rmtree(path)
