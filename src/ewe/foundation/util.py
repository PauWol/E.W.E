from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)


class EweError(RuntimeError):
    """Raised for expected, user-facing EWE failures."""


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def is_root() -> bool:
    return os.geteuid() == 0


def require_root() -> None:
    if is_root():
        return

    if not command_exists("sudo"):
        raise EweError("This needs to run as root, and 'sudo' isn't available.")

    log.info("Root privileges required, re-running with sudo...")
    os.execvp("sudo", ["sudo", "-E", sys.executable, *sys.argv])


def has_networkmanager() -> bool:
    if not command_exists("nmcli"):
        return False

    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", "NetworkManager"],
        check=False,
    )
    return result.returncode == 0


def list_wifi_interfaces() -> list[str]:
    if not command_exists("iw"):
        raise EweError(
            "'iw' is required to detect wireless interfaces (apt install iw)."
        )

    result = subprocess.run(
        ["iw", "dev"],
        check=True,
        capture_output=True,
        text=True,
    )

    interfaces: list[str] = []

    for line in result.stdout.splitlines():
        line = line.strip()

        if line.startswith("Interface "):
            interfaces.append(line.split("Interface ", 1)[1].strip())

    return interfaces


def _wifi_driver(interface: str) -> str | None:
    """Return the kernel driver used by a WiFi interface."""
    driver_link = Path(f"/sys/class/net/{interface}/device/driver")

    try:
        return driver_link.resolve().name
    except FileNotFoundError:
        return None


def _wifi_phy(interface: str) -> str | None:
    """Return the PHY/radio name backing an interface, e.g. phy0."""
    phy = Path(f"/sys/class/net/{interface}/phy80211")

    try:
        return phy.resolve().name
    except FileNotFoundError:
        return None


def _supports_ap(interface: str) -> bool:
    """Return whether the interface advertises AP mode."""
    result = subprocess.run(
        ["iw", "phy", _wifi_phy(interface) or "", "info"],
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return False

    return " * AP" in result.stdout or " AP\n" in result.stdout


def recommend_wifi_interfaces(
    interfaces: list[str] | None = None,
) -> tuple[str, str]:
    """
    Recommend (uplink_interface, ap_interface).

    Preference:
      - AP should not use brcmfmac.
      - AP interface should support AP mode.
      - Separate physical PHYs are preferred.

    Raises:
        EweError: if no viable AP interface exists.
    """
    interfaces = interfaces or list_wifi_interfaces()

    if len(interfaces) < 2:
        raise EweError("EWE needs at least two WiFi interfaces for repeater mode.")

    info: list[dict[str, object]] = []

    for iface in interfaces:
        driver = _wifi_driver(iface)
        phy = _wifi_phy(iface)
        ap = _supports_ap(iface)

        info.append(
            {
                "iface": iface,
                "driver": driver,
                "phy": phy,
                "ap": ap,
            }
        )

    # Prefer a non-brcmfmac interface that supports AP mode.
    ap_candidates = [
        item for item in info if item["ap"] and item["driver"] != "brcmfmac"
    ]

    # Fall back to any interface supporting AP mode.
    if not ap_candidates:
        ap_candidates = [item for item in info if item["ap"]]

    if not ap_candidates:
        raise EweError("None of the detected WiFi interfaces report AP mode support.")

    # Pick the first usable AP interface.
    ap = ap_candidates[0]

    # Prefer another physical radio for the uplink.
    uplink_candidates = [
        item
        for item in info
        if item["iface"] != ap["iface"] and item["phy"] != ap["phy"]
    ]

    # Fall back to another interface if there is no separate PHY.
    if not uplink_candidates:
        uplink_candidates = [item for item in info if item["iface"] != ap["iface"]]

    if not uplink_candidates:
        raise EweError("Could not find a second WiFi interface for the uplink.")

    uplink = uplink_candidates[0]

    # User-facing warnings.
    if ap["driver"] == "brcmfmac":
        log.warning(
            "AP interface %s uses the brcmfmac driver.",
            ap["iface"],
        )
        log.warning("brcmfmac may not support station + AP operation reliably.")
        log.warning(
            "lnxrouter may refuse this configuration or the driver may "
            "cause kernel instability."
        )
        log.warning("See: https://github.com/oblique/create_ap/issues/203")

    if ap["phy"] == uplink["phy"]:
        log.warning(
            "WARNING: %s and %s use the same WiFi radio (%s).",
            uplink["iface"],
            ap["iface"],
            ap["phy"],
        )
        log.warning("Two interface names do not necessarily mean two physical radios.")

    log.info(
        "Recommended WiFi configuration: uplink=%s, AP=%s",
        uplink["iface"],
        ap["iface"],
    )

    return str(uplink["iface"]), str(ap["iface"])
