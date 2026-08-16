from __future__ import annotations

import logging
import subprocess

from ewe.foundation.util import EweError, command_exists, has_networkmanager, run

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

    def _connect_uplink_nmcli(self, ssid: str, password: str, timeout: int) -> None:
        log.info(f"Connecting {self.wifi_iface} to '{ssid}' via NetworkManager")

        connection_name = f"ewe-uplink-{self.wifi_iface}"

        try:
            # Remove an old E.W.E profile if one exists.
            run(
                ["nmcli", "connection", "delete", connection_name],
                check=False,
            )

            # Create the WiFi profile explicitly.
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

            # Explicitly configure WPA-PSK.
            run(
                [
                    "nmcli",
                    "connection",
                    "modify",
                    connection_name,
                    "wifi-sec.key-mgmt",
                    "wpa-psk",
                    "wifi-sec.psk",
                    password,
                ],
                timeout=timeout,
            )

            # Bring the connection up.
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
        self, ssid: str, password: str, timeout: int
    ) -> None:
        if not command_exists("wpa_supplicant") or not command_exists("dhclient"):
            raise EweError(
                "NetworkManager isn't active and wpa_supplicant/dhclient "
                "aren't both available; can't connect the uplink interface."
            )

        log.info(f"Connecting {self.wifi_iface} to '{ssid}' via wpa_supplicant")

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

        # Clear out any stale supplicant instance for this interface first.
        run(["pkill", "-f", f"wpa_supplicant.*{self.wifi_iface}"], check=False)
        run(["wpa_supplicant", "-B", "-i", self.wifi_iface, "-c", conf_path])
        run(["dhclient", self.wifi_iface], timeout=timeout)

    # ---------- access point (bridge Internet from wifi_iface) ----------

    def start_ap(
        self,
        ssid: str,
        password: str,
        channel: int | None = None,
    ) -> None:
        """Start the repeater AP. Blocks in the foreground until stopped
        (Ctrl+C or SIGTERM) — lnxrouter owns hostapd/dnsmasq/iptables
        cleanup on exit, so we don't want to detach from it.
        """
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
            f"Starting access point '{ssid}' on {self.ap_iface}, bridging from {self.wifi_iface}"
        )
        subprocess.run(command, check=True)
