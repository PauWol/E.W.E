from __future__ import annotations

import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Confirm

from ewe.foundation.util import EweError, command_exists, is_root, run

log = logging.getLogger(__name__)

console = Console()

LNXROUTER_URL = (
    "https://raw.githubusercontent.com/garywill/linux-router/master/lnxrouter"
)
LNXROUTER_PATH = Path("/usr/local/bin/lnxrouter")

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

REQUIRED_COMMANDS = [
    "hostapd",
    "dnsmasq",
    "iptables",
    "iw",
    "wpa_supplicant",
    "dhclient",
    "ip",
]

OPTIONAL_COMMANDS = [
    "haveged",
    "iwconfig",
]


@dataclass(frozen=True)
class PackageManager:
    name: str
    install_cmd: list[str]
    update_cmd: list[str] | None


def detect_package_manager() -> PackageManager | None:
    if command_exists("apt-get"):
        return PackageManager(
            "apt",
            ["apt-get", "install", "-y"],
            ["apt-get", "update"],
        )

    if command_exists("dnf"):
        return PackageManager(
            "dnf",
            ["dnf", "install", "-y"],
            None,
        )

    if command_exists("pacman"):
        return PackageManager(
            "pacman",
            ["pacman", "-S", "--noconfirm"],
            ["pacman", "-Sy"],
        )

    if command_exists("yum"):
        return PackageManager(
            "yum",
            ["yum", "install", "-y"],
            None,
        )

    return None


def missing_commands(commands: list[str]) -> list[str]:
    return [command for command in commands if not command_exists(command)]


def check_lnxrouter() -> bool:
    return command_exists("lnxrouter")


def install_lnxrouter() -> None:
    console.print(
        Panel(
            "[bold]Installing lnxrouter[/bold]\n"
            "[dim]Downloading the networking backend from GitHub...[/dim]",
            border_style="cyan",
            expand=False,
        )
    )

    log.info("Downloading lnxrouter from %s", LNXROUTER_URL)

    try:
        urllib.request.urlretrieve(
            LNXROUTER_URL,
            LNXROUTER_PATH,
        )
    except OSError as exc:
        raise EweError(f"Failed to download lnxrouter: {exc}") from exc

    LNXROUTER_PATH.chmod(0o755)

    log.info("Installed lnxrouter to %s", LNXROUTER_PATH)

    console.print(
        f"  [green]✓[/green] Installed lnxrouter to [cyan]{LNXROUTER_PATH}[/cyan]"
    )


def install_packages(commands: list[str]) -> None:
    pm = detect_package_manager()

    if pm is None:
        raise EweError(
            "Couldn't detect a supported package manager "
            "(apt/dnf/yum/pacman). "
            f"Please install these manually: {', '.join(commands)}"
        )

    pkg_map = PACKAGE_MAP.get(pm.name, {})
    packages = sorted({pkg_map.get(command, command) for command in commands})

    if pm.update_cmd:
        console.print(
            f"  [cyan]›[/cyan] Updating package lists using [bold]{pm.name}[/bold]..."
        )
        run(pm.update_cmd)

    console.print(f"  [cyan]›[/cyan] Installing [bold]{', '.join(packages)}[/bold]...")

    log.info(
        "Installing via %s: %s",
        pm.name,
        ", ".join(packages),
    )

    run([*pm.install_cmd, *packages])

    console.print("  [green]✓[/green] Packages installed.")


def _print_dependency_status(
    missing: list[str],
    optional_missing: list[str],
    lnxrouter_missing: bool,
) -> None:
    table = Table(
        title="Dependency check",
        show_header=True,
        expand=False,
    )

    table.add_column("Dependency", style="bold")
    table.add_column("Status")
    table.add_column("Type")

    if lnxrouter_missing:
        table.add_row(
            "lnxrouter",
            "[yellow]missing[/yellow]",
            "[red]required[/red]",
        )
    else:
        table.add_row(
            "lnxrouter",
            "[green]ready[/green]",
            "required",
        )

    for command in REQUIRED_COMMANDS:
        if command in missing:
            table.add_row(
                command,
                "[yellow]missing[/yellow]",
                "[red]required[/red]",
            )
        else:
            table.add_row(
                command,
                "[green]ready[/green]",
                "required",
            )

    for command in OPTIONAL_COMMANDS:
        if command in optional_missing:
            table.add_row(
                command,
                "[dim]not installed[/dim]",
                "[dim]optional[/dim]",
            )
        else:
            table.add_row(
                command,
                "[green]ready[/green]",
                "[dim]optional[/dim]",
            )

    console.print(table)


def check_and_install_deps(auto_yes: bool = False) -> None:
    """Check dependencies and optionally install missing requirements."""

    missing_required = missing_commands(REQUIRED_COMMANDS)
    missing_optional = missing_commands(OPTIONAL_COMMANDS)
    missing_lnxrouter = not check_lnxrouter()

    if not missing_required and not missing_lnxrouter:
        console.print(
            "  [green]✓[/green] [bold]All required dependencies are available.[/bold]"
        )
        return

    _print_dependency_status(
        missing_required,
        missing_optional,
        missing_lnxrouter,
    )

    required_count = len(missing_required) + int(missing_lnxrouter)

    console.print()
    console.print(
        f"[yellow]![/yellow] "
        f"[bold]{required_count} required "
        f"dependency{' is' if required_count == 1 else 'ies are'} missing.[/bold]"
    )

    if not auto_yes:
        if not Confirm.ask(
            "Install the missing dependencies now?",
            default=True,
        ):
            raise EweError(
                "Missing dependencies. Run `ewe install-deps` or install them manually."
            )

    if not is_root():
        raise EweError(
            "Installing dependencies requires root privileges. Re-run with sudo."
        )

    console.print()
    console.print(
        Panel(
            "[bold]Installing dependencies[/bold]\n[dim]This may take a moment.[/dim]",
            border_style="cyan",
            expand=False,
        )
    )

    if missing_required:
        install_packages(missing_required)

    if missing_lnxrouter:
        install_lnxrouter()

    still_missing = missing_commands(REQUIRED_COMMANDS)
    lnxrouter_ok = check_lnxrouter()

    if still_missing or not lnxrouter_ok:
        problems = still_missing.copy()

        if not lnxrouter_ok:
            problems.append("lnxrouter")

        raise EweError(
            "Some dependencies are still missing after installation: "
            + ", ".join(problems)
        )

    console.print()
    console.print(
        Panel(
            "[green]✓[/green] [bold]All required dependencies are ready.[/bold]",
            border_style="green",
            expand=False,
        )
    )
