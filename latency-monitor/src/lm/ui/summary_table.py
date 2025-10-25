import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional, Tuple
import logging
import re

logger = logging.getLogger(__name__)


class SummaryTable(ttk.Frame):
    def __init__(self, master, columns: List[str],
                 col_weights: Optional[Dict[str, float]] = None,
                 min_col_widths: Optional[Dict[str, int]] = None,
                 row_height: int = 28,
                 header_height: int = 30,
                 bg: str = "white",
                 **kwargs):
        super().__init__(master, **kwargs)

        self.columns = columns
        self.col_weights = col_weights or {}
        self.min_col_widths = min_col_widths or {}
        self.row_h = row_height
        self.header_h = header_height
        self.bg = bg
        self.rows: List[List[Any]] = []

        # --- Header fijo + body con scroll
        self.header = tk.Canvas(self, highlightthickness=0, height=self.header_h, bg="#111827")
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=self.bg)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)

        self.header.grid(row=0, column=0, sticky="ew")
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.vsb.grid(row=1, column=1, sticky="ns")

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Column widths in pixels
        self.col_widths_px: Dict[str, int] = {}

        self._bind_scroll()
        self.canvas.bind("<Configure>", self._on_resize)
        self.header.bind("<Configure>", lambda e: self.header.configure(
            scrollregion=(0, 0, e.width, self.header_h))
        )

    # --------------------------------------------------------------
    def _bind_scroll(self):
        def _on_mousewheel(event):
            try:
                direction = -1 if event.delta > 0 else 1
            except Exception:
                direction = 1
            self.canvas.yview_scroll(direction, "units")

        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    # --------------------------------------------------------------
    def _on_resize(self, event):
        """Adjust column widths when resized."""
        try:
            total_weight = sum(self.col_weights.get(col, 1.0) for col in self.columns)
            width = event.width
            for col in self.columns:
                rel = self.col_weights.get(col, 1.0) / total_weight
                min_w = self.min_col_widths.get(col, 80)
                self.col_widths_px[col] = max(int(width * rel), min_w)
            self._render()
        except Exception:
            logger.exception("SummaryTable resize failed")

    # --------------------------------------------------------------
    def set_rows(self, rows: List[List[Any]]):
        """Set the table’s data and redraw."""
        if not isinstance(rows, list):
            logger.warning("SummaryTable.set_rows type error")
            return
        self.rows = rows
        self._render()

    # ===================== PARSING & FORMATEO =====================

    _re_space_like = re.compile(r"[\u00A0\u2007\u202F\s]")  # NBSP y espacios finos

    @staticmethod
    def _normalize_minus(s: str) -> str:
        """Convierte signos de menos unicode a ASCII '-'."""
        return s.replace("\u2212", "-").replace("−", "-").replace("‒", "-").replace("–", "-").replace("—", "-")

    def _parse_number_like(self, s: str) -> Optional[float]:
        """
        Intenta parsear 's' como número robusto:
          - Acepta '-' unicode, '+'.
          - Acepta formato contable: (123) => -123.
          - Ignora separadores de miles, '€', y espacios finos.
          - Si tiene '%', lo quita y devuelve el valor en las mismas unidades (no /100).
        Devuelve float o None si no parece número.
        """
        if s is None:
            return None
        if not isinstance(s, str):
            try:
                return float(s)
            except Exception:
                return None

        s0 = s.strip()
        if s0 == "":
            return None

        # Quitar espacios especiales y normalizar menos
        s0 = self._re_space_like.sub("", s0)
        s0 = self._normalize_minus(s0)

        # Contable: (123.4) -> -123.4
        is_paren_negative = s0.startswith("(") and s0.endswith(")")
        if is_paren_negative:
            s0 = s0[1:-1]

        # Quitar moneda y otros símbolos comunes
        s0 = s0.replace("€", "").replace("$", "").replace("£", "")

        # Quitar porcentaje si lo hay (lo tratamos fuera)
        has_pct = s0.endswith("%")
        if has_pct:
            s0 = s0[:-1]

        # Quitar separadores de miles (coma o punto cuando corresponde)
        # Asumimos entrada tipo 1,234,567.89 o 1.234.567,89 -> simplificamos a quitar comas
        s0 = s0.replace(",", "")

        # Ahora debería ser algo tipo "-1234.56" o "1234.56"
        try:
            x = float(s0)
        except Exception:
            return None

        if is_paren_negative:
            x = -abs(x)

        # No reinterpretamos porcentajes aquí (eso se hace en formateo de %)
        return x

    def _format_value(self, col: str, val: Any) -> str:
        """
        Formatea por columna:
          - Trades → '1,234'
          - PnL / PnL medio → '1,234.5'
          - % Trades PnL+ → '53.2%' (si llega como 0.532 -> 53.2%)
          - Δt medio (s) → '1,234'
        """
        try:
            col_norm = (col or "").lower()

            # Dict rich: no formatear aquí; se tratará en _format_rich_items
            if isinstance(val, dict):
                return str(val)

            # Intentar parseo robusto
            if isinstance(val, (int, float)):
                x = float(val)
            else:
                parsed = self._parse_number_like(str(val))
                if parsed is None:
                    return str(val)
                x = parsed

            # Porcentaje
            if "% trades pnl+" in col_norm or "pnl+" in col_norm:
                # Si es 0..1 -> pásalo a %
                if 0.0 <= x <= 1.0:
                    x *= 100.0
                return f"{x:,.1f}%"

            # Δt (s)
            if "Δt" in col or "dt" in col_norm or "(s" in col_norm:
                return f"{x:,.0f}"

            # Trades (entero con miles)
            if "trade" in col_norm:
                return f"{int(round(x)):,}"

            # PnL columns
            if "pnl" in col_norm:
                return f"{x:,.1f}"

            # Fallback numérico: miles; 1 decimal si no entero
            if abs(x - int(x)) < 1e-9:
                return f"{int(x):,}"
            return f"{x:,.1f}"
        except Exception:
            return str(val)

    def _format_numeric_like(self, col: str, text: str) -> str:
        """
        Aplica formateo numérico incluso si llega como texto con símbolos,
        preservando % si lo trae.
        """
        if text is None:
            return ""
        s = str(text).strip()
        if s == "":
            return s

        # ¿termina en %? -> interpretamos como porcentaje ya expresado
        has_pct = s.endswith("%")
        parsed = self._parse_number_like(s)
        if parsed is None:
            # No parece número, devolver tal cual
            return s

        col_norm = (col or "").lower()
        x = parsed

        if has_pct or ("% trades pnl+" in col_norm or "pnl+" in col_norm):
            # Si viene sin % pero la columna es de porcentaje: 0..1 -> %
            if not has_pct and 0.0 <= x <= 1.0:
                x *= 100.0
            return f"{x:,.1f}%"

        if "Δt" in col or "dt" in col_norm or "(s" in col_norm:
            return f"{x:,.0f}"
        if "trade" in col_norm:
            return f"{int(round(x)):,}"
        if "pnl" in col_norm:
            return f"{x:,.1f}"

        if abs(x - int(x)) < 1e-9:
            return f"{int(x):,}"
        return f"{x:,.1f}"

    def _format_rich_items(self, col: str, rich_items: List) -> List[Tuple[str, str]]:
        """
        Aplica formateo numérico a cada chunk de rich preservando su color.
        Maneja negativos con unicode minus y paréntesis.
        """
        out: List[Tuple[str, str]] = []
        for item in rich_items:
            try:
                text, key = item
            except Exception:
                text, key = (str(item), "default")
            out.append((self._format_numeric_like(col, text), str(key)))
        return out

    # ===================== DIBUJO =====================

    def _measure_rich_width(self, c: tk.Canvas, x_start: int, y_mid: int,
                            rich_items: List[Tuple[str, str]],
                            font: Tuple[str, int]) -> int:
        """Mide ancho total de una secuencia rich (temporalmente crea y borra)."""
        x = int(x_start)
        tmp_ids = []
        for text, _key in rich_items:
            t = c.create_text(x, y_mid, anchor="w", text=str(text), font=font)
            bbox = c.bbox(t)
            x = (bbox[2] + 2) if bbox else (x + 10)
            tmp_ids.append(t)
        total = max(0, x - x_start)
        for t in tmp_ids:
            c.delete(t)
        return total

    def _draw_rich_text_centered(self, c: tk.Canvas, x_left: int, y_mid: int, width: int,
                                 rich_items: List[Tuple[str, str]],
                                 font: Tuple[str, int] = ("Segoe UI", 10)):
        """Dibuja rich centrado dentro de la celda."""
        color_map = {
            "blue": "#2563eb",
            "green": "#059669",
            "red": "#dc2626",
            "muted": "#6b7280",
            "default": "#111111"
        }
        total_w = self._measure_rich_width(c, 0, y_mid, rich_items, font)
        start_x = x_left + max(0, (width - total_w) // 2)

        x = int(start_x)
        for text, key in rich_items:
            color = color_map.get(str(key), color_map["default"])
            t = c.create_text(x, y_mid, anchor="w", text=str(text), fill=color, font=font)
            bbox = c.bbox(t)
            x = (bbox[2] + 2) if bbox else (x + 10)

    # --------------------------------------------------------------
    def _render(self):
        """Render both header and body."""
        c_body = self.canvas
        c_head = self.header
        try:
            c_head.delete("all")
            c_body.delete("all")

            total_w = sum(int(self.col_widths_px.get(col, 120)) for col in self.columns)
            total_h_rows = len(self.rows) * self.row_h

            # --- HEADER (fixed, centered)
            x = 0
            for col in self.columns:
                w = int(self.col_widths_px.get(col, 120))
                c_head.create_rectangle(x, 0, x + w, self.header_h,
                                        fill="#111827", outline="#e5e7eb")
                c_head.create_text(x + w // 2, self.header_h // 2,
                                   anchor="center", text=str(col), fill="white",
                                   font=("Segoe UI Semibold", 10))
                x += w

            # --- ROWS (scrollable, centered)
            y = 0
            for i, row in enumerate(self.rows):
                bg = "#fbfdff" if i % 2 == 0 else "#f2f6fb"
                c_body.create_rectangle(0, y, total_w, y + self.row_h,
                                        fill=bg, outline="#e5e7eb")
                x = 0
                for col, val in zip(self.columns, row):
                    w = int(self.col_widths_px.get(col, 120))
                    cx = x + w // 2  # centro de la celda

                    if isinstance(val, dict) and "rich" in val:
                        rich_fmt = self._format_rich_items(col, val.get("rich", []))
                        self._draw_rich_text_centered(c_body, x, y + self.row_h // 2, w,
                                                      rich_fmt, font=("Segoe UI", 10))
                    else:
                        formatted = self._format_value(col, val)
                        c_body.create_text(cx, y + self.row_h // 2,
                                           anchor="center", text=formatted,
                                           fill="#111111", font=("Segoe UI", 10))
                    x += w
                y += self.row_h

            # scrollregion only for the body
            c_body.configure(scrollregion=(0, 0, max(total_w, self.winfo_width()), total_h_rows))
            c_head.configure(scrollregion=(0, 0, max(total_w, self.winfo_width()), self.header_h))

        except Exception:
            logger.exception("SummaryTable render failed")
