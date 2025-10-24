import logging
from lm.ui.main_window import TradesApp
from lm.data.simulator import SimulatedProvider

logger = logging.getLogger("LatencyMonitor")

def run():
    app = TradesApp(provider=SimulatedProvider(n_rows=260), refresh_ms=3500)
    app.mainloop()


# src/lm/app.py
# from lm.ui.main_window import TradesApp
# from lm.data.my_source import my_fetch
# from lm.utils.numbers import safe_int  # ya tienes esta función

# class RealProvider:
#     def __init__(self, app_ref):
#         self.app_ref = app_ref  # para leer el valor del Entry BIS

#     def fetch(self):
#         # Lee el texto del Entry y lo convierte a entero (o None si vacío)
#         bis_value = safe_int(self.app_ref.BIS_var.get())
#         return my_fetch(bis_value)
# def run():
#     app = TradesApp(provider=None, refresh_ms=3500)
#     app.provider = RealProvider(app)
#     app.mainloop()
