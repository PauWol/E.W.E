from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

log = logging.getLogger(__name__)


class EweError(RuntimeError):
    """Raised for expected, user-facing EWE failures (not a bug, just bad input/state)."""


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def is_root() -> bool:
    return os.geteuid() == 0


def require_root() -> None:
    """Re-exec the current process under sudo if it isn't already root.

    EWE needs root to bring up interfaces and run hostapd/dnsmasq via
    lnxrouter. Rather than failing with a permissions error, we transparently
    re-exec with sudo so the walkthrough still feels like a single command.
    """
    if is_root():
        return

    if not command_exists("sudo"):
        raise EweError("This needs to run as root, and 'sudo' isn't available.")

    log.info("Root privileges required, re-running with sudo...")
    os.execvp("sudo", ["sudo", "-E", sys.executable, *sys.argv])


def has_networkmanager() -> bool:
    """True if NetworkManager is installed and its systemd unit is active."""
    if not command_exists("nmcli"):
        return False

    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", "NetworkManager"],
        check=False,
    )
    return result.returncode == 0


def list_wifi_interfaces() -> list[str]:
    """Return the names of all wireless interfaces on this machine."""
    if not command_exists("iw"):
        raise EweError(
            "'iw' is required to detect wireless interfaces (apt install iw)."
        )

    result = subprocess.run(["iw", "dev"], check=True, capture_output=True, text=True)

    interfaces: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("Interface "):
            interfaces.append(line.split("Interface ", 1)[1].strip())

    return interfaces


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    log.debug(f"Running: {' '.join(command)}")
    kwargs.setdefault("check", True)
    return subprocess.run(command, **kwargs)
