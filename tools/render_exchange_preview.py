#!/usr/bin/env python3
"""Render the native Vkus Exchange screen under Xvfb for a real Tk smoke test."""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from types import MethodType

import tkinter as tk
from PIL import ImageGrab

from vkus.app import VkusApp
from vkus.exchange_visual import install_exchange_visuals


class PreviewHost:
    """Minimal host that exercises the real VkusApp Exchange screen methods."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Vkus preview host")
        self.root.geometry("420x120+10+10")
        self.root.configure(bg="#030817")
        self.exchange_window = None
        self.exchange_tiger_photo = None
        self.exchange_categories_selected = set()

        install_exchange_visuals()
        method_names = (
            "_show_exchange", "_exchange_close", "_exchange_redraw",
            "_exchange_click", "_exchange_entry_focus_in",
            "_exchange_entry_focus_out", "_exchange_find",
            "_exchange_menu", "_exchange_set_filter", "_exchange_info",
        )
        for name in method_names:
            method = getattr(VkusApp, name)
            setattr(self, name, MethodType(method, self))
        self._set_nav_active = lambda *_args, **_kwargs: None

    def close(self):
        try:
            if self.exchange_window is not None:
                self.exchange_window.destroy()
        finally:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/Vkus_3.17_Exchange.png")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    host = PreviewHost()
    host._show_exchange()
    host.root.update_idletasks()
    host.root.update()

    window = host.exchange_window
    if window is None or not window.winfo_exists():
        raise RuntimeError("Vkus Exchange window did not open")

    # Allow Tk to complete layout and paint before capturing the actual window.
    host.root.after(1200, lambda: capture_and_close(host, output))
    host.root.mainloop()


def capture_and_close(host: PreviewHost, output: Path):
    window = host.exchange_window
    host.root.update_idletasks()
    host.root.update()
    x, y = window.winfo_rootx(), window.winfo_rooty()
    width, height = window.winfo_width(), window.winfo_height()
    if width < 1500 or height < 800:
        raise RuntimeError(f"Unexpected Exchange window size: {width}x{height}")
    image = ImageGrab.grab(bbox=(x, y, x + width, y + height))
    image.save(output, format="PNG")
    if output.stat().st_size < 50_000:
        raise RuntimeError("Captured UI screenshot is unexpectedly small")
    print(f"SCREENSHOT={output.resolve()} SIZE={width}x{height} BYTES={output.stat().st_size}")
    host.close()


if __name__ == "__main__":
    main()
