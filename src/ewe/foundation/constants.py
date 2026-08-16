import os
import pwd
from pathlib import Path
from typing import TypeVar

from dotenv import load_dotenv

T = TypeVar("T")


def path(p: str | Path) -> Path:
    return Path(p).expanduser()


def user_home() -> Path:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        return Path(pwd.getpwnam(sudo_user).pw_dir)
    return Path.home()


ENV_PATH = user_home() / "ewe/.env"


def load_dot_env() -> bool:
    """Load ARC's .env file.

    Returns:
        True if the .env file was loaded.
        False if the file does not exist.
    """
    if not ENV_PATH.is_file():
        return False

    return load_dotenv(
        ENV_PATH,
        override=False,
    )


ENV_LOADED = load_dot_env()


def get_env(key: str, default: T) -> str | T:
    """
    Return an environment variable or a default value.
    """
    return os.getenv(key, default)


def get_env_str(key: str, default: str) -> str:
    return os.getenv(key, default)


def get_env_bool(key: str, default: str = "false") -> bool:
    value = os.getenv(key)
    if value is None:
        value = default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_env_int(key: str, default: str) -> int:
    value = os.getenv(key)
    if value is None:
        value = default
    return int(value)


def get_env_float(key: str, default: str) -> float:
    value = os.getenv(key)
    if value is None:
        value = default
    return float(value)


def set_env(key: str, value: T):  # pyright: ignore[reportInvalidTypeVarUse]
    _path = ENV_PATH

    _path.parent.mkdir(parents=True, exist_ok=True)

    if not _path.is_file():
        _ = _path.write_text("", encoding="utf-8")

    _updated = False

    lines = _path.read_text("utf-8").splitlines()

    for i, l in enumerate(lines):
        if l.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            _updated = True
            break

    if not _updated:
        lines.append(f"{key}={value}")

    _ = _path.write_text("\n".join(lines) + "\n")


DEFAULT_DOT_ENV = {
    "TERMINAL_NO_COLOR": "0",
    "PYTHONUNBUFFERED": "0",  # INFO: If logs aren't logged at the right time or don't at all set to 1
    # ---
    "LOG_LEVEL": "INFO",
    "LOG_FILE": "~/ewe/ewe.log",
    "LOG_CONSOLE": "1",
    "LOG_JSON": "0",
    "LOG_ROTATE": "1",
    "LOG_MAX_BYTES": "10485760",
    "LOG_BACKUP_COUNT": "1",
    # ---
    "WIFI_SSID_NAME_EXTENSION": "1",
    "WIFI_POWER_SAVING_OFF": "1",
}

_DEV = DEFAULT_DOT_ENV

# System
TERMINAL_NO_COLOR = get_env_bool("TERMINAL_NO_COLOR", _DEV["TERMINAL_NO_COLOR"])

# Logging
LOG_LEVEL = get_env_str("LOG_LEVEL", _DEV["LOG_LEVEL"])
LOG_FILE = path(get_env("LOG_FILE", _DEV["LOG_FILE"]))
LOG_CONSOLE = get_env_bool("LOG_CONSOLE", _DEV["LOG_CONSOLE"])
LOG_JSON = get_env_bool("LOG_JSON", _DEV["LOG_JSON"])
LOG_ROTATE = get_env_bool("LOG_ROTATE", _DEV["LOG_ROTATE"])
LOG_MAX_BYTES = get_env_int("LOG_MAX_BYTES", _DEV["LOG_MAX_BYTES"])
LOG_BACKUP_COUNT = get_env_int("LOG_BACKUP_COUNT", _DEV["LOG_BACKUP_COUNT"])

WIFI_SSID = get_env_str("WIFI_SSID", "")
WIFI_SSID_NAME_EXTENSION = get_env_bool(
    "WIFI_SSID_NAME_EXTENSION", _DEV["WIFI_SSID_NAME_EXTENSION"]
)
WIFI_PSK = get_env_str("WIFI_PSK", "")
WIFI_AP_IFACE = get_env_str("WIFI_AP_IFACE", "")
WIFI_UPLINK_IFACE = get_env_str("WIFI_UPLINK_IFACE", "")
WIFI_CHANNEL = get_env_str("WIFI_CHANNEL", "")
WIFI_POWER_SAVING_OFF = get_env_bool(
    "WIFI_POWER_SAVING_OFF", _DEV["WIFI_POWER_SAVING_OFF"]
)
