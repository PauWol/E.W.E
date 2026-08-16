from collections.abc import Sequence

from cyclopts import App
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from ewe.foundation.util import EweError

console = Console()


def header(title: str, subtitle: str | None = None) -> None:
    content = f"[bold]{title}[/bold]"

    if subtitle:
        content += f"\n[dim]{subtitle}[/dim]"

    console.print(
        Panel(
            content,
            border_style="cyan",
            expand=False,
        )
    )


def step(number: int, total: int, title: str) -> None:
    console.print()
    console.print(f"[cyan][{number}/{total}][/cyan] [bold]{title}[/bold]")
    console.rule(style="dim")


def ok(text: str) -> None:
    console.print(f"  [green]✓[/green] {text}")


def warn(text: str) -> None:
    console.print(f"  [yellow]![/yellow] {text}")


def error(text: str) -> None:
    console.print(f"  [red]✗[/red] {text}")


def info(text: str) -> None:
    console.print(f"  [cyan]›[/cyan] {text}")


def choose_from_list(
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
        info(f"{title}: using [bold]{only}[/bold] (only option available)")
        return only

    console.print(f"  {title}")

    for index, name in enumerate(filtered, start=1):
        suffix = " [green](recommended)[/green]" if name == default else ""
        console.print(f"    [bold]{index}[/bold]) {name}{suffix}")

    default_index = filtered.index(default) + 1 if default in filtered else None

    while True:
        raw = Prompt.ask(
            "  Choose",
            default=str(default_index) if default_index is not None else None,
        )

        if isinstance(raw, str) and raw.isdigit():
            index = int(raw)

            if 1 <= index <= len(filtered):
                return filtered[index - 1]

        warn(f"Choose a number between 1 and {len(filtered)}.")


def prompt_channel(default: int | None = None) -> int | None:
    raw = Prompt.ask(
        "Channel (blank = automatic)",
        default=str(default) if default is not None else "",
    ).strip()

    if not raw:
        return None

    try:
        channel = int(raw)
    except ValueError:
        raise EweError(f"Invalid WiFi channel: {raw!r}") from None

    if not 1 <= channel <= 196:
        raise EweError(f"WiFi channel must be between 1 and 196, got {channel}.")

    return channel


def validate_wifi_credentials(ssid: str, password: str) -> None:
    if not ssid:
        raise EweError("SSID cannot be empty.")

    if not password:
        raise EweError("WiFi password cannot be empty.")

    if len(ssid.encode()) > 32:
        raise EweError("SSID must be at most 32 bytes long.")

    if len(password) < 8:
        raise EweError("WiFi password must be at least 8 characters long.")

    if len(password) > 63:
        raise EweError("WiFi password must be at most 63 characters long.")


def _mask_secret(value: str) -> str:
    if not value:
        return "—"

    if len(value) <= 4:
        return "•" * len(value)

    return f"{value[:2]}{'•' * (len(value) - 4)}{value[-2:]}"


def print_summary(
    *,
    wifi_iface: str,
    ap_iface: str,
    ssid: str,
    password: str,
    channel: int | None,
) -> None:
    table = Table(
        title="Configuration",
        show_header=False,
        expand=False,
    )

    table.add_column("Setting", style="bold")
    table.add_column("Value", style="cyan")

    table.add_row("Uplink interface", wifi_iface)
    table.add_row("AP interface", ap_iface)
    table.add_row("SSID", ssid)
    table.add_row("Password", _mask_secret(password))
    table.add_row("Channel", str(channel) if channel is not None else "Auto")

    console.print(table)
