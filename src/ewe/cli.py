from __future__ import annotations

import getpass
import logging
import sys

from ewe.foundation import constants
from ewe.foundation.install import check_and_install_deps
from ewe.foundation.log import setup_logging
from ewe.foundation.util import EweError, list_wifi_interfaces, require_root
from ewe.wifi.repeater import WifiRepeater
from ewe.wifi.service import install_systemd_service

log = logging.getLogger(__name__)


# ---------- small prompt helpers ----------


def _prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{text}{suffix}: ").strip()
    return value or default


def _prompt_password(text: str, default: str = "") -> str:
    suffix = " [keep saved password]" if default else ""
    value = getpass.getpass(f"{text}{suffix}: ").strip()
    return value or default


def _prompt_yes_no(text: str, default_yes: bool = True) -> bool:
    suffix = " [Y/n]" if default_yes else " [y/N]"
    value = input(f"{text}{suffix}: ").strip().lower()
    if not value:
        return default_yes
    return value in ("y", "yes")


def _choose_interface(prompt: str, interfaces: list[str], exclude: str = "") -> str:
    choices = [i for i in interfaces if i != exclude]
    if not choices:
        raise EweError("No wireless interfaces left to choose from.")

    if len(choices) == 1:
        print(f"{prompt}: using '{choices[0]}' (only option available)")
        return choices[0]

    print(f"{prompt}:")
    for idx, name in enumerate(choices, start=1):
        print(f"  {idx}) {name}")

    while True:
        raw = input(f"  Choose 1-{len(choices)}: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1]
        print("  Invalid choice, try again.")


# ---------- core launch, shared by both entrypoints ----------


def _launch(
    wifi_iface: str, ap_iface: str, ssid: str, password: str, channel: int | None
) -> None:
    repeater = WifiRepeater(ap_iface=ap_iface, wifi_iface=wifi_iface)
    repeater.connect_uplink(ssid, password)
    repeater.start_ap(ssid, password, channel=channel)


# ---------- interactive walkthrough ----------


def run_walkthrough() -> None:
    print("=== E.W.E \u2014 Easy WiFi Extender ===\n")

    interfaces = list_wifi_interfaces()
    if len(interfaces) < 2:
        raise EweError(
            f"Found {len(interfaces)} wireless interface(s); EWE needs two "
            "(one to join your existing WiFi, one to broadcast the extended AP)."
        )

    wifi_iface = _choose_interface(
        "Interface to CONNECT to your existing WiFi (uplink)", interfaces
    )
    ap_iface = _choose_interface(
        "Interface to BROADCAST the extended AP", interfaces, exclude=wifi_iface
    )

    ssid = _prompt(
        "WiFi network name (SSID) \u2014 used for both connecting and the new AP",
        constants.WIFI_SSID,
    )
    password = _prompt_password(
        "WiFi password \u2014 same for both networks", constants.WIFI_PSK
    )
    if not ssid or not password:
        raise EweError("SSID and password are both required.")

    channel_raw = _prompt("Channel (blank = auto)", constants.WIFI_CHANNEL)
    channel = int(channel_raw) if channel_raw else None

    print("\nSummary:")
    print(f"  Uplink interface : {wifi_iface}")
    print(f"  AP interface     : {ap_iface}")
    print(f"  SSID             : {ssid}")
    print(f"  Channel          : {channel or 'auto'}\n")

    if not _prompt_yes_no("Proceed?"):
        print("Aborted.")
        return

    if _prompt_yes_no("Save these settings to ~/ewe/.env for autostart on boot?"):
        constants.set_env("WIFI_SSID", ssid)
        constants.set_env("WIFI_PSK", password)
        constants.set_env("WIFI_AP_IFACE", ap_iface)
        constants.set_env("WIFI_UPLINK_IFACE", wifi_iface)
        constants.set_env("WIFI_CHANNEL", channel or "")
        print(f"Saved to {constants.ENV_PATH}")

        if _prompt_yes_no(
            "Install + enable a systemd service so this starts automatically on boot?"
        ):
            start_now = _prompt_yes_no(
                "Start it now too (in addition to enabling it)?", default_yes=False
            )
            install_systemd_service(start_now=start_now)
            print("ewe.service installed and enabled.")
            if start_now:
                print(
                    "It's already running \u2014 you don't need to launch it manually below."
                )
                return

    _launch(wifi_iface, ap_iface, ssid, password, channel)


# ---------- non-interactive entrypoint (used by the systemd service) ----------


def run_from_env() -> None:
    missing = [k for k in ("WIFI_SSID", "WIFI_PSK") if not getattr(constants, k)]
    if missing:
        raise EweError(
            f"Missing {', '.join(missing)} in {constants.ENV_PATH}. "
            "Run the interactive walkthrough once first: `ewe --setup`."
        )

    if not constants.WIFI_AP_IFACE or not constants.WIFI_UPLINK_IFACE:
        raise EweError(
            "WIFI_AP_IFACE / WIFI_UPLINK_IFACE not set. "
            "Run the interactive walkthrough once first: `ewe --setup`."
        )

    channel = int(constants.WIFI_CHANNEL) if constants.WIFI_CHANNEL else None

    _launch(
        constants.WIFI_UPLINK_IFACE,
        constants.WIFI_AP_IFACE,
        constants.WIFI_SSID,
        constants.WIFI_PSK,
        channel,
    )


# ---------- entrypoint ----------


def main() -> None:
    constants.load_dot_env()
    setup_logging()
    require_root()

    try:
        if "--install-deps" in sys.argv:
            # Standalone: just fix dependencies and exit, don't launch anything.
            check_and_install_deps(auto_yes=True)
            print("Dependencies OK.")
            return

        from_env = "--from-env" in sys.argv

        # Every real run checks first — a stale/broken install shouldn't
        # get halfway into bringing up interfaces before failing. The
        # boot/systemd path has no tty to answer a prompt, so it installs
        # silently rather than blocking forever.
        check_and_install_deps(auto_yes=from_env)

        if from_env:
            run_from_env()
        else:
            run_walkthrough()
    except EweError as e:
        log.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
