"""Parámetros del backtest. La grilla es chica a propósito: pocos parámetros,
pocos valores por parámetro, para limitar el sobreajuste."""

DESDE = "2021-01-01"          # incluye el ciclo alcista 2021 y el bajista 2022

# Costos por operación (sobre el monto transado, por lado)
COMISION = 0.0040             # taker Kraken tramo bajo — verificar tu tramo
SLIPPAGE = 0.0020             # deslizamiento; en altcoins chicas puede ser más
COSTO_TOTAL = COMISION + SLIPPAGE

# Parámetros fijos
BASE = {
    "salto": 1,               # ignora el último día (evita la reversión de corto plazo)
    "rebalanceo": 7,          # días entre rebalanceos
    "vol_min_usd": 2_000_000, # mediana de volumen diario 30d para ser elegible
    "vol_objetivo": 0.60,     # volatilidad anual objetivo del portafolio (sin apalancamiento)
    "max_peso": 0.30,         # tope por activo
}

# Parámetros a optimizar en walk-forward (3 x 3 x 3 = 27 combinaciones)
GRILLA = {
    "lookback": [14, 28, 56],     # días de momentum
    "top_n": [3, 5, 10],          # activos en cartera
    "sma_regimen": [50, 100, 200],# media de BTC para el filtro de régimen
}

# Walk-forward: optimiza con TRAIN días, prueba en los TEST siguientes
WF_TRAIN = 365
WF_TEST = 90
