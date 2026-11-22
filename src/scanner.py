"""Network scanning utilities for discovering active devices on a subnet."""

from __future__ import annotations

import concurrent.futures
import ipaddress
import logging
import platform
import re
import socket
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]
ResultCallback = Callable[["DeviceResult"], None]
CompleteCallback = Callable[[list["DeviceResult"]], None]


@dataclass(frozen=True)
class DeviceResult:
    """A single host discovered (or probed) during a network scan."""

    ip: str
    hostname: str | None
    is_alive: bool
    response_time_ms: float | None = None


@dataclass(frozen=True)
class LocalNetworkInfo:
    """Local interface addressing used to derive a default scan range."""

    ip: str
    netmask: str
    network: str


class NetworkScanner:
    """Discover active hosts on a subnet using concurrent ICMP ping probes."""

    def __init__(
        self,
        *,
        timeout_ms: int = 1000,
        max_workers: int = 64,
        on_progress: ProgressCallback | None = None,
        on_result: ResultCallback | None = None,
        on_complete: CompleteCallback | None = None,
    ) -> None:
        self.timeout_ms = timeout_ms
        self.max_workers = max_workers
        self.on_progress = on_progress
        self.on_result = on_result
        self.on_complete = on_complete
        self._cancel_event = threading.Event()
        self._is_scanning = False
        self._lock = threading.Lock()

    @property
    def is_scanning(self) -> bool:
        """Return whether a scan is currently in progress."""
        with self._lock:
            return self._is_scanning

    def cancel(self) -> None:
        """Request cancellation of an in-progress scan."""
        self._cancel_event.set()
        logger.info("Network scan cancellation requested")

    def get_local_ip(self) -> str:
        """Return the primary local IPv4 address of this machine."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                # No packets are sent; this only selects a routable local interface.
                sock.connect(("8.8.8.8", 80))
                local_ip = sock.getsockname()[0]
            if local_ip and not local_ip.startswith("127."):
                return local_ip
        except OSError:
            logger.exception("Unable to determine local IP via UDP socket probe")

        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            if local_ip and not local_ip.startswith("127."):
                return local_ip
        except OSError:
            logger.exception("Unable to resolve local IP from hostname")

        raise RuntimeError("Could not determine the local machine IPv4 address")

    def get_local_network_info(self) -> LocalNetworkInfo:
        """Return local IP, subnet mask, and CIDR network for the default scan range."""
        local_ip = self.get_local_ip()
        netmask = self._resolve_netmask_for_ip(local_ip)

        try:
            network = ipaddress.IPv4Network(f"{local_ip}/{netmask}", strict=False)
        except ValueError:
            logger.exception(
                "Invalid local network addressing ip=%s netmask=%s; falling back to /24",
                local_ip,
                netmask,
            )
            network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
            netmask = str(network.netmask)

        info = LocalNetworkInfo(
            ip=local_ip,
            netmask=netmask,
            network=str(network),
        )
        logger.info(
            "Resolved local network info ip=%s netmask=%s network=%s",
            info.ip,
            info.netmask,
            info.network,
        )
        return info

    def get_default_subnet(self) -> str:
        """Return a CIDR subnet suitable as the default scanning range."""
        return self.get_local_network_info().network

    def discover(self, subnet: str) -> list[DeviceResult]:
        """
        Discover active devices on ``subnet`` (e.g. ``'192.168.1.0/24'``).

        Progress and live results are emitted through the configured callbacks.
        Returns the full list of alive hosts after the sweep completes (or is cancelled).
        """
        with self._lock:
            if self._is_scanning:
                raise RuntimeError("A network scan is already in progress")
            self._is_scanning = True
            self._cancel_event.clear()

        alive_results: list[DeviceResult] = []

        try:
            hosts = self._hosts_from_subnet(subnet)
            total = len(hosts)
            logger.info("Starting network scan of %s (%s hosts)", subnet, total)
            self._emit_progress(f"Starting scan of {subnet} ({total} hosts)...")

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.max_workers
            ) as executor:
                future_map = {
                    executor.submit(self._probe_host, str(host)): str(host)
                    for host in hosts
                }

                for future in concurrent.futures.as_completed(future_map):
                    if self._cancel_event.is_set():
                        for pending in future_map:
                            pending.cancel()
                        self._emit_progress("Scan cancelled")
                        break

                    host_ip = future_map[future]
                    try:
                        result = future.result()
                    except Exception:
                        logger.exception("Unexpected error while probing host %s", host_ip)
                        continue

                    if result is None:
                        continue

                    if result.is_alive:
                        alive_results.append(result)
                        self._emit_result(result)

            alive_results.sort(key=lambda item: ipaddress.IPv4Address(item.ip))
            self._emit_progress(
                f"Scan complete: {len(alive_results)} active device(s) found"
            )
            self._emit_complete(alive_results)
            return alive_results
        except Exception:
            logger.exception("Network scan failed for subnet %s", subnet)
            raise
        finally:
            with self._lock:
                self._is_scanning = False

    def _hosts_from_subnet(self, subnet: str) -> Sequence[ipaddress.IPv4Address]:
        try:
            network = ipaddress.ip_network(subnet, strict=False)
        except ValueError:
            logger.exception("Invalid subnet provided: %s", subnet)
            raise ValueError(f"Invalid subnet: {subnet}") from None

        if not isinstance(network, ipaddress.IPv4Network):
            raise TypeError(f"Only IPv4 subnets are supported: {subnet}")

        hosts = list(network.hosts())
        if not hosts:
            # /32 (and similar) networks have no usable host range via hosts().
            hosts = [network.network_address]
        return hosts

    def _probe_host(self, ip: str) -> DeviceResult | None:
        if self._cancel_event.is_set():
            return None

        self._emit_progress(f"Scanning {ip}...")

        is_alive, response_time_ms = self._ping(ip)
        if not is_alive:
            return DeviceResult(
                ip=ip,
                hostname=None,
                is_alive=False,
                response_time_ms=None,
            )

        hostname = self._resolve_hostname(ip)
        return DeviceResult(
            ip=ip,
            hostname=hostname,
            is_alive=True,
            response_time_ms=response_time_ms,
        )

    def _ping(self, ip: str) -> tuple[bool, float | None]:
        system = platform.system().lower()
        if system == "windows":
            command = [
                "ping",
                "-n",
                "1",
                "-w",
                str(self.timeout_ms),
                ip,
            ]
        else:
            # Linux/macOS: -c count, -W timeout in seconds.
            timeout_seconds = max(1, round(self.timeout_ms / 1000))
            command = ["ping", "-c", "1", "-W", str(timeout_seconds), ip]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=(self.timeout_ms / 1000) + 2,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Ping failed for %s: %s", ip, exc)
            return False, None

        if completed.returncode != 0:
            return False, None

        response_time_ms = self._parse_ping_time_ms(completed.stdout)
        return True, response_time_ms

    def _parse_ping_time_ms(self, output: str) -> float | None:
        match = re.search(
            r"(?:time[=<]|time=)(\d+(?:\.\d+)?)\s*ms",
            output,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            logger.warning("Unable to parse ping latency from output: %s", match.group(0))
            return None

    def _resolve_hostname(self, ip: str) -> str | None:
        try:
            hostname, _aliases, _addresses = socket.gethostbyaddr(ip)
            return hostname
        except socket.herror:
            return None
        except OSError:
            logger.debug("Hostname lookup failed for %s", ip, exc_info=True)
            return None

    def _resolve_netmask_for_ip(self, local_ip: str) -> str:
        system = platform.system().lower()
        try:
            if system == "windows":
                netmask = self._netmask_from_ipconfig(local_ip)
            else:
                netmask = (
                    self._netmask_from_ip_command(local_ip)
                    or self._netmask_from_ifconfig(local_ip)
                )
            if netmask:
                return netmask
        except Exception:
            logger.exception(
                "Failed to resolve subnet mask for %s; defaulting to 255.255.255.0",
                local_ip,
            )
        logger.warning(
            "Subnet mask for %s unavailable; defaulting to 255.255.255.0 (/24)",
            local_ip,
        )
        return "255.255.255.0"

    def _run_text_command(self, command: Sequence[str]) -> str | None:
        try:
            completed = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except FileNotFoundError:
            logger.debug("Command not found while probing network: %s", command[0])
            return None
        except (subprocess.TimeoutExpired, OSError):
            logger.warning(
                "Failed to run command while probing network: %s",
                command[0],
                exc_info=True,
            )
            return None
        return completed.stdout

    def _netmask_from_ipconfig(self, local_ip: str) -> str | None:
        output = self._run_text_command(["ipconfig"])
        if not output:
            return None

        blocks = re.split(r"\r?\n\r?\n", output)
        for block in blocks:
            if local_ip not in block:
                continue
            match = re.search(
                r"Subnet Mask[.\s]*:\s*(\d+\.\d+\.\d+\.\d+)",
                block,
                flags=re.IGNORECASE,
            )
            if match:
                return match.group(1)
        return None

    def _netmask_from_ip_command(self, local_ip: str) -> str | None:
        output = self._run_text_command(["ip", "-4", "-o", "addr", "show"])
        if not output:
            return None

        pattern = re.compile(rf"\binet\s+{re.escape(local_ip)}/(\d+)\b")
        for line in output.splitlines():
            match = pattern.search(line)
            if not match:
                continue
            try:
                network = ipaddress.IPv4Network(f"{local_ip}/{match.group(1)}", strict=False)
                return str(network.netmask)
            except ValueError:
                logger.exception("Invalid prefix length in ip addr output: %s", line)
                return None
        return None

    def _netmask_from_ifconfig(self, local_ip: str) -> str | None:
        output = self._run_text_command(["ifconfig"])
        if not output:
            return None

        blocks = re.split(r"\n(?=\S)", output)
        for block in blocks:
            if local_ip not in block:
                continue
            match = re.search(
                r"(?:netmask|Mask:?)\s*(?:0x([0-9a-fA-F]+)|(\d+\.\d+\.\d+\.\d+))",
                block,
            )
            if not match:
                continue
            if match.group(2):
                return match.group(2)
            try:
                raw = int(match.group(1), 16)
                return socket.inet_ntoa(raw.to_bytes(4, byteorder="big"))
            except (ValueError, OSError):
                logger.warning("Unable to parse ifconfig netmask for %s", local_ip)
                return None
        return None

    def _emit_progress(self, message: str) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress(message)
        except Exception:
            logger.exception("Progress callback raised unexpectedly")

    def _emit_result(self, result: DeviceResult) -> None:
        if self.on_result is None:
            return
        try:
            self.on_result(result)
        except Exception:
            logger.exception("Result callback raised unexpectedly for %s", result.ip)

    def _emit_complete(self, results: list[DeviceResult]) -> None:
        if self.on_complete is None:
            return
        try:
            self.on_complete(results)
        except Exception:
            logger.exception("Complete callback raised unexpectedly")
