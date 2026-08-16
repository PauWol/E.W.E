from __future__ import annotations

import logging
import os
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
Environment="HOME={home}"
ExecStart={exec_start}
Restart=on-failure
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
"""


def install_systemd_service(start_now: bool = False) -> None:
    """Install and enable the E.W.E systemd service.

    The service runs as root, but HOME is set to the user that invoked
    EWE through sudo so ~/ewe/.env resolves to the user's config.
    """
    require_root()

    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        import pwd

        home = Path(pwd.getpwnam(sudo_user).pw_dir)
    else:
        home = Path.home()

    exec_start = f"{sys.executable} -m ewe.cli --from-env"

    SERVICE_PATH.write_text(
        SERVICE_TEMPLATE.format(
            exec_start=exec_start,
            home=home,
        ),
        encoding="utf-8",
    )

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "unmask", "ewe.service"])
    run(["systemctl", "enable", "ewe.service"])

    log.info("Installed and enabled %s", SERVICE_PATH)
    log.info("Using config: %s", home / "ewe/.env")

    if start_now:
        run(["systemctl", "start", "ewe.service"])
        log.info("Started ewe.service")


def uninstall_systemd_service() -> None:
    require_root()
    run(["systemctl", "disable", "--now", "ewe.service"], check=False)
    SERVICE_PATH.unlink(missing_ok=True)
    run(["systemctl", "daemon-reload"])
    log.info("Removed ewe.service")
