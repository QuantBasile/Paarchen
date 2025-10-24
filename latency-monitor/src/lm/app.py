import logging
from lm.ui.main_window import TradesApp
from lm.data.simulator import SimulatedProvider

logger = logging.getLogger("LatencyMonitor")

def run():
    app = TradesApp(provider=SimulatedProvider(n_rows=260), refresh_ms=3500)
    app.mainloop()
