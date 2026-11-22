"""Application window for the Scanner desktop app."""

from __future__ import annotations

import ipaddress
import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import List, Optional, Tuple, Union

import customtkinter as ctk

from src.scanner import DeviceResult, NetworkScanner

logger = logging.getLogger(__name__)

UiEvent = Tuple[str, Union[str, DeviceResult, List[DeviceResult], Exception, None]]


class App(ctk.CTk):
    """Main application window with a sidebar and scanner content area."""

    def __init__(self) -> None:
        try:
            super().__init__()
        except Exception:
            logger.exception("Failed to initialize the CustomTkinter root window")
            raise

        self.title("Scanner")
        self.geometry("900x600")
        self.minsize(720, 480)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._ui_queue: queue.Queue[UiEvent] = queue.Queue()
        self._scan_thread: Optional[threading.Thread] = None
        self._hosts_total: int = 0
        self._hosts_scanned: int = 0
        self._scanner: Optional[NetworkScanner] = None

        self.sidebar: ctk.CTkFrame = self._build_sidebar()
        self.content: ctk.CTkFrame = self._build_content()
        self._configure_treeview_style()
        self._autofill_subnet()
        self.after(50, self._process_ui_queue)

    def _build_sidebar(self) -> ctk.CTkFrame:
        """Create the left navigation sidebar."""
        sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(4, weight=1)

        title = ctk.CTkLabel(
            sidebar,
            text="Scanner",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        title.grid(row=0, column=0, padx=20, pady=(24, 16), sticky="w")

        home_button = ctk.CTkButton(sidebar, text="Home", anchor="w")
        home_button.grid(row=1, column=0, padx=16, pady=6, sticky="ew")

        scan_button = ctk.CTkButton(sidebar, text="Scan", anchor="w")
        scan_button.grid(row=2, column=0, padx=16, pady=6, sticky="ew")

        settings_button = ctk.CTkButton(sidebar, text="Settings", anchor="w")
        settings_button.grid(row=3, column=0, padx=16, pady=6, sticky="ew")

        return sidebar

    def _build_content(self) -> ctk.CTkFrame:
        """Create the main scanner interface in the content frame."""
        content = ctk.CTkFrame(self, corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew", padx=(1, 0))
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(3, weight=1)

        header = ctk.CTkLabel(
            content,
            text="Network Scan",
            font=ctk.CTkFont(size=22, weight="bold"),
            anchor="w",
        )
        header.grid(row=0, column=0, padx=24, pady=(24, 12), sticky="ew")

        controls = ctk.CTkFrame(content, fg_color="transparent")
        controls.grid(row=1, column=0, padx=24, pady=(0, 12), sticky="ew")
        controls.grid_columnconfigure(1, weight=1)

        subnet_label = ctk.CTkLabel(controls, text="IP Subnet")
        subnet_label.grid(row=0, column=0, padx=(0, 12), sticky="w")

        self.subnet_entry = ctk.CTkEntry(
            controls,
            placeholder_text="192.168.1.0/24",
        )
        self.subnet_entry.grid(row=0, column=1, padx=(0, 12), sticky="ew")

        self.start_button = ctk.CTkButton(
            controls,
            text="Start Scan",
            width=120,
            command=self._on_start_scan,
        )
        self.start_button.grid(row=0, column=2, sticky="e")

        progress_frame = ctk.CTkFrame(content, fg_color="transparent")
        progress_frame.grid(row=2, column=0, padx=24, pady=(0, 12), sticky="ew")
        progress_frame.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(progress_frame)
        self.progress_bar.grid(row=0, column=0, sticky="ew")
        self.progress_bar.set(0)

        self.status_label = ctk.CTkLabel(
            progress_frame,
            text="Ready",
            anchor="w",
            font=ctk.CTkFont(size=12),
        )
        self.status_label.grid(row=1, column=0, pady=(8, 0), sticky="ew")

        table_frame = ctk.CTkFrame(content)
        table_frame.grid(row=3, column=0, padx=24, pady=(0, 24), sticky="nsew")
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        self.results_tree = ttk.Treeview(
            table_frame,
            columns=("ip", "hostname", "status"),
            show="headings",
            selectmode="browse",
        )
        self.results_tree.heading("ip", text="IP Address")
        self.results_tree.heading("hostname", text="Hostname")
        self.results_tree.heading("status", text="Status")
        self.results_tree.column("ip", width=160, anchor="w")
        self.results_tree.column("hostname", width=260, anchor="w")
        self.results_tree.column("status", width=120, anchor="w")

        scrollbar = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.results_tree.yview,
        )
        self.results_tree.configure(yscrollcommand=scrollbar.set)
        self.results_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        return content

    def _configure_treeview_style(self) -> None:
        """Style ttk.Treeview to match CustomTkinter colors."""
        try:
            style = ttk.Style(self)
            try:
                style.theme_use("clam")
            except tk.TclError:
                logger.debug("clam theme unavailable; keeping default ttk theme")

            appearance = ctk.get_appearance_mode()
            if appearance == "Dark":
                background = "#2b2b2b"
                foreground = "#dce4ee"
                field_background = "#212121"
                heading_background = "#1f538d"
                selected_background = "#1f538d"
                border_color = "#3a3a3a"
            else:
                background = "#dbdbdb"
                foreground = "#1a1a1a"
                field_background = "#f0f0f0"
                heading_background = "#3b8ed0"
                selected_background = "#3b8ed0"
                border_color = "#cfcfcf"

            # Prefer live CustomTkinter theme colors when available.
            try:
                background = self._apply_appearance_mode(
                    ctk.ThemeManager.theme["CTkFrame"]["fg_color"]
                )
                foreground = self._apply_appearance_mode(
                    ctk.ThemeManager.theme["CTkLabel"]["text_color"]
                )
                field_background = self._apply_appearance_mode(
                    ctk.ThemeManager.theme["CTkEntry"]["fg_color"]
                )
                heading_background = self._apply_appearance_mode(
                    ctk.ThemeManager.theme["CTkButton"]["fg_color"]
                )
                selected_background = heading_background
            except (KeyError, TypeError, AttributeError):
                logger.debug("Falling back to static Treeview colors", exc_info=True)

            style.configure(
                "Scanner.Treeview",
                background=field_background,
                foreground=foreground,
                fieldbackground=field_background,
                bordercolor=border_color,
                borderwidth=0,
                rowheight=28,
                font=("Segoe UI", 11),
            )
            style.configure(
                "Scanner.Treeview.Heading",
                background=heading_background,
                foreground="#ffffff",
                relief="flat",
                borderwidth=0,
                font=("Segoe UI", 11, "bold"),
            )
            style.map(
                "Scanner.Treeview",
                background=[("selected", selected_background)],
                foreground=[("selected", "#ffffff")],
            )
            style.map(
                "Scanner.Treeview.Heading",
                background=[("active", heading_background)],
            )
            self.results_tree.configure(style="Scanner.Treeview")
        except Exception:
            logger.exception("Failed to configure Treeview style")

    def _autofill_subnet(self) -> None:
        """Populate the subnet entry using local network detection."""
        try:
            default_subnet = NetworkScanner().get_default_subnet()
        except Exception:
            logger.exception("Unable to auto-detect local subnet; using fallback")
            default_subnet = "192.168.1.0/24"

        self.subnet_entry.delete(0, tk.END)
        self.subnet_entry.insert(0, default_subnet)
        self.status_label.configure(text=f"Default subnet detected: {default_subnet}")

    def _on_start_scan(self) -> None:
        """Disable controls and launch NetworkScanner on a worker thread."""
        if self._scan_thread is not None and self._scan_thread.is_alive():
            logger.warning("Start Scan ignored because a scan is already running")
            return

        subnet = self.subnet_entry.get().strip()
        if not subnet:
            self.status_label.configure(text="Enter a subnet to scan (e.g. 192.168.1.0/24)")
            return

        try:
            network = ipaddress.ip_network(subnet, strict=False)
            if not isinstance(network, ipaddress.IPv4Network):
                raise ValueError("Only IPv4 subnets are supported")
        except ValueError:
            logger.exception("Invalid subnet entered: %s", subnet)
            self.status_label.configure(text=f"Invalid subnet: {subnet}")
            return

        hosts = list(network.hosts()) or [network.network_address]
        self._hosts_total = len(hosts)
        self._hosts_scanned = 0

        for item in self.results_tree.get_children():
            self.results_tree.delete(item)

        self.progress_bar.set(0)
        self.status_label.configure(text=f"Starting scan of {subnet}...")
        self.start_button.configure(state="disabled")
        self.subnet_entry.configure(state="disabled")

        self._scanner = NetworkScanner(
            timeout_ms=800,
            max_workers=64,
            on_progress=self._enqueue_progress,
            on_result=self._enqueue_result,
            on_complete=self._enqueue_complete,
        )

        self._scan_thread = threading.Thread(
            target=self._run_scan,
            args=(subnet,),
            name="NetworkScanThread",
            daemon=True,
        )
        self._scan_thread.start()

    def _run_scan(self, subnet: str) -> None:
        """Execute the network sweep off the UI thread."""
        try:
            if self._scanner is None:
                raise RuntimeError("NetworkScanner was not initialized")
            self._scanner.discover(subnet)
        except Exception as exc:
            logger.exception("Background network scan failed for subnet %s", subnet)
            self._ui_queue.put(("error", exc))

    def _enqueue_progress(self, message: str) -> None:
        self._ui_queue.put(("progress", message))

    def _enqueue_result(self, result: DeviceResult) -> None:
        self._ui_queue.put(("result", result))

    def _enqueue_complete(self, results: List[DeviceResult]) -> None:
        self._ui_queue.put(("complete", results))

    def _process_ui_queue(self) -> None:
        """Drain thread-safe events and update UI widgets on the main thread."""
        try:
            while True:
                event_type, payload = self._ui_queue.get_nowait()
                if event_type == "progress" and isinstance(payload, str):
                    self._handle_progress(payload)
                elif event_type == "result" and isinstance(payload, DeviceResult):
                    self._handle_result(payload)
                elif event_type == "complete" and isinstance(payload, list):
                    self._handle_complete(payload)
                elif event_type == "error":
                    self._handle_error(payload)
                else:
                    logger.warning("Ignoring unexpected UI queue event: %s", event_type)
        except queue.Empty:
            pass
        except Exception:
            logger.exception("Failed while processing UI queue events")

        self.after(50, self._process_ui_queue)

    def _handle_progress(self, message: str) -> None:
        self.status_label.configure(text=message)
        if message.startswith("Scanning "):
            self._hosts_scanned += 1
            if self._hosts_total > 0:
                self.progress_bar.set(min(self._hosts_scanned / self._hosts_total, 1.0))

    def _handle_result(self, result: DeviceResult) -> None:
        hostname = result.hostname or "—"
        status = "Online" if result.is_alive else "Offline"
        if result.response_time_ms is not None:
            status = f"Online ({result.response_time_ms:.0f} ms)"
        self.results_tree.insert(
            "",
            tk.END,
            values=(result.ip, hostname, status),
        )

    def _handle_complete(self, results: List[DeviceResult]) -> None:
        self.progress_bar.set(1.0)
        self.status_label.configure(
            text=f"Scan complete: {len(results)} active device(s) found"
        )
        self._set_scan_controls_enabled(True)

    def _handle_error(self, payload: object) -> None:
        message = str(payload) if payload is not None else "Unknown error"
        self.status_label.configure(text=f"Scan failed: {message}")
        self.progress_bar.set(0)
        self._set_scan_controls_enabled(True)

    def _set_scan_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.start_button.configure(state=state)
        self.subnet_entry.configure(state=state)


def run(app: Optional[App] = None) -> None:
    """Create the application window and start the event loop."""
    try:
        window = app if app is not None else App()
        window.mainloop()
    except Exception:
        logger.exception("Scanner application exited due to an unexpected error")
        raise
