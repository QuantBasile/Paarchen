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
        Reglas:
          - Columnas de porcentaje (como '% Trades PnL+') → siempre con signo y '%'
          - Columnas PnL (importe) → siempre con signo y miles, 1 decimal
          - Enteros (no PnL) → '1,234' (sin signo)
          - Floats (no PnL) → '+/-1,234.5' si quieres signo genérico; aquí los dejamos sin signo salvo PnL
        """
        try:
            # Pasar dict rich sin formatear aquí (se trata por _format_rich_items)
            if isinstance(val, dict):
                return str(val)
    
            # Parseo robusto de cualquier tipo de entrada
            if isinstance(val, (int, float)):
                x = float(val)
            else:
                parsed = self._parse_number_like(str(val))
                if parsed is None:
                    return str(val)
                x = parsed
    
            col_norm = (col or "").lower()
    
            # --- 1) Porcentaje (col de % como '% Trades PnL+') ---
            if ("% trades pnl+" in col_norm) or ("pnl+" in col_norm and "%" in col_norm):
                # Si viene en 0..1, pásalo a %
                if 0.0 <= x <= 1.0:
                    x *= 100.0
                sign = "+" if x >= 0 else "−"
                return f"{sign}{abs(x):,.1f}%"
    
            # --- 2) PnL (importe): SIEMPRE signo y miles, 1 decimal ---
            if ("pnl" in col_norm) and ("pnl+" not in col_norm):
                sign = "+" if x >= 0 else "−"
                return f"{sign}{abs(x):,.1f}"
    
            # --- 3) Resto de columnas ---
            # Entero (sin signo, con miles)
            if abs(x - int(x)) < 1e-9:
                return f"{int(x):,}"
            # Float genérico (no PnL): miles con 1 decimal (sin signo)
            return f"{x:,.1f}"
    
        except Exception:
            return str(val)


   

    def _format_numeric_like(self, col: str, text: str) -> str:
        """
        Igual que _format_value pero partiendo de texto:
          - % Trades PnL+ → siempre con signo y '%'
          - PnL (importe) → siempre con signo y miles, 1 decimal
          - Entero genérico → '1,234' (sin signo)
          - Float genérico → '1,234.5' (sin signo)
        """
        if text is None:
            return ""
        s = str(text).strip()
        if s == "":
            return s
    
        parsed = self._parse_number_like(s)
        if parsed is None:
            return s
    
        x = parsed
        col_norm = (col or "").lower()
    
        # 1) Porcentaje (col tipo '% Trades PnL+')
        if ("% trades pnl+" in col_norm) or ("pnl+" in col_norm and "%" in col_norm) or s.endswith("%"):
            # Si viene 0..1 y SIN '%', pásalo a %
            if not s.endswith("%") and 0.0 <= x <= 1.0:
                x *= 100.0
            sign = "+" if x >= 0 else "−"
            return f"{sign}{abs(x):,.1f}%"
    
        # 2) PnL (importe) → SIEMPRE signo
        if ("pnl" in col_norm) and ("pnl+" not in col_norm):
            sign = "+" if x >= 0 else "−"
            return f"{sign}{abs(x):,.1f}"
    
        # 3) Genérico
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
        base_font = ("Segoe UI", 10)
        big_font = ("Segoe UI Semibold", 12)  
        for text, key in rich_items:
            color = color_map.get(str(key), color_map["default"])
            fnt = big_font if key == "blue" else base_font
            t = c.create_text(x, y_mid, anchor="w", text=str(text), fill=color, font=fnt)
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

class CounterpartyVolumeTable(SummaryTable):
    """
    Tabla especializada para volumen y market share por counterparty.
    Paramétrica en:
      - bucket_col: columna que define el tipo (p.ej. 'nombre' o 'UND_TYPE')
      - main_values: tuplas con los 2 tipos principales (p.ej. ('TSLA','NVDA') o ('KO_CALL','KO_PUT'))
    """

    def __init__(
        self,
        master,
        columns: List[str],
        bucket_col: str,
        main_values: Tuple[str, str],
        col_weights: Optional[Dict[str, float]] = None,
        min_col_widths: Optional[Dict[str, int]] = None,
        row_height: int = 28,
        header_height: int = 30,
        bg: str = "white",
        **kwargs
    ):
        super().__init__(
            master,
            columns=columns,
            col_weights=col_weights,
            min_col_widths=min_col_widths,
            row_height=row_height,
            header_height=header_height,
            bg=bg,
            **kwargs,
        )
        self.bucket_col = bucket_col
        # guardamos también versiones upper para el match
        self.main_values = tuple(main_values)
        self.main_values_upper = tuple(v.upper() for v in main_values)

    def update_from_df(self, df):
        try:
            needed = {"counterparty", self.bucket_col, "qty", "exec price"}
            if df is None or df.empty or not needed.issubset(df.columns):
                self.set_rows([])
                return

            import pandas as pd

            df = df.copy()
            df["qty"] = pd.to_numeric(df["qty"], errors="coerce").abs()
            df["exec price"] = pd.to_numeric(df["exec price"], errors="coerce").abs()
            df = df.dropna(subset=["qty", "exec price"])
            if df.empty:
                self.set_rows([])
                return

            # volumen en dinero
            df["vol"] = df["qty"] * df["exec price"]

            # buckets a partir de bucket_col
            vals_upper = df[self.bucket_col].astype(str).str.upper()
            main1, main2 = self.main_values
            main1_u, main2_u = self.main_values_upper

            df["bucket"] = "Other"
            df.loc[vals_upper == main1_u, "bucket"] = main1
            df.loc[vals_upper == main2_u, "bucket"] = main2

            # agrupar
            g = (
                df.groupby(["counterparty", "bucket"])["vol"]
                  .sum()
                  .unstack("bucket", fill_value=0.0)
            )

            # asegurar columnas
            for c in [main1, main2, "Other"]:
                if c not in g.columns:
                    g[c] = 0.0

            g["total"] = g[main1] + g[main2] + g["Other"]

            # total global (para Marktanteil Total)
            total_global = g["total"].sum() if g["total"].sum() > 0 else 1.0

            # ordenar por volumen total
            g = g.sort_values("total", ascending=False)

            def fmt_vol(x: float) -> str:
                return f"{x:,.0f}"

            def fmt_pct(x: float) -> str:
                return f"{x*100:.1f}%"

            rows: List[List[Any]] = []
            for cp, r in g.iterrows():
                tot = float(r["total"])
                if tot <= 0:
                    continue

                vol1 = float(r[main1])
                vol2 = float(r[main2])
                vol_other = float(r["Other"])

                pct1 = vol1 / tot
                pct2 = vol2 / tot
                pct_other = vol_other / tot

                pct_total = tot / total_global  # share de ese CP vs total global

                # Orden de columnas:
                # [Counterparty,
                #  Vol main1, Marktanteil main1,
                #  Vol main2, Marktanteil main2,
                #  Vol Other, Marktanteil Other,
                #  Marktanteil Total]
                rows.append([
                    cp,
                    fmt_vol(vol1),    fmt_pct(pct1),
                    fmt_vol(vol2),    fmt_pct(pct2),
                    fmt_vol(vol_other), fmt_pct(pct_other),
                    fmt_pct(pct_total),
                ])

            self.set_rows(rows)

        except Exception:
            logger.exception("CounterpartyVolumeTable.update_from_df failed")
            self.set_rows([])
