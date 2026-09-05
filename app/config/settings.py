from pathlib import Path
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = APP_DIR.parent
DEFAULT_ENV_FILE = PROJECT_DIR / ".env"


class Settings:
    def __init__(self, env_file: Path = DEFAULT_ENV_FILE):
        self.env_file = env_file
        self._config: dict[str, str] = {}
        self._load_env_file()

        self.host = self.get("APP_HOST", "127.0.0.1")
        self.port = self.get_int("APP_PORT", 8000)
        self.reload = self.get_bool("APP_RELOAD", True)
        self.log_level = self.get("APP_LOG_LEVEL", "info")

    def _load_env_file(self):
        if not self.env_file.exists():
            logger.warning("Environment file %s not found. Using defaults.", self.env_file)
            return

        with open(self.env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key, value = key.strip(), value.strip()
                    self._config[key] = value
                    # Expose to os.environ for connectors (e.g. optional Reddit PRAW)
                    os.environ.setdefault(key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        return int(self.get(key, default))

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = str(self.get(key, str(default))).lower()
        return value in ("true", "1", "yes", "on")


def get_settings() -> Settings:
    return Settings()
