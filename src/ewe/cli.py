from __future__ import annotations

import logging

from cyclopts import App
from rich.console import Console
from rich.prompt import Confirm, Prompt

from ewe.cli_helpers import (
    choose_from_list,
    error,
    header,
    info,
    ok,
    print_summary,
    prompt_channel,
    step,
    validate_wifi_credentials,
    warn,
)
from ewe.foundation import constants
from ewe.foundation.install import check_and_install_deps
from ewe.foundation.log import setup_logging
from ewe.foundation.util import (
    EweError,
    list_wifi_interfaces,
    recommend_wifi_interfaces,
    require_root,
)
from ewe.wifi.repeater import WifiRepeater
from ewe.wifi.service import install_systemd_service

log = logging.getLogger(__name__)

app = App(
    "ewe",
    help="Easy WiFi Extender — turn a Linux box with two WiFi radios into a WiFi extender.",
)
console = Console()


def _launch(
    wifi_iface: str,
    ap_iface: str,
    ssid: str,
    password: str,
    channel: int | None,
) -> None:
    """Common core launch method for E.W.E."""
    info(f"Connecting to [bold]{ssid}[/bold] using [bold]{wifi_iface}[/bold]...")

    repeater = WifiRepeater(
        ap_iface=ap_iface,
        wifi_iface=wifi_iface,
    )

    try:
        repeater.connect_uplink(ssid, password)

        ok("Uplink connected.")

        mode = f"channel {channel}" if channel else "automatic channel"

        info(f"Starting access point on [bold]{ap_iface}[/bold] ({mode})...")

        repeater.start_ap(
            ssid,
            password,
            channel=channel,
        )

        ok("Access point started.")

        console.print()
        console.print("  [green]✓[/green] [bold]EWE is running.[/bold]")

    finally:
        repeater.cleanup()


def run_walkthrough() -> None:
    """Interactive setup."""
    header(
        "E.W.E",
        "Easy WiFi Extender — interactive setup",
    )

    info("Scanning for wireless interfaces...")
    interfaces = list_wifi_interfaces()

    if len(interfaces) < 2:
        raise EweError(
            f"Found {len(interfaces)} wireless interface(s). "
            "EWE requires at least two: one for the uplink and one for the AP."
        )

    ok(f"Found {len(interfaces)} wireless interfaces:")

    for interface in interfaces:
        console.print(f"    • {interface}")

    try:
        recommended_uplink, recommended_ap = recommend_wifi_interfaces(interfaces)
    except Exception:
        log.debug("Interface recommendation failed", exc_info=True)

        recommended_uplink = interfaces[0]
        recommended_ap = interfaces[1]

        warn("Could not determine the best interface pairing.")
        info("Using the first two interfaces as defaults.")

    step(1, 5, "Choose wireless interfaces")

    wifi_iface = choose_from_list(
        "Interface for connecting to your existing WiFi",
        interfaces,
        default=recommended_uplink,
    )

    ap_iface = choose_from_list(
        "Interface for broadcasting the extended network",
        interfaces,
        default=(recommended_ap if recommended_ap != wifi_iface else None),
        exclude=wifi_iface,
    )

    ok(f"Uplink: [bold]{wifi_iface}[/bold]")
    ok(f"AP:     [bold]{ap_iface}[/bold]")

    step(2, 5, "Configure WiFi")

    ssid = Prompt.ask(
        "WiFi network name (SSID)",
        default=constants.WIFI_SSID,
    )

    password = Prompt.ask(
        "WiFi password",
        password=True,
        default=constants.WIFI_PSK,
    )

    validate_wifi_credentials(ssid, password)
    ok("WiFi credentials look valid.")

    step(3, 5, "Configure access point")

    configured_channel: int | None = None

    if constants.WIFI_CHANNEL:
        try:
            configured_channel = int(constants.WIFI_CHANNEL)
        except ValueError:
            warn(f"Ignoring invalid configured channel: {constants.WIFI_CHANNEL!r}")

    channel = prompt_channel(configured_channel)

    step(4, 5, "Review configuration")

    print_summary(
        wifi_iface=wifi_iface,
        ap_iface=ap_iface,
        ssid=ssid,
        password=password,
        channel=channel,
    )

    if not Confirm.ask(
        "Start EWE with these settings?",
        default=True,
    ):
        warn("Setup cancelled.")
        return

    step(5, 5, "Optional autostart")

    if Confirm.ask(
        "Save these settings to ~/ewe/.env?",
        default=True,
    ):
        constants.set_env("WIFI_SSID", ssid)
        constants.set_env("WIFI_PSK", password)
        constants.set_env("WIFI_AP_IFACE", ap_iface)
        constants.set_env("WIFI_UPLINK_IFACE", wifi_iface)
        constants.set_env(
            "WIFI_CHANNEL",
            str(channel) if channel is not None else "",
        )

        ok(f"Settings saved to {constants.ENV_PATH}")

        if Confirm.ask(
            "Install EWE as a systemd service?",
            default=True,
        ):
            start_now = Confirm.ask(
                "Start the service now?",
                default=False,
            )

            info("Installing systemd service...")
            install_systemd_service(start_now=start_now)

            ok("ewe.service installed and enabled.")

            if start_now:
                ok("EWE is now managed by systemd.")
                return

    console.rule(style="dim")
    info("Starting EWE manually...")
    console.rule(style="dim")

    _launch(
        wifi_iface,
        ap_iface,
        ssid,
        password,
        channel,
    )


