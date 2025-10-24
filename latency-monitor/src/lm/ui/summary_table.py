import tkinter as tk
from tkinter import ttk
import logging
from typing import List, Dict, Any, Optional
logger = logging.getLogger("LatencyMonitor")
from typing import Optional, Dict, List, Tuple, Any

class SummaryTable(ttk.Frame):
    def __init__(self, master, columns: List[str], col_weights: Optional[Dict[str, float]] = None,
                 min_col_widths: Optional[Dict[str, int]] = None, row_height: int = 28,
                 header_height: int = 30, bg: str = "white", **kwargs):
        super().__init__(master, **kwargs)
        self.columns = list(columns)
        self.col_weights = col_weights or {c: 1.0 for c in self.columns}
        self.min_col_widths = min_col_widths or {c: 120 for c in self.columns}
        self.row_h = int(row_height); self.header_h = int(header_height); self.bg = str(bg)

        self.canvas = tk.Canvas(self, highlightthickness=0, bg=self.bg)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1); self.grid_columnconfigure(0, weight=1)

        self.rows: List[List[Any]] = []
        self.col_widths_px: Dict[str, int] = {c: self.min_col_widths.get(c, 120) for c in self.columns}

        self._bind_scroll()
        self.canvas.bind("<Configure>", self._on_resize)

    def _bind_scroll(self):
        def _on_mousewheel(event):
            try: direction = -1 if event.delta > 0 else 1
            except Exception: direction = 1
            self.canvas.yview_scroll(direction, "units")
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def set_rows(self, rows: List[List[Any]]):
        if not isinstance(rows, list):
            logger.warning("SummaryTable.set_rows type error"); return
        self.rows = rows; self._render()

    def _on_resize(self, event):
        try:
            total_weight = sum(float(self.col_weights.get(c, 1.0)) for c in self.columns)
            avail = max(int(event.width) - 2, 200)
            min_total = sum(int(self.min_col_widths.get(c, 80)) for c in self.columns)
            extra = max(avail - min_total, 0)
            for c in self.columns:
                wmin = int(self.min_col_widths.get(c, 80))
                wshare = int(round(extra * (float(self.col_weights.get(c, 1.0)) / total_weight)))
                self.col_widths_px[c] = max(50, wmin + wshare)
            self._render()
        except Exception:
            logger.exception("SummaryTable resize failed")

    def _draw_rich_text(self, x_left: int, y_mid: int, rich_items: List[Tuple[str, str]],
                        font: Tuple[str, int] = ("Segoe UI", 10)) -> int:
        color_map = {"blue":"#2563eb","green":"#059669","red":"#dc2626","muted":"#6b7280","default":"#111111"}
        x = int(x_left)
        for item in rich_items:
            try: text, key = item
            except Exception: text, key = (str(item), "default")
            color = color_map.get(str(key), color_map["default"])
            t = self.canvas.create_text(x, y_mid, anchor="w", text=str(text), fill=color, font=font)
            bbox = self.canvas.bbox(t); x = (bbox[2] + 2) if bbox else (x + 10)
        return x

    def _render(self):
        c = self.canvas
        try:
            c.delete("all")
            total_w = sum(int(self.col_widths_px.get(col, 120)) for col in self.columns)
            total_h = self.header_h + len(self.rows) * self.row_h

            # Header
            x = 0
            for col in self.columns:
                w = int(self.col_widths_px.get(col, 120))
                c.create_rectangle(x, 0, x + w, self.header_h, fill="#111827", outline="#e5e7eb")
                c.create_text(x + 8, self.header_h // 2, anchor="w", text=str(col), fill="white",
                              font=("Segoe UI Semibold", 10))
                x += w

            # Rows
            y = self.header_h
            for i, row in enumerate(self.rows):
                bg = "#fbfdff" if i % 2 == 0 else "#f2f6fb"
                c.create_rectangle(0, y, total_w, y + self.row_h, fill=bg, outline="#e5e7eb")
                x = 0
                for col, val in zip(self.columns, row):
                    w = int(self.col_widths_px.get(col, 120))
                    if isinstance(val, dict) and "rich" in val:
                        self._draw_rich_text(x + 8, y + self.row_h // 2, val.get("rich", []), font=("Segoe UI", 10))
                    else:
                        c.create_text(x + 8, y + self.row_h // 2, anchor="w", text=str(val), fill="#111111",
                                      font=("Segoe UI", 10))
                    x += w
                y += self.row_h

            c.configure(scrollregion=(0, 0, max(total_w, self.winfo_width()), total_h))
        except Exception:
            logger.exception("SummaryTable render failed")