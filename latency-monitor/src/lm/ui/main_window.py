import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import logging, os, json, math
from datetime import datetime

from lm.utils.numbers import safe_float, safe_int, signed_text
from lm.utils.debounce import Debouncer
from lm.ui.summary_table import SummaryTable
from lm.data.provider import DataProvider

import sys
from typing import Optional, Dict, List, Tuple, Any
from logging.handlers import RotatingFileHandler

# --- Python version check ---
_MIN_PY = (3, 9)
if sys.version_info < _MIN_PY:
    raise RuntimeError(f"Python {_MIN_PY[0]}.{_MIN_PY[1]}+ required, got {sys.version.split()[0]}")

# --- Logging setup ---
LOG_LEVEL = os.getenv("LAT_MON_LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LAT_MON_LOG_FILE", "latency_monitor.log")
logger = logging.getLogger("LatencyMonitor")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG))
if not logger.handlers:
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    ch = logging.StreamHandler(stream=sys.stdout); ch.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG)); ch.setFormatter(fmt)
    fh = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG)); fh.setFormatter(fmt)
    logger.addHandler(ch); logger.addHandler(fh)

# --- Deps ---
try:
    import pandas as pd
    from pandas.api.types import is_numeric_dtype
except Exception:
    logger.exception("pandas import failed"); raise

# matplotlib es opcional
MATPLOTLIB_OK = False
try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MATPLOTLIB_OK = True
except Exception:
    logger.warning("matplotlib not available; charts disabled.")


