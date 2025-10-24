# src/lm/data/my_source.py
import pandas as pd

def my_fetch(bis: int | None) -> pd.DataFrame:
    # Ejemplo de uso del parámetro BIS
    # Si bis es None o 0, carga todo; si es un número, filtra por algo
    df = pd.read_csv("data/trades.csv")

    if bis:
        df = df[df["Quantity"] > bis]  # solo ejemplo de filtro usando BIS

    # Asegúrate de devolver las mismas columnas que el simulador
    return df