def run_from_env() -> None:
    """Main method for the systemd service to start E.W.E"""

    missing = [key for key in ("WIFI_SSID", "WIFI_PSK") if not getattr(constants, key)]

    if missing:
        raise EweError(
            f"Missing {', '.join(missing)} in {constants.ENV_PATH}. "
            "Run `ewe --setup` first."
        )

    if not constants.WIFI_AP_IFACE or not constants.WIFI_UPLINK_IFACE:
        raise EweError(
            "WIFI_AP_IFACE / WIFI_UPLINK_IFACE are not configured. "
            "Run `ewe --setup` first."
        )

    try:
        channel = int(constants.WIFI_CHANNEL) if constants.WIFI_CHANNEL else None
    except ValueError as exc:
        raise EweError(
            f"Invalid WIFI_CHANNEL={constants.WIFI_CHANNEL!r} in {constants.ENV_PATH}."
        ) from exc

    _launch(
        constants.WIFI_UPLINK_IFACE,
        constants.WIFI_AP_IFACE,
        constants.WIFI_SSID,
        constants.WIFI_PSK,
        channel,
    )


def _run(*, from_env: bool = False, install_deps: bool = False) -> None:
    constants.load_dot_env()
    setup_logging()
    require_root()

    try:
        if install_deps:
            header("E.W.E", "Dependency check")
            check_and_install_deps(auto_yes=True)
            ok("Dependencies are ready.")
            return

        # Interactive setup may answer dependency prompts.
        # Non-interactive/systemd mode must never block.
        check_and_install_deps(auto_yes=from_env)

        if from_env:
            run_from_env()
        else:
            run_walkthrough()

    except EweError as exc:
        error(str(exc))
        raise SystemExit(1) from exc

    except KeyboardInterrupt:
        print()
        warn("Aborted by user.")
        raise SystemExit(130) from None

    except ValueError as exc:
        error(str(exc))
        raise SystemExit(1) from exc

    except Exception:
        log.exception("Unexpected EWE failure")
        error("Unexpected error. Check the EWE logs for details.")
        raise SystemExit(1) from None


@app.default
def main() -> None:
    """Start the interactive EWE setup wizard."""
    _run()


@app.command
def setup() -> None:
    """Start the interactive EWE setup wizard."""
    _run()


@app.command
def from_env() -> None:
    """Start EWE using the saved configuration.

    Intended for systemd and other non-interactive environments.
    """
    _run(from_env=True)


@app.command
def install_deps() -> None:
    """Install and verify EWE's required dependencies."""
    _run(install_deps=True)


if __name__ == "__main__":
    app()
