"""Application window for the Scanner desktop app."""

from __future__ import annotations

import logging
from typing import Optional

import customtkinter as ctk

logger = logging.getLogger(__name__)


class App(ctk.CTk):
    """Main application window with a sidebar and content area."""

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

        self.sidebar: ctk.CTkFrame = self._build_sidebar()
        self.content: ctk.CTkFrame = self._build_content()

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
        """Create the main content frame on the right."""
        content = ctk.CTkFrame(self, corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew", padx=(1, 0))
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        placeholder = ctk.CTkLabel(
            content,
            text="Main content",
            font=ctk.CTkFont(size=18),
        )
        placeholder.grid(row=0, column=0, padx=24, pady=24)

        return content


def run(app: Optional[App] = None) -> None:
    """Create the application window and start the event loop."""
    try:
        window = app if app is not None else App()
        window.mainloop()
    except Exception:
        logger.exception("Scanner application exited due to an unexpected error")
        raise
