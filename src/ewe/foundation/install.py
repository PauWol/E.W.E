from __future__ import annotations

import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ewe.foundation.util import EweError, command_exists, is_root, run

log = logging.getLogger(__name__)

LNXROUTER_URL = (
    "https://raw.githubusercontent.com/garywill/linux-router/master/lnxrouter"
)
LNXROUTER_PATH = Path("/usr/local/bin/lnxrouter")

# Command -> distro package name, only where it differs from the command itself.
PACKAGE_MAP: dict[str, dict[str, str]] = {
    "apt": {
        "iwconfig": "wireless-tools",
        "wpa_supplicant": "wpasupplicant",
        "dhclient": "isc-dhcp-client",
        "ip": "iproute2",
    },
    "dnf": {
        "iwconfig": "wireless-tools",
        "dhclient": "dhcp-client",
        "ip": "iproute",
    },
    "yum": {
        "iwconfig": "wireless-tools",
        "dhclient": "dhcp-client",
        "ip": "iproute",
    },
    "pacman": {
        "iwconfig": "wireless_tools",
        "ip": "iproute2",
    },
}

# Commands lnxrouter and the uplink connection logic actually shell out to.
REQUIRED_COMMANDS = [
    "hostapd",
    "dnsmasq",
    "iptables",
    "iw",
    "wpa_supplicant",
    "dhclient",
    "ip",
]
OPTIONAL_COMMANDS = ["haveged", "iwconfig"]  # nice-to-have, not fatal if missing


@dataclass(frozen=True)
class PackageManager:
    name: str
    install_cmd: list[str]
    update_cmd: list[str] | None


def detect_package_manager() -> PackageManager | None:
    if command_exists("apt-get"):
        return PackageManager(
            "apt", ["apt-get", "install", "-y"], ["apt-get", "update"]
        )
    if command_exists("dnf"):
        return PackageManager("dnf", ["dnf", "install", "-y"], None)
    if command_exists("pacman"):
        return PackageManager(
            "pacman", ["pacman", "-S", "--noconfirm"], ["pacman", "-Sy"]
        )
    if command_exists("yum"):
        return PackageManager("yum", ["yum", "install", "-y"], None)
    return None


def missing_commands(commands: list[str]) -> list[str]:
    return [c for c in commands if not command_exists(c)]


def check_lnxrouter() -> bool:
    return command_exists("lnxrouter")


def install_lnxrouter() -> None:
    log.info(f"Downloading lnxrouter from {LNXROUTER_URL}")
    try:
        urllib.request.urlretrieve(LNXROUTER_URL, LNXROUTER_PATH)
    except OSError as e:
        raise EweError(f"Failed to download lnxrouter: {e}") from e

    LNXROUTER_PATH.chmod(0o755)
    log.info(f"Installed lnxrouter to {LNXROUTER_PATH}")


def install_packages(commands: list[str]) -> None:
    pm = detect_package_manager()
    if pm is None:
        raise EweError(
            "Couldn't detect a supported package manager (apt/dnf/yum/pacman). "
            f"Please install these manually: {', '.join(commands)}"
        )

    pkg_map = PACKAGE_MAP.get(pm.name, {})
    packages = sorted({pkg_map.get(c, c) for c in commands})

    if pm.update_cmd:
        run(pm.update_cmd)

    log.info(f"Installing via {pm.name}: {', '.join(packages)}")
    run([*pm.install_cmd, *packages])


def check_and_install_deps(auto_yes: bool = False) -> None:
    """Check for lnxrouter and its runtime deps; offer to install anything missing.

    Call this after require_root() so we're already privileged if the user
    says yes. Raises EweError if the user declines or install fails.
    """
    missing_pkgs = missing_commands(REQUIRED_COMMANDS)
    missing_optional = missing_commands(OPTIONAL_COMMANDS)
    needs_lnxrouter = not check_lnxrouter()

    if not missing_pkgs and not needs_lnxrouter:
        return

    print("Missing dependencies:")
    if needs_lnxrouter:
        print("  - lnxrouter (not on PATH)")
    for c in missing_pkgs:
        print(f"  - {c}")
    if missing_optional:
        print(
            f"  (optional, skipping unless you want them: {', '.join(missing_optional)})"
        )

    if not auto_yes:
        answer = input("Install missing dependencies now? [Y/n]: ").strip().lower()
        if answer not in ("", "y", "yes"):
            raise EweError(
                "Missing dependencies; run with --install-deps or install them manually."
            )

    if not is_root():
        raise EweError("Installing dependencies requires root; re-run with sudo.")

    if missing_pkgs:
        install_packages(missing_pkgs)

    if needs_lnxrouter:
        install_lnxrouter()

    still_missing = missing_commands(REQUIRED_COMMANDS)
    lnxrouter_ok = check_lnxrouter()
    if still_missing or not lnxrouter_ok:
        problems = still_missing + ([] if lnxrouter_ok else ["lnxrouter"])
        raise EweError(f"Still missing after install: {', '.join(problems)}")

    print("All dependencies installed.\n")
