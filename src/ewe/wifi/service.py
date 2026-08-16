from __future__ import annotations

import logging
import sys
from pathlib import Path

from ewe.foundation.util import require_root, run

log = logging.getLogger(__name__)

SERVICE_PATH = Path("/etc/systemd/system/ewe.service")

SERVICE_TEMPLATE = """[Unit]
Description=E.W.E - Easy WiFi Extender
After=network.target NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
"""


def install_systemd_service(start_now: bool = False) -> None:
    """Write, enable (and optionally start) the ewe.service unit.

    On boot this runs the CLI's non-interactive entrypoint, which reads
    SSID/password/interfaces straight from ~/ewe/.env — no prompts.
    """
    require_root()

    exec_start = f"{sys.executable} -m ewe.cli --from-env"
    SERVICE_PATH.write_text(
        SERVICE_TEMPLATE.format(exec_start=exec_start),
        encoding="utf-8",
    )

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "unmask", "ewe.service"])
    run(["systemctl", "enable", "ewe.service"])

    log.info(f"Installed and enabled {SERVICE_PATH}")

    if start_now:
        run(["systemctl", "start", "ewe.service"])
        log.info("Started ewe.service")


def uninstall_systemd_service() -> None:
    require_root()
    run(["systemctl", "disable", "--now", "ewe.service"], check=False)
    SERVICE_PATH.unlink(missing_ok=True)
    run(["systemctl", "daemon-reload"])
    log.info("Removed ewe.service")
