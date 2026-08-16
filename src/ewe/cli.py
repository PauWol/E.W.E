from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
from collections.abc import Sequence

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


# ---------------------------------------------------------------------------
# Terminal UI
# ---------------------------------------------------------------------------


def _supports_color() -> bool:
    return (
        sys.stdout.isatty()
        and os.environ.get("NO_COLOR") is None
        and os.environ.get("TERMINAL_NO_COLOR") is None
    )


_COLOR = _supports_color()


def _style(text: str, code: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def _bold(text: str) -> str:
    return _style(text, "1")


def _dim(text: str) -> str:
    return _style(text, "2")


def _green(text: str) -> str:
    return _style(text, "32")


def _yellow(text: str) -> str:
    return _style(text, "33")


def _red(text: str) -> str:
    return _style(text, "31")


def _cyan(text: str) -> str:
    return _style(text, "36")


def _line(char: str = "─", width: int = 64) -> None:
    print(char * width)


def _header(title: str, subtitle: str | None = None) -> None:
    print()
    _line("═")
    print(f"  {_bold(title)}")
    if subtitle:
        print(f"  {_dim(subtitle)}")
    _line("═")
    print()


def _step(number: int, total: int, title: str) -> None:
    print(f"\n{_cyan(f'[{number}/{total}]')} {_bold(title)}")
    _line()


def _ok(text: str) -> None:
    print(f"  {_green('✓')} {text}")


def _warn(text: str) -> None:
    print(f"  {_yellow('!')} {text}")


def _error(text: str) -> None:
    print(f"  {_red('✗')} {text}")


def _info(text: str) -> None:
    print(f"  {_cyan('›')} {text}")


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def _prompt(text: str, default: str = "") -> str:
    suffix = f" {_dim(f'[{default}]')}" if default else ""
    try:
        value = input(f"  {text}{suffix}: ").strip()
    except EOFError as exc:
        raise EweError(
            "Input is unavailable. Are you running EWE interactively?"
        ) from exc

    return value or default


def _prompt_password(text: str, default: str = "") -> str:
    suffix = f" {_dim('[keep saved password]')}" if default else ""

    try:
        value = getpass.getpass(f"  {text}{suffix}: ").strip()
    except EOFError as exc:
        raise EweError("Password input is unavailable.") from exc

    return value or default


def _prompt_yes_no(text: str, default_yes: bool = True) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"

    try:
        value = input(f"  {text} {_dim(suffix)}: ").strip().lower()
    except EOFError as exc:
        raise EweError(
            "Input is unavailable. Are you running EWE interactively?"
        ) from exc

    if not value:
        return default_yes

    if value in {"y", "yes"}:
        return True

    if value in {"n", "no"}:
        return False

    print(f"  {_yellow('Please answer yes or no.')}")
    return _prompt_yes_no(text, default_yes)


def _prompt_int(
    text: str,
    default: int | None = None,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    allow_blank: bool = True,
) -> int | None:
    while True:
        default_text = str(default) if default is not None else ""
        value = _prompt(text, default_text)

        if not value and allow_blank:
            return None

        try:
            parsed = int(value)
        except ValueError:
            _warn("Please enter a number.")
            continue

        if minimum is not None and parsed < minimum:
            _warn(f"Value must be at least {minimum}.")
            continue

        if maximum is not None and parsed > maximum:
            _warn(f"Value must be at most {maximum}.")
            continue

        return parsed


def _choose_from_list(
    title: str,
    choices: Sequence[str],
    *,
    default: str | None = None,
    exclude: str | None = None,
) -> str:
    filtered = [choice for choice in choices if choice != exclude]

    if not filtered:
        raise EweError("No wireless interfaces are available for this selection.")

    if len(filtered) == 1:
        only = filtered[0]
        _info(f"{title}: using {_bold(only)} (only available option)")
        return only

    default_index = None
    if default in filtered:
        default_index = filtered.index(default) + 1

    print(f"  {title}")
    print()

    for index, name in enumerate(filtered, start=1):
        marker = ""
        if default_index == index:
            marker = f" {_green('(recommended)')}"
        print(f"    {_bold(str(index))}) {name}{marker}")

    while True:
        prompt = "Choose"
        if default_index is not None:
            prompt += f" [{default_index}]"

        raw = input(f"  {prompt}: ").strip()

        if not raw and default_index is not None:
            return filtered[default_index - 1]

        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(filtered):
                return filtered[index - 1]

        _warn(f"Choose a number between 1 and {len(filtered)}.")


# ---------------------------------------------------------------------------
# Validation / display
# ---------------------------------------------------------------------------


def _validate_wifi_credentials(ssid: str, password: str) -> None:
    if not ssid:
        raise EweError("SSID cannot be empty.")

    if not password:
        raise EweError("Wi-Fi password cannot be empty.")

    if len(ssid.encode()) > 32:
        raise EweError("SSID must be at most 32 bytes long.")

    if len(password) < 8:
        raise EweError("Wi-Fi password must be at least 8 characters long.")

    if len(password) > 63:
        raise EweError("Wi-Fi password must be at most 63 characters long.")


def _mask_secret(value: str) -> str:
    if not value:
        return "—"

    if len(value) <= 4:
        return "•" * len(value)

    return f"{value[:2]}{'•' * (len(value) - 4)}{value[-2:]}"


def _print_summary(
    *,
    wifi_iface: str,
    ap_iface: str,
    ssid: str,
    password: str,
    channel: int | None,
) -> None:
    print()
    _line()
    print(f"  {_bold('Configuration')}")
    _line()

    rows = [
        ("Uplink interface", wifi_iface),
        ("AP interface", ap_iface),
        ("SSID", ssid),
        ("Password", _mask_secret(password)),
        ("Channel", str(channel) if channel is not None else "Auto"),
    ]

    width = max(len(label) for label, _ in rows)

    for label, value in rows:
        print(f"  {label:<{width}}  {_cyan(value)}")

    _line()


# ---------------------------------------------------------------------------
# Core launch
# ---------------------------------------------------------------------------


def _launch(
    wifi_iface: str,
    ap_iface: str,
    ssid: str,
    password: str,
    channel: int | None,
) -> None:
    _info(f"Connecting to {_bold(ssid)} using {_bold(wifi_iface)}...")

    repeater = WifiRepeater(
        ap_iface=ap_iface,
        wifi_iface=wifi_iface,
    )

    try:
        repeater.connect_uplink(ssid, password)

        _ok("Uplink connected.")

        _info(
            f"Starting access point on {_bold(ap_iface)}"
            + (f" (channel {channel})" if channel else " (automatic channel)")
            + "..."
        )

        repeater.start_ap(
            ssid,
            password,
            channel=channel,
        )

        _ok("Access point started.")
        print()
        print(f"  {_green('✓')} {_bold('EWE is running.')}")

    finally:
        # This runs when the process is interrupted or an exception occurs.
        repeater.cleanup()


# ---------------------------------------------------------------------------
# Interactive setup
# ---------------------------------------------------------------------------


def run_walkthrough() -> None:
    _header(
        "E.W.E",
        "Easy WiFi Extender — interactive setup",
    )

    _info("Scanning for wireless interfaces...")
    interfaces = list_wifi_interfaces()

    if len(interfaces) < 2:
        raise EweError(
            f"Found {len(interfaces)} wireless interface(s). "
            "EWE requires at least two: one for the uplink and one for the AP."
        )

    _ok(f"Found {len(interfaces)} wireless interfaces:")
    for interface in interfaces:
        print(f"    • {interface}")

    try:
        recommended_uplink, recommended_ap = recommend_wifi_interfaces(interfaces)
    except Exception as exc:
        log.debug("Interface recommendation failed", exc_info=True)
        recommended_uplink = interfaces[0]
        recommended_ap = interfaces[1]

        _warn("Could not determine the best interface pairing.")
        _info("Using the first two available interfaces as defaults.")

    _step(1, 5, "Choose wireless interfaces")

    wifi_iface = _choose_from_list(
        "Interface for connecting to your existing Wi-Fi",
        interfaces,
        default=recommended_uplink,
    )

    ap_iface = _choose_from_list(
        "Interface for broadcasting the extended network",
        interfaces,
        default=recommended_ap if recommended_ap != wifi_iface else None,
        exclude=wifi_iface,
    )

    _ok(f"Uplink: {_bold(wifi_iface)}")
    _ok(f"AP:     {_bold(ap_iface)}")

    _step(2, 5, "Configure Wi-Fi")

    ssid = _prompt(
        "Wi-Fi network name (SSID)",
        constants.WIFI_SSID,
    )

    password = _prompt_password(
        "Wi-Fi password",
        constants.WIFI_PSK,
    )

    _validate_wifi_credentials(ssid, password)

    _ok("Wi-Fi credentials look valid.")

    _step(3, 5, "Configure access point")

    configured_channel: int | None = None

    if constants.WIFI_CHANNEL:
        try:
            configured_channel = int(constants.WIFI_CHANNEL)
        except ValueError:
            _warn(f"Ignoring invalid configured channel: {constants.WIFI_CHANNEL!r}")

    channel = _prompt_int(
        "Channel (blank = automatic)",
        configured_channel,
        minimum=1,
        maximum=196,
    )

    _step(4, 5, "Review configuration")

    _print_summary(
        wifi_iface=wifi_iface,
        ap_iface=ap_iface,
        ssid=ssid,
        password=password,
        channel=channel,
    )

    if not _prompt_yes_no("Start EWE with these settings?", default_yes=True):
        print()
        _warn("Setup cancelled.")
        return

    _step(5, 5, "Optional autostart")

    save_settings = _prompt_yes_no(
        "Save these settings to ~/ewe/.env?",
        default_yes=True,
    )

    if save_settings:
        constants.set_env("WIFI_SSID", ssid)
        constants.set_env("WIFI_PSK", password)
        constants.set_env("WIFI_AP_IFACE", ap_iface)
        constants.set_env("WIFI_UPLINK_IFACE", wifi_iface)
        constants.set_env(
            "WIFI_CHANNEL",
            str(channel) if channel is not None else "",
        )

        _ok(f"Settings saved to {constants.ENV_PATH}")

        install_service = _prompt_yes_no(
            "Install EWE as a systemd service?",
            default_yes=True,
        )

        if install_service:
            start_now = _prompt_yes_no(
                "Start the service now?",
                default_yes=False,
            )

            _info("Installing systemd service...")
            install_systemd_service(start_now=start_now)
            _ok("ewe.service installed and enabled.")

            if start_now:
                print()
                _ok("EWE is now managed by systemd.")
                return

    print()
    _line()
    _info("Starting EWE manually...")
    _line()

    _launch(
        wifi_iface,
        ap_iface,
        ssid,
        password,
        channel,
    )


# ---------------------------------------------------------------------------
# Environment / systemd mode
# ---------------------------------------------------------------------------


def run_from_env() -> None:
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ewe",
        description="Easy WiFi Extender",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ewe                 Start the interactive setup wizard\n"
            "  ewe --setup         Run the setup wizard\n"
            "  ewe --from-env      Start using saved settings\n"
            "  ewe --install-deps  Install/check required dependencies\n"
        ),
    )

    mode = parser.add_mutually_exclusive_group()

    mode.add_argument(
        "--setup",
        action="store_true",
        help="Run the interactive setup wizard.",
    )

    mode.add_argument(
        "--from-env",
        action="store_true",
        help="Start EWE using the saved configuration.",
    )

    mode.add_argument(
        "--install-deps",
        action="store_true",
        help="Install/check required system dependencies and exit.",
    )

    return parser


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    constants.load_dot_env()
    setup_logging()
    require_root()

    try:
        if args.install_deps:
            _header("E.W.E", "Dependency check")
            check_and_install_deps(auto_yes=True)
            _ok("Dependencies are ready.")
            return

        from_env = args.from_env

        # Interactive setup can answer dependency prompts itself.
        # Non-interactive/systemd mode must never block.
        check_and_install_deps(auto_yes=from_env)

        if from_env:
            run_from_env()
        else:
            run_walkthrough()

    except EweError as exc:
        _error(str(exc))
        sys.exit(1)

    except KeyboardInterrupt:
        print()
        _warn("Aborted by user.")
        sys.exit(130)

    except ValueError as exc:
        _error(str(exc))
        sys.exit(1)

    except Exception:
        log.exception("Unexpected EWE failure")
        _error("Unexpected error. Check the EWE logs for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
