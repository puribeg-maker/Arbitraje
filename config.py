"""Parámetros del escáner. Todas las comisiones son aproximadas: VERIFÍCALAS
con tu nivel de cuenta real antes de confiar en el spread neto."""

# Alerta si el spread neto supera este umbral (0.008 = 0,8%)
UMBRAL_ALERTA = 0.008
# ...y se mantiene por esta cantidad de lecturas seguidas (filtra ruido)
LECTURAS_CONSECUTIVAS = 2

# Caso 1: USDT/CLP en Buda vs dólar de mercado
USDT_CLP = {
    "mercado_buda": "usdt-clp",
    "comision_buda": 0.008,       # taker fee aprox. — verificar
    "costo_fx": 0.004,            # conseguir/vender USD en banco o casa de cambio
    "costo_transferencia": 0.002, # transferencias / retiro de USDT
}

# Caso 2: PAXG (oro tokenizado) vs oro y entre exchanges
# Ojo: GitHub Actions corre en servidores de EE.UU., donde Binance.com bloquea
# la API. Por eso se usan exchanges accesibles desde EE.UU.
PAXG = {
    "exchanges": {
        "kraken": "PAXG/USD",
        "coinbase": "PAXG/USD",
    },
    "ref_oro": "GC=F",            # futuro de oro COMEX (proxy del spot)
    "comision_trading": 0.004,    # por operación — verificar
    "costo_retiro": 0.001,        # retiro PAXG entre exchanges, como % aprox.
}
