from typing import Protocol
import pandas as pd

class DataProvider(Protocol):
    def fetch(self) -> pd.DataFrame: ...
