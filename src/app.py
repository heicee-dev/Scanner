"""Application window for the Scanner desktop app."""

import customtkinter as ctk


def run() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")

    window = ctk.CTk()
    window.title("Scanner")
    window.geometry("960x640")
    window.minsize(640, 420)

    heading = ctk.CTkLabel(
        window,
        text="Scanner",
        font=ctk.CTkFont(size=28, weight="bold"),
    )
    heading.pack(expand=True)

    window.mainloop()
