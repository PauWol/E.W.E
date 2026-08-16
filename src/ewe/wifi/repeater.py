from __future__ import annotations

import logging
import subprocess

from ewe.foundation.util import EweError, command_exists, has_networkmanager, run
from ewe.foundation.constants import WIFI_SSID_NAME_EXTENSION, WIFI_POWER_SAVING_OFF

log = logging.getLogger(__name__)


class WifiRepeater:
    """Turns two WiFi interfaces into a repeater.

    ``wifi_iface`` joins an existing WiFi network as a normal client (the
    "uplink"). ``ap_iface`` then broadcasts a new access point that shares
    that connection, via ``lnxrouter`` — the maintained successor to
    ``create_ap``.
    """

    def __init__(self, ap_iface: str, wifi_iface: str) -> None:
        self.ap_iface = ap_iface
        self.wifi_iface = wifi_iface

    # ---------- power saving ----------

    def _set_power_saving(self, enabled_off: bool) -> None:
        """Enable or disable WiFi power saving on both E.W.E interfaces."""
        if not enabled_off:
            return

        for iface in (self.wifi_iface, self.ap_iface):
            try:
                run(["iw", "dev", iface, "set", "power_save", "off"])
                log.info("Disabled WiFi power saving on %s", iface)
            except subprocess.CalledProcessError:
                log.warning(
                    "Could not disable WiFi power saving on %s",
                    iface,
                )

    # ---------- uplink (connect to the existing network) ----------

    def connect_uplink(self, ssid: str, password: str, timeout: int = 30) -> None:
        """Connect wifi_iface to an existing WiFi network.

        Uses NetworkManager (nmcli) when it's actively managing the system,
        otherwise falls back to wpa_supplicant + dhclient.
        """
        if has_networkmanager():
            self._connect_uplink_nmcli(ssid, password, timeout)
        else:
            self._connect_uplink_wpa_supplicant(ssid, password, timeout)

        self._set_power_saving(WIFI_POWER_SAVING_OFF)

    def _connect_uplink_nmcli(
        self,
        ssid: str,
        password: str,
        timeout: int,
    ) -> None:
        log.info(
            "Connecting %s to '%s' via NetworkManager",
            self.wifi_iface,
            ssid,
        )

        connection_name = f"ewe-uplink-{self.wifi_iface}"

        try:
            run(
                ["nmcli", "connection", "delete", connection_name],
                check=False,
            )

            run(
                [
                    "nmcli",
                    "connection",
                    "add",
                    "type",
                    "wifi",
                    "ifname",
                    self.wifi_iface,
                    "con-name",
                    connection_name,
                    "ssid",
                    ssid,
                ],
                timeout=timeout,
            )

            modify_args = [
                "nmcli",
                "connection",
                "modify",
                connection_name,
                "wifi-sec.key-mgmt",
                "wpa-psk",
                "wifi-sec.psk",
                password,
            ]

            if WIFI_POWER_SAVING_OFF:
                modify_args.extend(
                    [
                        "802-11-wireless.powersave",
                        "2",
                    ]
                )

            run(modify_args, timeout=timeout)

            run(
                [
                    "nmcli",
                    "connection",
                    "up",
                    connection_name,
                ],
                timeout=timeout,
            )

        except subprocess.CalledProcessError as e:
            raise EweError(
                f"Failed to connect {self.wifi_iface} to '{ssid}': {e}"
            ) from e

    def _connect_uplink_wpa_supplicant(
        self,
        ssid: str,
        password: str,
        timeout: int,
    ) -> None:
        if not command_exists("wpa_supplicant") or not command_exists("dhclient"):
            raise EweError(
                "NetworkManager isn't active and wpa_supplicant/dhclient "
                "aren't both available; can't connect the uplink interface."
            )

        log.info(
            "Connecting %s to '%s' via wpa_supplicant",
            self.wifi_iface,
            ssid,
        )

        conf_path = f"/tmp/ewe-wpa-{self.wifi_iface}.conf"
        wpa_conf = (
            "ctrl_interface=/var/run/wpa_supplicant\n"
            "update_config=1\n\n"
            "network={\n"
            f'    ssid="{ssid}"\n'
            f'    psk="{password}"\n'
            "}\n"
        )

        with open(conf_path, "w") as f:
            f.write(wpa_conf)

        run(
            ["pkill", "-f", f"wpa_supplicant.*{self.wifi_iface}"],
            check=False,
        )
        run(
            [
                "wpa_supplicant",
                "-B",
                "-i",
                self.wifi_iface,
                "-c",
                conf_path,
            ]
        )
        run(["dhclient", self.wifi_iface], timeout=timeout)

    # ---------- access point (bridge Internet from wifi_iface) ----------

    def start_ap(
        self,
        ssid: str,
        password: str,
        channel: int | None = None,
    ) -> None:
        """Start the repeater AP."""
        if WIFI_SSID_NAME_EXTENSION:
            ssid = f"{ssid}-E.W.E"

        # AP interface is configured by lnxrouter, but disable power saving
        # beforehand when requested.
        self._set_power_saving(WIFI_POWER_SAVING_OFF)

        command = [
            "lnxrouter",
            "--ap",
            self.ap_iface,
            ssid,
            "--password",
            password,
            "-o",
            self.wifi_iface,
        ]

        if channel is not None:
            command.extend(["--channel", str(channel)])

        log.info(
            "Starting access point '%s' on %s, bridging from %s",
            ssid,
            self.ap_iface,
            self.wifi_iface,
        )

        subprocess.run(command, check=True)
