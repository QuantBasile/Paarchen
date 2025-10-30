# popup.py
import tkinter as tk
from tkinter import ttk
import re

def popup_df_simple(root, df, name_col="symbol", isin_col="isin", pnl_col="pnl", ms=8000, title="Aviso"):
    """
    Popup simple con texto plano pero con:
      - name_col en negrita
      - isin_col en azul
      - pnl_col en rojo
    ms: milisegundos para autocerrar (0/None = solo con OK)
    """
    if df is None or df.empty:
        return

    # --- Ventana ---
    w = tk.Toplevel(root)
    w.title(title)
    w.attributes("-topmost", True)
    w.resizable(True, True)

    # --- Frame + scroll ---
    frame = ttk.Frame(w)
    frame.pack(fill="both", expand=True, padx=6, pady=6)
    yscroll = ttk.Scrollbar(frame, orient="vertical")
    text = tk.Text(frame, wrap="none", yscrollcommand=yscroll.set, bg="#f9fafb")
    yscroll.config(command=text.yview)
    yscroll.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)

    # MUY IMPORTANTE: fijar fuente monoespaciada ANTES de insertar
    text.configure(font=("Courier", 10))

    # Forzar columnas con izquierda + espaciado fijo (consistente)
    # col_space>=3 para separar bien; left-just para que el inicio del dato coincida con la cabecera
    txt = df.to_string(index=False, justify="left", col_space=4)
    text.insert("1.0", txt)

    # Tags
    text.tag_configure("name_bold", font=("Courier", 10, "bold"))
    text.tag_configure("isin_blue", foreground="#2563eb")
    text.tag_configure("pnl_red", foreground="#ef4444")

    # Detectar spans de columnas a partir de la cabecera (línea 1)
    lines = txt.splitlines()
    if lines:
        header = lines[0]

        # Encuentra inicios de columnas: cualquier carácter no-espacio cuyo anterior sea espacio o pos 0
        starts = [m.start() for m in re.finditer(r"(^|\s)(\S)", header)]
        starts = [s if header[s] != " " else s+1 for s in starts]  # ajustar al primer no-espacio
        # Ordenar y deduplicar
        starts = sorted(set(starts))
        # Mapear nombre->(start,end)
        # Para robustez, buscamos el índice cuyo texto de cabecera coincide (case-insensitive)
        def col_span(colname):
            if not colname: 
                return None
            name = str(colname)
            # localizar inicio exacto del nombre en la cabecera
            idx = header.lower().find(name.lower())
            if idx < 0:
                return None
            # el final es el siguiente inicio de columna mayor que idx, si existe
            next_starts = [s for s in starts if s > idx]
            end = min(next_starts) if next_starts else len(header)
            return (idx, end)

        spans = {}
        for col, tag in ((name_col, "name_bold"), (isin_col, "isin_blue"), (pnl_col, "pnl_red")):
            s = col_span(col)
            if s:
                spans[tag] = s

        # Aplicar tags a todas las filas de datos (desde la línea 2 en el Text)
        total_lines = len(lines)
        for tag, (start, end) in spans.items():
            for i in range(2, total_lines + 1):
                text.tag_add(tag, f"{i}.{start}", f"{i}.{end}")

    text.configure(state="disabled")

    # Botón cerrar
    ttk.Button(w, text="OK", command=w.destroy).pack(pady=(4, 8))

    # Centrar y autocerrar
    w.update_idletasks()
    ww = min(max(w.winfo_width(), 800), 1200)
    hh = min(max(w.winfo_height(), 300), 800)
    sx, sy = w.winfo_screenwidth(), w.winfo_screenheight()
    w.geometry(f"{ww}x{hh}+{(sx-ww)//2}+{(sy-hh)//5}")
    if ms and ms > 0:
        w.after(ms, w.destroy)
    w.lift()
