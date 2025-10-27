# src/lm/data/simulator.py
import pandas as pd
from typing import Optional
from .provider import DataProvider
import random, math
from datetime import datetime, timedelta
import logging
logger = logging.getLogger("LatencyMonitor")
from typing import Optional, Dict, List, Tuple, Any

def simulate_tsla_quotes(n_rows: int = 240, seed: Optional[int] = None) -> pd.DataFrame:
    """
    Columns:
      Time, nombre (TSLA/NVDA/MSFT), Exchange (A-D), counterparty (H/J/K),
      ISIN, b/s, qty, exec price, PnL, TimeDT, inc_t_s
    """
    if seed is not None:
        random.seed(seed)

    exchanges = ["A", "B", "C", "D"]
    cps = ["H", "J", "K"]
    sides = ["buy", "sell"]
    nombres = ["TSLA", "NVDA", "MSFT"]
    now = datetime.now()

    rows: List[Dict[str, Any]] = []
    try:
        for _ in range(max(1, int(n_rows))):
            tdt = now + timedelta(minutes=random.randint(-120, 120), seconds=random.randint(0, 59))
            hhmmss = tdt.strftime("%H:%M:%S")
            nombre = random.choice(nombres)
            ex = random.choice(exchanges)
            cp = random.choice(cps)
            isin = "DE000" + "".join(random.choices("0123456789", k=7))
            side = random.choice(sides)
            qty = random.choice([50, 100, 200, 500, 800, 1200])
            exec_price = round(280 + random.random() * 45, 2)
            pnl = random.randint(-1000, 100)*0.15

            rows.append({
                "Time": hhmmss,
                "nombre": nombre,
                "Exchange": ex,
                "counterparty": cp,
                "ISIN": isin,
                "b/s": side,
                "qty": int(qty),
                "exec price": float(exec_price),
                "PnL": float(pnl),
                "TimeDT": tdt,
            })

        df = pd.DataFrame(rows)
        df = df.sort_values(["nombre", "TimeDT"]).reset_index(drop=True)
        df["inc_t_s"] = df.groupby("nombre")["TimeDT"].diff().dt.total_seconds().fillna(0.0)
        return df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    except Exception:
        logger.exception("simulate_tsla_quotes failed")
        cols = ["Time","nombre","Exchange","counterparty","ISIN","b/s","qty","exec price","PnL","TimeDT","inc_t_s"]
        return pd.DataFrame(columns=cols)
class SimulatedProvider(DataProvider):
    def __init__(self, n_rows: int = 260, seed: Optional[int] = None):
        self.n_rows, self.seed = n_rows, seed
    def fetch(self) -> pd.DataFrame:
        return simulate_tsla_quotes(self.n_rows, seed=self.seed)