class TradesApp(tk.Tk):
    DISPLAY_COLS = ["Time","nombre","Exchange","counterparty","ISIN","b/s","qty","exec price","PnL","inc_t_s"]

    def __init__(self, provider: DataProvider, refresh_ms: int = 5000, settings_path: str | None = None):
        super().__init__()
        self.provider = provider
        
        self._ui_ready = False  # <-- evita redibujar antes de tener widgets
        self.title("Market Maker — Live Latency Monitor")
        self.geometry("1780x1050")
        self._auto_size_once = True
        self._header_signature = None   # (tuple(columns), tuple(widths))


        # --- Settings file path ---
        self.settings_path = settings_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

        self.PALETTE = {
            "bg":"#f5f7fb","panel":"#ffffff","panel2":"#f0f3f9","heading_bg":"#111827","heading_fg":"#ffffff",
            "row_even":"#fbfdff","row_odd":"#f2f6fb","hl":"#fff3c4",
            "kpi_pos":"#e6f6ee","kpi_neg":"#fde8e8","kpi_neu":"#eef2ff",
            "kpi_pos_txt":"#047857","kpi_neg_txt":"#b91c1c","kpi_neu_txt":"#1e3a8a",
        }
        try: self.configure(bg=self.PALETTE["bg"])
        except Exception: pass

        style = ttk.Style(self)
        try: style.theme_use("clam")
        except Exception: logger.warning("Could not use 'clam' theme")

        default_font=("Segoe UI",11); header_font=("Segoe UI Semibold",11)
        try:
            style.configure("Treeview", background=self.PALETTE["panel"], foreground="#111111",
                            rowheight=28, fieldbackground=self.PALETTE["panel"], font=default_font, borderwidth=0)
            style.configure("Treeview.Heading", background=self.PALETTE["heading_bg"], foreground=self.PALETTE["heading_fg"],
                            font=header_font, relief="flat")
            style.map("Treeview", background=[("selected","#cfe8ff")], foreground=[("selected","#111111")])
            style.configure("TButton", font=("Segoe UI",10,"bold"), padding=(10,6))
            style.configure("TNotebook", background=self.PALETTE["bg"], borderwidth=0)
            style.configure("TNotebook.Tab", padding=(14,6), font=("Segoe UI",10,"bold"))
            style.configure("TCombobox", padding=4, fieldbackground="#ffffff")
            style.configure("TEntry", padding=4)
            style.configure("Card.TFrame", background=self.PALETTE["panel"])
            style.configure("Soft.TFrame", background=self.PALETTE["panel2"])
            style.configure("Root.TFrame", background=self.PALETTE["bg"])
        except Exception:
            logger.exception("ttk style config failed")

        # ---------- STATE ----------
        df = self.provider.fetch()
        expected = set(self.DISPLAY_COLS + ["TimeDT"])
        for c in expected:
            if c not in df.columns:
                logger.warning("Missing column %s in initial df; creating empty.", c)
                df[c] = []
        self.df_all = df.copy()
        self.df_filtered = df.copy()

        # Tk variables (vinculadas a settings)
        self.refresh_ms = tk.IntVar(value=int(refresh_ms))
        self.running = tk.BooleanVar(value=True)
        self.sort_state_main: Dict[str, bool] = {}
        # Debounce config
        self._debouncer = Debouncer(self)
        self._filter_debounce_ms = 200  # ajusta en settings si quieres

        self.hl_qty = tk.StringVar(value="800")
        self.hl_pnl = tk.StringVar(value="0")

        self.bis_var  = tk.StringVar(value="")     # NEW: BIS variable editable

        # Intenta cargar settings del JSON (si existe)
        self._load_settings_startup()

        # ---------- UI ----------
        banner = ttk.Frame(self, style="Soft.TFrame"); banner.pack(fill=tk.X, padx=16, pady=(12,8))
        ttk.Label(banner, text="Live Latency Monitor", font=("Segoe UI Semibold",16)).pack(side=tk.LEFT)
        ttk.Label(banner, text="Open-end KOs — Detección de capturas por latencia", foreground="#555").pack(side=tk.LEFT, padx=12)

        top_area = ttk.Panedwindow(self, orient=tk.HORIZONTAL); top_area.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
        self.left_frame = ttk.Frame(top_area, style="Root.TFrame"); top_area.add(self.left_frame, weight=3)
        self.right_frame = ttk.Frame(top_area, style="Root.TFrame"); top_area.add(self.right_frame, weight=2)

        # Controls
        ctrl_card = ttk.Frame(self.left_frame, style="Card.TFrame"); ctrl_card.pack(fill=tk.X, padx=4, pady=(0,8))
        ttk.Label(ctrl_card, text="Refresh (ms):").pack(side=tk.LEFT, padx=(10,6))
        self.refresh_entry = ttk.Entry(ctrl_card, width=8, textvariable=self.refresh_ms); self.refresh_entry.pack(side=tk.LEFT, padx=(0,10))
        self.btn_freeze = ttk.Button(ctrl_card, text="⏸ Freeze", command=self.toggle_run); self.btn_freeze.pack(side=tk.LEFT, padx=4)

        # NEW: BIS control
        ttk.Label(ctrl_card, text="BIS:").pack(side=tk.LEFT, padx=(16,6))
        self.bis_entry = ttk.Entry(ctrl_card, width=12, textvariable=self.bis_var)
        self.bis_entry.pack(side=tk.LEFT, padx=(0,10))

        ttk.Button(ctrl_card, text="Load Settings", command=self.load_settings_dialog).pack(side=tk.RIGHT, padx=6)
        ttk.Button(ctrl_card, text="Save Settings", command=self.save_settings_dialog).pack(side=tk.RIGHT, padx=6)
        ttk.Button(ctrl_card, text="⬇ Export CSV", command=self.export_csv).pack(side=tk.RIGHT, padx=10)
        ttk.Button(ctrl_card, text="Clear All Filters", command=self.clear_all_dynamic_filters).pack(side=tk.RIGHT, padx=6)

        # Highlight
        hl_card = ttk.Frame(self.left_frame, style="Card.TFrame"); hl_card.pack(fill=tk.X, padx=4, pady=(0,8))
        ttk.Label(hl_card, text="Highlight if:  qty >", font=("Segoe UI",10,"bold")).pack(side=tk.LEFT, padx=(10,4))
        e_hl_qty = ttk.Entry(hl_card, width=8, textvariable=self.hl_qty)
        e_hl_qty.pack(side=tk.LEFT, padx=(0,12)); e_hl_qty.bind("<Return>", lambda e: self.update_all_views()); e_hl_qty.bind("<FocusOut>", lambda e: self.update_all_views())
        ttk.Label(hl_card, text="AND   PnL >", font=("Segoe UI",10,"bold")).pack(side=tk.LEFT, padx=(6,4))
        e_hl_pnl = ttk.Entry(hl_card, width=8, textvariable=self.hl_pnl)
        e_hl_pnl.pack(side=tk.LEFT, padx=(0,12)); e_hl_pnl.bind("<Return>", lambda e: self.update_all_views()); e_hl_pnl.bind("<FocusOut>", lambda e: self.update_all_views())
        ttk.Label(hl_card, text="(Only rows meeting both are highlighted)", foreground="#666").pack(side=tk.LEFT, padx=(8,0))

        # Dynamic filters
        filters_card = ttk.Frame(self.left_frame, style="Card.TFrame"); filters_card.pack(fill=tk.X, padx=4, pady=(0,8))
        self.filters_frame = ttk.Frame(filters_card, style="Card.TFrame"); self.filters_frame.pack(fill=tk.X, padx=8, pady=8)
        self.dynamic_filters: Dict[str, Dict[str, Any]] = {}
        self.skip_filter_cols = {"Time", "TimeDT"}
        self.build_dynamic_filters(self.df_all)

        # Main table
        table_card = ttk.Frame(self.left_frame, style="Card.TFrame"); table_card.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0,8))
        self.tree = ttk.Treeview(table_card, columns=self.DISPLAY_COLS, show="headings")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        for col in self.DISPLAY_COLS:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_main_by(c))
            self.tree.column(col, width=120, anchor="center")
        vsb = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=vsb.set); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.tag_configure("ROW_EVEN", background=self.PALETTE["row_even"])
        self.tree.tag_configure("ROW_ODD", background=self.PALETTE["row_odd"])
        self.tree.tag_configure("HL", background=self.PALETTE["hl"])

        # KPIs
        kpi_card = ttk.Frame(self.left_frame, style="Root.TFrame"); kpi_card.pack(fill=tk.X, padx=4, pady=(0,6))
        self.kpi_total = tk.Label(kpi_card, text="", font=("Segoe UI Semibold",11),
                                  bg=self.PALETTE["kpi_neu"], fg=self.PALETTE["kpi_neu_txt"], padx=12, pady=6)
        self.kpi_pos = tk.Label(kpi_card, text="", font=("Segoe UI",11),
                                bg=self.PALETTE["kpi_pos"], fg=self.PALETTE["kpi_pos_txt"], padx=12, pady=6)
        self.kpi_neg = tk.Label(kpi_card, text="", font=("Segoe UI",11),
                                bg=self.PALETTE["kpi_neg"], fg=self.PALETTE["kpi_neg_txt"], padx=12, pady=6)
        self.kpi_neg.pack(side=tk.RIGHT, padx=(8,10)); self.kpi_pos.pack(side=tk.RIGHT, padx=8); self.kpi_total.pack(side=tk.RIGHT, padx=8)

        # Right controls & charts
        right_ctrl = ttk.Frame(self.right_frame, style="Card.TFrame"); right_ctrl.pack(fill=tk.X, padx=4, pady=(0,8))
        charts_nb = ttk.Notebook(self.right_frame); charts_nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Cumulative PnL
        tab_cum = ttk.Frame(charts_nb, style="Card.TFrame"); charts_nb.add(tab_cum, text="Cumulative PnL (time)")
        self.fig2 = self.ax2 = self.canvas2 = None
        if MATPLOTLIB_OK:
            try:
                self.fig2 = Figure(figsize=(5,3.2), dpi=100); self.ax2 = self.fig2.add_subplot(111)
                self.canvas2 = FigureCanvasTkAgg(self.fig2, master=tab_cum)
                self.canvas2.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
                self._pnl_line = None
            except Exception: logger.exception("fig2 init failed")

        # Cumulative Trades
        tab_trades = ttk.Frame(charts_nb, style="Card.TFrame"); charts_nb.add(tab_trades, text="Cumulative Trades (time)")
        self.fig3 = self.ax3 = self.canvas3 = None
        if MATPLOTLIB_OK:
            try:
                self.fig3 = Figure(figsize=(5,3.2), dpi=100); self.ax3 = self.fig3.add_subplot(111)
                self.canvas3 = FigureCanvasTkAgg(self.fig3, master=tab_trades)
                self.canvas3.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
                self._trades_line = None
            except Exception: logger.exception("fig3 init failed")


        # ----------- Bottom summaries (UNFILTERED) -----------
        bottom_area = ttk.Notebook(self); bottom_area.pack(fill=tk.BOTH, expand=False, padx=12, pady=(0,12), ipady=4)
        self.summary_cols = ["Key","Trades","% Trades PnL+","Δt medio (s)","PnL medio","PnL"]
        col_weights = {"Key":2.2,"Trades":1.7,"% Trades PnL+":1.2,"Δt medio (s)":1.2,"PnL medio":1.2,"PnL":2.0}
        min_col_widths = {"Key":240,"Trades":180,"% Trades PnL+":140,"Δt medio (s)":140,"PnL medio":130,"PnL":200}

        # FIRST: Exchanges
        tab_exch = ttk.Frame(bottom_area, style="Card.TFrame"); bottom_area.add(tab_exch, text="Global — Exchanges")
        self.exch_table = SummaryTable(tab_exch, columns=self.summary_cols, col_weights=col_weights, min_col_widths=min_col_widths, bg="white")
        self.exch_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # ISINs
        tab_isin = ttk.Frame(bottom_area, style="Card.TFrame"); bottom_area.add(tab_isin, text="Global — ISINs")
        self.isin_table = SummaryTable(tab_isin, columns=self.summary_cols, col_weights=col_weights, min_col_widths=min_col_widths, bg="white")
        self.isin_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Nombres
        tab_nombre = ttk.Frame(bottom_area, style="Card.TFrame"); bottom_area.add(tab_nombre, text="Global — Nombres")
        self.nombre_table = SummaryTable(tab_nombre, columns=self.summary_cols, col_weights=col_weights, min_col_widths=min_col_widths, bg="white")
        self.nombre_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Marcar UI como lista y hacer primer render
        self._ui_ready = True
        try:
            self.apply_dynamic_filters()
            self.update_global_summaries()
        except Exception:
            logger.exception("initial render failed")
        
        self.after(self._safe_refresh_ms(), self.refresh_data)


    # ================= SETTINGS (JSON) =================
    def _default_settings(self) -> Dict[str, Any]:
        return {
            "refresh_ms": 3500,
            "hl_qty": "800",
            "hl_pnl": "0",
            "BIS": ""
        }

    def _gather_settings_from_ui(self) -> Dict[str, Any]:
        # Coge valores actuales de la UI (no valida aquí; valida al aplicar)
        s = {
            "refresh_ms": safe_int(str(self.refresh_ms.get()), 3500),
            "hl_qty": str(self.hl_qty.get()).strip(),
            "hl_pnl": str(self.hl_pnl.get()).strip(),
            "BIS": str(self.bis_var.get()).strip(),
        }
        # Coerciones mínimas
        if s["refresh_ms"] is None: s["refresh_ms"] = 3500
        return s

    def _apply_settings_to_ui(self, s: Dict[str, Any]) -> None:
        # Asigna a Tk vars con validaciones suaves
        try:
            self.refresh_ms.set(int(s.get("refresh_ms", 3500)))
        except Exception:
            self.refresh_ms.set(3500)

        self.hl_qty.set(str(s.get("hl_qty", "800")))
        self.hl_pnl.set(str(s.get("hl_pnl", "0")))
        self.bis_var.set(str(s.get("BIS", "")))

        # No redibujar si la UI aún no está lista
        if getattr(self, "_ui_ready", False):
            self.update_all_views()

    def load_settings_dialog(self):
        try:
            path = filedialog.askopenfilename(
                title="Load settings JSON",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                initialfile=os.path.basename(self.settings_path),
                initialdir=os.path.dirname(self.settings_path),
            )
            if not path:
                return
            with open(path, "r", encoding="utf-8") as f:
                s = json.load(f)
            if not isinstance(s, dict):
                raise ValueError("Settings JSON must contain an object at top-level.")
            self._apply_settings_to_ui({**self._default_settings(), **s})
            self.settings_path = path  # recuerda el último path usado
            logger.info("Settings loaded from %s", path)
        except Exception as e:
            logger.exception("load_settings_dialog failed")
            messagebox.showerror("Load Settings", f"Error loading settings:\n{e}")

    def save_settings_dialog(self):
        try:
            s = self._gather_settings_from_ui()
            path = filedialog.asksaveasfilename(
                defaultextension=".json",
                title="Save settings JSON",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                initialfile=os.path.basename(self.settings_path),
                initialdir=os.path.dirname(self.settings_path),
            )
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                json.dump(s, f, indent=2, ensure_ascii=False)
            self.settings_path = path
            logger.info("Settings saved to %s", path)
            messagebox.showinfo("Save Settings", f"Settings saved to:\n{path}")
        except Exception as e:
            logger.exception("save_settings_dialog failed")
            messagebox.showerror("Save Settings", f"Error saving settings:\n{e}")

    def _load_settings_startup(self):
        """Carga settings al inicio desde self.settings_path si existe; si no, usa defaults."""
        try:
            if os.path.isfile(self.settings_path):
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    s = json.load(f)
                if not isinstance(s, dict):
                    logger.warning("Settings file invalid top-level; using defaults.")
                    s = self._default_settings()
            else:
                s = self._default_settings()
            self._apply_settings_to_ui(s)
            logger.info("Settings applied at startup (path=%s exists=%s)", self.settings_path, os.path.isfile(self.settings_path))
        except Exception:
            logger.exception("Failed to load settings at startup")
            self._apply_settings_to_ui(self._default_settings())

    # ============== App features (filters, table, charts, summaries) ==============
    def build_dynamic_filters(self, df: pd.DataFrame):
        prev: Dict[str, Any] = {}
        # Guardar estado previo de los filtros para restaurar selección
        for col, meta in self.dynamic_filters.items():
            try:
                if meta["type"] == "cat":
                    sel = meta["listbox"].curselection()
                    prev[col] = [meta["listbox"].get(i) for i in sel] if sel else ["(All)"]
                else:
                    prev[col] = (meta["min_var"].get(), meta["max_var"].get())
            except Exception:
                prev[col] = None

        for w in self.filters_frame.winfo_children(): w.destroy()
        self.dynamic_filters.clear()

        cidx = 0
        for col in df.columns:
            if col in {"Time","TimeDT"}:
                continue
            try:
                colf = ttk.Frame(self.filters_frame, style="Card.TFrame")
                colf.grid(row=0, column=cidx, padx=6, pady=6, sticky="nw"); cidx += 1
                ttk.Label(colf, text=str(col), font=("Segoe UI Semibold",10)).pack(anchor="w")

                if not is_numeric_dtype(df[col]):
                    values = sorted(map(str, pd.unique(df[col].astype(str))))
                    values = ["(All)"] + values
                    lb = tk.Listbox(colf,
                                    height=min(6, max(1, len(values))),
                                    exportselection=False,
                                    selectmode="extended")
                    for v in values:
                        lb.insert(tk.END, v)
                    lb.pack(anchor="w", fill="x", pady=(2,0))
                    # Restaurar selección previa (lista) o "(All)"
                    to_select_list = prev.get(col, ["(All)"])
                    try_indices = [values.index(v) for v in to_select_list if v in values]
                    if not try_indices:
                        try_indices = [0]
                    lb.selection_clear(0, tk.END)
                    for i in try_indices:
                        lb.selection_set(i)
                    # Debounce en selección
                    lb.bind("<<ListboxSelect>>", lambda e: self._debouncer.schedule(
                        "filters", self._filter_debounce_ms, self.apply_dynamic_filters
                    ))
                    self.dynamic_filters[col] = {"type":"cat","listbox":lb,"values":values}
                 
                else:
                    min_var = tk.StringVar(value=""); max_var = tk.StringVar(value="")
                    row1 = ttk.Frame(colf, style="Card.TFrame"); row1.pack(anchor="w", pady=(2,0))
                    ttk.Label(row1, text="min").pack(side=tk.LEFT)
                    e_min = ttk.Entry(row1, width=8, textvariable=min_var); e_min.pack(side=tk.LEFT, padx=(4,0))
                    row2 = ttk.Frame(colf, style="Card.TFrame"); row2.pack(anchor="w", pady=(2,0))
                    ttk.Label(row2, text="max").pack(side=tk.LEFT)
                    e_max = ttk.Entry(row2, width=8, textvariable=max_var); e_max.pack(side=tk.LEFT, padx=(4,0))
                    if col in prev and isinstance(prev[col], tuple):
                        min_var.set(prev[col][0] or ""); max_var.set(prev[col][1] or "")
                    
                    # Debounce para numeric entries
                    e_min.bind("<KeyRelease>", lambda e: self._debouncer.schedule(
                        "filters", self._filter_debounce_ms, self.apply_dynamic_filters
                    ))
                    e_min.bind("<FocusOut>", lambda e: self._debouncer.schedule(
                        "filters", self._filter_debounce_ms, self.apply_dynamic_filters
                    ))
                    e_max.bind("<KeyRelease>", lambda e: self._debouncer.schedule(
                        "filters", self._filter_debounce_ms, self.apply_dynamic_filters
                    ))
                    e_max.bind("<FocusOut>", lambda e: self._debouncer.schedule(
                        "filters", self._filter_debounce_ms, self.apply_dynamic_filters
                    ))
                    
                    
                    
                    self.dynamic_filters[col] = {"type":"num","min_var":min_var,"max_var":max_var}
            except Exception:
                logger.exception("filter build failed for %s", col)

        for j in range(cidx):
            try: self.filters_frame.grid_columnconfigure(j, weight=1)
            except Exception: pass

    def apply_dynamic_filters(self):
        try:
            df = self.df_all.copy()
            for col, meta in self.dynamic_filters.items():
                if meta["type"] == "cat":
                    sel_idx = meta["listbox"].curselection()
                    if sel_idx:
                        chosen = [meta["listbox"].get(i) for i in sel_idx]
                        # Si "(All)" está seleccionado o la selección queda vacía: no filtra
                        chosen_wo_all = [v for v in chosen if v != "(All)"]
                        if chosen_wo_all:
                            df = df[df[col].astype(str).isin(chosen_wo_all)]
                else:
                    smin = (meta["min_var"].get() or "").strip(); smax = (meta["max_var"].get() or "").strip()
                    vmin = safe_float(smin); vmax = safe_float(smax)
                    if vmin is not None: df = df[df[col] >= vmin]
                    if vmax is not None: df = df[df[col] <= vmax]
            self.df_filtered = df.reset_index(drop=True)
            self.update_all_views()
        except Exception:
            logger.exception("apply_dynamic_filters failed")

    def clear_all_dynamic_filters(self):
        try:
            for col, meta in self.dynamic_filters.items():
                if meta["type"] == "cat":
                    if meta.get("values"):
                        try:
                            idx_all = meta["values"].index("(All)")
                        except Exception:
                            idx_all = 0
                        meta["listbox"].selection_clear(0, tk.END)
                        meta["listbox"].selection_set(idx_all)
                else:
                    meta["min_var"].set(""); meta["max_var"].set("")
            self.df_filtered = self.df_all.copy()
            self.update_all_views()
        except Exception:
            logger.exception("clear filters failed")

    def update_table(self):
        try:
            # Clear fast
            for r in self.tree.get_children():
                self.tree.delete(r)
    
            # thresholds once
            hl_qty = safe_float(self.hl_qty.get(), default=float("inf"))
            hl_pnl = safe_float(self.hl_pnl.get(), default=float("inf"))
    
            dfv = self.df_filtered  # shorthand
            if dfv.empty:
                # also reset KPIs quickly
                self.kpi_total.config(text="PnL Total: 0 (0)")
                self.kpi_pos.config(text="PnL +: +0 (0)")
                self.kpi_neg.config(text="PnL -: 0 (0)")
                return
    
            # Prebuild values row tuples in Python once (fast path)
            cols = self.DISPLAY_COLS
            values_rows = dfv[cols].astype(object).values.tolist()  # no per-cell getattr in the loop
    
            # Insert rows with a single pass (tags computed once per row)
            for i, row_vals in enumerate(values_rows):
                try:
                    qty_v = float(row_vals[cols.index("qty")]) if "qty" in cols else 0.0
                    pnl_v = float(row_vals[cols.index("PnL")]) if "PnL" in cols else -1e18
                    cond_hl = (qty_v > hl_qty) and (pnl_v > hl_pnl)
                except Exception:
                    cond_hl = False
                tags = ("HL",) if cond_hl else (("ROW_EVEN",) if i % 2 == 0 else ("ROW_ODD",))
                self.tree.insert("", "end", values=row_vals, tags=tags)
    
            # Column widths: set a sane default (no O(N) scanning every tick)
            for col in cols:
                try:
                    self.tree.column(col, width=max(90, int(9 * max(len(str(col)), 8))), anchor="center")
                except Exception:
                    pass
    
            # KPIs: compute once
            if "PnL" in dfv.columns:
                pnl = dfv["PnL"]
                total = float(pnl.sum()); n_total = int(len(dfv))
                pos_mask = pnl > 0; neg_mask = pnl < 0
                pos_sum = float(pnl.loc[pos_mask].sum()); n_pos = int(pos_mask.sum())
                neg_sum = float(pnl.loc[neg_mask].sum()); n_neg = int(neg_mask.sum())
            else:
                total = pos_sum = neg_sum = 0.0; n_total = n_pos = n_neg = 0
    
            sign = "+" if total > 0 else ("−" if total < 0 else "")
            # format once here
            self.kpi_total.config(text=f"PnL Total: {sign}{abs(total):,.0f} ({n_total})")
            self.kpi_pos.config(text=f"PnL +: +{pos_sum:,.0f} ({n_pos})")
            self.kpi_neg.config(text=f"PnL -: {neg_sum:,.0f} ({n_neg})")
    
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.exception("update_table failed")


    # ---- BIS accessor (para uso futuro en lógica/funciones) ----
    def get_bis(self) -> str:
        """Devuelve el valor actual de BIS (string). Realiza strip()."""
        try:
            return str(self.bis_var.get()).strip()
        except Exception:
            logger.exception("get_bis failed")
            return ""

    def _reduce_xticks(self, ax, labels: List[str], max_ticks: int = 6):
        try:
            if not labels: return
            n = len(labels)
            if n <= max_ticks:
                ax.set_xticks(range(n)); ax.set_xticklabels(labels, rotation=45, ha="right"); return
            idxs = [0]; mid_needed = max_ticks - 2
            for k in range(1, mid_needed+1): idxs.append(round(k*(n-1)/(mid_needed+1)))
            idxs.append(n-1); idxs = sorted(set(idxs))
            ax.set_xticks(idxs); ax.set_xticklabels([labels[i] for i in idxs], rotation=45, ha="right")
        except Exception:
            logger.exception("reduce_xticks failed")


    def update_cumulative_pnl(self):
        if not (MATPLOTLIB_OK and self.ax2 and self.canvas2):
            return
        try:
            import matplotlib.dates as mdates
            import pandas as pd
    
            # lazy axis init (titles/formatters once)
            if getattr(self, "_ax2_inited", False) is False:
                self.ax2.set_title("Cumulative PnL (1s grouped)")
                self.ax2.set_xlabel("Time")
                self.ax2.set_ylabel("PnL cumulative (€)")
                self.ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                self.ax2.xaxis.set_major_locator(mdates.HourLocator(byhour=[8,10,12,14,16,18,20,22]))
                self.ax2.grid(True, axis="y", alpha=0.2)
                self._ax2_inited = True
    
            # No data? keep axis, just clear the line
            if self.df_filtered.empty or "TimeDT" not in self.df_filtered.columns or "PnL" not in self.df_filtered.columns:
                # set a stable x window for today 08–22
                today = pd.Timestamp.today().normalize()
                start, end = self._day_window_bounds(today)
                self.ax2.set_xlim(start, end)
                if self._pnl_line is None:
                    (self._pnl_line,) = self.ax2.plot([], [], linewidth=2, drawstyle="steps-post")
                self._pnl_line.set_data([], [])
                self.canvas2.draw_idle()
                return
    
            df = self.df_filtered.copy()
            df["TimeDT"] = pd.to_datetime(df["TimeDT"], errors="coerce")
            df["PnL"] = pd.to_numeric(df["PnL"], errors="coerce").fillna(0.0)
            df = df.dropna(subset=["TimeDT"]).sort_values("TimeDT")
            if df.empty:
                today = pd.Timestamp.today().normalize()
                start, end = self._day_window_bounds(today)
                self.ax2.set_xlim(start, end)
                if self._pnl_line is None:
                    (self._pnl_line,) = self.ax2.plot([], [], linewidth=2, drawstyle="steps-post")
                self._pnl_line.set_data([], [])
                self.canvas2.draw_idle()
                return
    
            # Window 08–22 of the day of first trade
            start_day, end_day = self._day_window_bounds(df["TimeDT"].iloc[0])
            df = df[(df["TimeDT"] >= start_day) & (df["TimeDT"] <= end_day)]
            if df.empty:
                self.ax2.set_xlim(start_day, end_day)
                if self._pnl_line is None:
                    (self._pnl_line,) = self.ax2.plot([], [], linewidth=2, drawstyle="steps-post")
                self._pnl_line.set_data([], [])
                self.canvas2.draw_idle()
                return
    
            # 1s grouping via resample
            s = (df.set_index("TimeDT")["PnL"]
                    .resample("1S", origin="start_day").sum()
                    .sort_index())
    
            # Reindex strictly between first & last second with data
            first_sec, last_sec = s.index[0], s.index[-1]
            sec_index = pd.date_range(first_sec, last_sec, freq="1S")
            s = s.reindex(sec_index, fill_value=0.0)
    
            # cumulative series (no clears; reuse the line)
            cum = s.cumsum()
            if self._pnl_line is None:
                (self._pnl_line,) = self.ax2.plot(cum.index, cum.values, linewidth=2, drawstyle="steps-post")
            else:
                self._pnl_line.set_data(cum.index, cum.values)
    
            # Keep x axis fixed 08–22, line only spans [first_sec, last_sec]
            self.ax2.set_xlim(start_day, end_day)
            self.fig2.tight_layout()
            self.canvas2.draw_idle()
    
        except Exception:
            # trimmed logging on hot path
            if logger.isEnabledFor(logging.DEBUG):
                logger.exception("update_cumulative_pnl failed")



    def _day_window_bounds(self, ts: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
        day = ts.normalize()
        start = day.replace(hour=8, minute=0, second=0, microsecond=0)
        end   = day.replace(hour=22, minute=0, second=0, microsecond=0)
        return start, end


    def update_trades_over_time(self):
        if not (MATPLOTLIB_OK and self.ax3 and self.canvas3):
            return
        try:
            import matplotlib.dates as mdates
            import pandas as pd
    
            # lazy axis init once
            if getattr(self, "_ax3_inited", False) is False:
                self.ax3.set_title("Cumulative Trades (time)")
                self.ax3.set_xlabel("Time")
                self.ax3.set_ylabel("Trades (cum)")
                self.ax3.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                self.ax3.xaxis.set_major_locator(mdates.HourLocator(byhour=[8,10,12,14,16,18,20,22]))
                self.ax3.grid(True, axis="y", alpha=0.2)
                self._ax3_inited = True
    
            if self.df_filtered.empty or "TimeDT" not in self.df_filtered.columns:
                today = pd.Timestamp.today().normalize()
                start, end = self._day_window_bounds(today)
                self.ax3.set_xlim(start, end)
                if self._trades_line is None:
                    (self._trades_line,) = self.ax3.plot([], [], linewidth=2, drawstyle="steps-post")
                self._trades_line.set_data([], [])
                self.canvas3.draw_idle()
                return
    
            df = self.df_filtered.copy()
            df["TimeDT"] = pd.to_datetime(df["TimeDT"], errors="coerce")
            df = df.dropna(subset=["TimeDT"]).sort_values("TimeDT")
            if df.empty:
                today = pd.Timestamp.today().normalize()
                start, end = self._day_window_bounds(today)
                self.ax3.set_xlim(start, end)
                if self._trades_line is None:
                    (self._trades_line,) = self.ax3.plot([], [], linewidth=2, drawstyle="steps-post")
                self._trades_line.set_data([], [])
                self.canvas3.draw_idle()
                return
    
            start_day, end_day = self._day_window_bounds(df["TimeDT"].iloc[0])
            df = df[(df["TimeDT"] >= start_day) & (df["TimeDT"] <= end_day)]
            if df.empty:
                self.ax3.set_xlim(start_day, end_day)
                if self._trades_line is None:
                    (self._trades_line,) = self.ax3.plot([], [], linewidth=2, drawstyle="steps-post")
                self._trades_line.set_data([], [])
                self.canvas3.draw_idle()
                return
    
            # 1s counts, then cumulative
            counts = (df.set_index(df["TimeDT"].dt.floor("S"))
                        .sort_index()
                        .groupby(level=0)["TimeDT"].size())
            first_sec, last_sec = counts.index[0], counts.index[-1]
            sec_index = pd.date_range(first_sec, last_sec, freq="1S")
            counts = counts.reindex(sec_index, fill_value=0)
            cum = counts.cumsum()
    
            if self._trades_line is None:
                (self._trades_line,) = self.ax3.plot(cum.index, cum.values, linewidth=2, drawstyle="steps-post")
            else:
                self._trades_line.set_data(cum.index, cum.values)
    
            self.ax3.set_xlim(start_day, end_day)
            self.fig3.tight_layout()
            self.canvas3.draw_idle()
    
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.exception("update_trades_over_time failed")



    def update_time_charts(self):
        self.update_cumulative_pnl(); self.update_trades_over_time()

    # ---- Global summaries (UNFILTERED) ----
    def update_global_summaries(self):
        try:
            def make_summary(df: pd.DataFrame, keycol: str) -> pd.DataFrame:
                if df.empty:
                    return pd.DataFrame(columns=[keycol,"trades","pos_trades","neg_trades","pct_pos","dt_mean","pnl_mean","pnl_total","pnl_pos","pnl_neg"])
                g = df.groupby(keycol).agg(
                    trades=("PnL","size"),
                    pos_trades=("PnL", lambda s: int((s>0).sum())),
                    neg_trades=("PnL", lambda s: int((s<0).sum())),
                    pct_pos=("PnL", lambda s: 100.0 * (s.gt(0).sum()) / max(1, len(s))),
                    dt_mean=("inc_t_s","mean"),
                    pnl_mean=("PnL","mean"),
                    pnl_total=("PnL","sum"),
                    pnl_pos=("PnL", lambda s: float(s[s>0].sum())),
                    pnl_neg=("PnL", lambda s: float(s[s<0].sum())),
                ).reset_index().sort_values("pnl_total", ascending=False)
                return g

            g_ex   = make_summary(self.df_all, "Exchange")
            g_isin = make_summary(self.df_all, "ISIN").head(50)
            g_nom  = make_summary(self.df_all, "nombre")

            def rows_from_df(df: pd.DataFrame, keyname: str) -> List[List[Any]]:
                rows: List[List[Any]] = []
                for _, r in df.iterrows():
                    neg_tr = int(r["neg_trades"])
                    neg_txt = "0" if neg_tr == 0 else f"−{neg_tr}"  # no '−0'
                    trip_trades = {"rich":[
                        (f"{int(r['trades'])}","blue"), (" | ","muted"),
                        (f"+{int(r['pos_trades'])}","green"), (" | ","muted"),
                        (neg_txt,"red"),
                    ]}
                    pnl_total_txt = signed_text(float(r["pnl_total"]))
                    pnl_pos_txt   = f"+{float(r['pnl_pos']):.0f}"
                    pnl_neg_val   = float(r["pnl_neg"])
                    pnl_neg_txt   = "0" if pnl_neg_val == 0 else f"−{abs(pnl_neg_val):.0f}"
                    trip_pnl = {"rich":[
                        (pnl_total_txt,"blue"), (" | ","muted"),
                        (pnl_pos_txt,"green"),  (" | ","muted"),
                        (pnl_neg_txt,"red"),
                    ]}
                    rows.append([
                        r[keyname],
                        trip_trades,
                        f"{float(r['pct_pos']):.1f}%",
                        f"{float(r['dt_mean']):.1f}",
                        f"{float(r['pnl_mean']):.1f}",
                        trip_pnl,
                    ])
                return rows

            self.exch_table.set_rows(rows_from_df(g_ex, "Exchange"))
            self.isin_table.set_rows(rows_from_df(g_isin, "ISIN"))
            self.nombre_table.set_rows(rows_from_df(g_nom, "nombre"))
        except Exception:
            logger.exception("update_global_summaries failed")

    # ---- Sorting / refresh / utils ----
    def sort_main_by(self, col: str):
        try:
            asc = not self.sort_state_main.get(col, True)
            self.sort_state_main[col] = asc
            df = self.df_filtered.copy()
            if col in ("qty","PnL","exec price","inc_t_s"):
                df = df.sort_values(by=col, ascending=asc, kind="mergesort")
            elif col == "Time":
                df = df.sort_values(by="TimeDT", ascending=asc, kind="mergesort")
            else:
                df = df.sort_values(by=col, ascending=asc, kind="mergesort")
            self.df_filtered = df.reset_index(drop=True)
            self.update_all_views()
        except Exception:
            logger.exception("sort_main_by failed for %s", col)

    def update_all_views(self):
        self.update_table(); self.update_cumulative_pnl(); self.update_trades_over_time()


    def refresh_data(self):
        try:
            if self.running.get():
                self.df_all = self.provider.fetch()
                self.apply_dynamic_filters()
                self.update_global_summaries()
        except Exception:
            logger.exception("refresh_data failed")
        finally:
            self.after(self._safe_refresh_ms(), self.refresh_data)

    def _safe_refresh_ms(self) -> int:
        try: ms = int(self.refresh_ms.get())
        except Exception: ms = 5000
        return max(200, min(ms, 30000))

    def toggle_run(self):
        try:
            if self.running.get():
                self.running.set(False); self.btn_freeze.config(text="▶ Resume"); logger.info("Paused")
            else:
                self.running.set(True); self.btn_freeze.config(text="⏸ Freeze"); logger.info("Resumed")
        except Exception:
            logger.exception("toggle_run failed")

    def export_csv(self):
        try:
            if self.df_filtered.empty:
                messagebox.showwarning("Export CSV", "No filtered data to export."); return
            path = filedialog.asksaveasfilename(defaultextension=".csv",
                                                filetypes=[("CSV files","*.csv"),("All files","*.*")],
                                                title="Export filtered view to CSV",
                                                initialfile="trades_filtered.csv")
            if path:
                try:
                    self.df_filtered[self.DISPLAY_COLS].to_csv(path, index=False)
                    messagebox.showinfo("Export CSV", f"Exported to:\n{path}"); logger.info("Exported CSV: %s", path)
                except Exception as e:
                    logger.exception("CSV export failed"); messagebox.showerror("Export CSV", f"Error:\n{e}")
        except Exception:
            logger.exception("export_csv outer failed")


