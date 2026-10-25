"""Persistence of user settings (e.g. the last used printer address)."""

from __future__ import annotations

import json
from pathlib import Path

from platformdirs import user_config_dir

APP_NAME = "LT200B-GUI"
CONFIG_FILENAME = "config.json"


class ConfigStore:
    """Loads and saves a small JSON settings file in the user config dir."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = config_dir or Path(user_config_dir(APP_NAME))
        self._path = self._config_dir / CONFIG_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, values: dict[str, str]) -> None:
        merged = {**self.load(), **values}
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
