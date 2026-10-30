"""Parámetros del escáner de viajes (comprar en A, transferir, vender en B).
Los valores marcados VERIFICAR son supuestos: confírmalos en cada plataforma."""

# ---------- Chile (CLP) ----------
MONTO_CLP = 500_000            # monto por viaje: define slippage y peso del costo fijo
UMBRAL_NETO_CL = 0.015         # alerta si el ciclo completo deja ≥ 1,5% neto
LECTURAS_MIN = 2               # el spread debe existir en ≥ N lecturas seguidas (15 min c/u)

COMISION_TAKER = {             # VERIFICAR en tu tramo
    "buda": 0.008,
    "cryptomkt": 0.008,        # hay referencias de hasta 1,5% en algunas operaciones
}
RETIRO_CLP = {                 # costo de sacar los pesos al banco — VERIFICAR
    "buda": 2_900,
    "cryptomkt": 3_000,
}
# CryptoMKT entrega solo un precio de referencia: se avisa para revisar a mano
UMBRAL_REF_CRYPTOMKT = 0.03    # diferencia mínima vs el libro de Buda para avisar
# Red preferida para traer USDT de vuelta a Buda — VERIFICAR que Buda la acepte
RED_USDT_PREFERIDA = "TRC20"
# Costo de retiro de cripto (en unidades de la moneda) cuando la API no lo entrega.
# Supuestos conservadores — VERIFICAR la red más barata disponible en cada plataforma.
RETIRO_CRIPTO_DEFAULT = {
    "BTC": 0.0002, "ETH": 0.003, "USDT": 1.0, "USDC": 1.0, "LTC": 0.001,
    "XRP": 0.25, "XLM": 0.1, "TRX": 1.0, "SOL": 0.01, "BCH": 0.001,
    "DOGE": 5.0, "ADA": 1.0, "DOT": 0.1, "MATIC": 1.0, "POL": 1.0,
    "DAI": 1.0, "LINK": 0.1, "UNI": 0.2, "AVAX": 0.05,
}
# Minutos aprox. de traslado (confirmaciones + acreditación). Monedas rápidas = menos riesgo.
TIEMPO_TRASLADO_MIN = {
    "XRP": 2, "XLM": 2, "TRX": 3, "USDT": 5, "SOL": 2, "LTC": 20, "DOGE": 15,
    "ADA": 10, "BCH": 30, "ETH": 10, "USDC": 10, "DAI": 10, "BTC": 60,
    "DOT": 5, "AVAX": 3, "MATIC": 5, "POL": 5, "LINK": 10, "UNI": 10,
}
DESVIO_MAX_SOSPECHOSO = 0.5    # si un precio difiere >50% de la mediana, se descarta (error de datos)

# ---------- Extranjero (monedas de bajo volumen) ----------
EXCHANGES_EXT = ["kraken", "coinbase", "bitstamp", "gemini", "bitfinex", "kucoin",
                 "gate", "okx", "bybit", "mexc", "htx", "bitget"]
QUOTES_EXT = ["USDT", "USD"]
VOL_MIN_USD = 5_000            # bajo esto, no hay con quién transar
VOL_MAX_USD = 2_000_000        # "bajo volumen": al menos un lado bajo este umbral
COMISION_EXT = 0.002           # taker típico — VERIFICAR
UMBRAL_NETO_EXT = 0.02         # neto con comisiones, retiro y profundidad para MONTO_USD
MONTO_USD = 300                # monto por viaje en el extranjero
TOP_PROFUNDIDAD = 25           # candidatos a los que se les revisa el libro completo
