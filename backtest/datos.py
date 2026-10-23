"""Universo = pares en USD listados hoy en Kraken.
Historia diaria = Yahoo Finance (la API pública de Kraken solo entrega 720 velas)."""
import os

import pandas as pd
import requests
import yfinance as yf

KRAKEN = "https://api.kraken.com/0/public"
ALIAS = {"XBT": "BTC", "XDG": "DOGE"}
EXCLUIR = {  # stablecoins, oro tokenizado y monedas fiat
    "USDT", "USDC", "DAI", "PYUSD", "TUSD", "USDS", "USDG", "USDE", "RLUSD",
    "FDUSD", "EURT", "EURC", "PAXG", "XAUT", "EUR", "GBP", "AUD", "CAD", "CHF",
}
CACHE = "cache"


def universo_kraken():
    pares = requests.get(f"{KRAKEN}/AssetPairs", timeout=30).json()["result"]
    ticks = requests.get(f"{KRAKEN}/Ticker", timeout=30).json()["result"]
    univ = {}
    for clave, p in pares.items():
        ws = p.get("wsname", "")
        if not ws.endswith("/USD") or clave.endswith(".d") or clave not in ticks:
            continue
        base = ALIAS.get(ws.split("/")[0], ws.split("/")[0])
        if base in EXCLUIR:
            continue
        t = ticks[clave]
        univ[base] = {"precio": float(t["c"][0]),
                      "vol_24h_usd": float(t["v"][1]) * float(t["p"][1])}
    return univ


def descargar(desde, refrescar=False):
    """Devuelve (close, volumen_usd) como DataFrames anchos (fecha x activo)."""
    os.makedirs(CACHE, exist_ok=True)
    f_close, f_vol = f"{CACHE}/close.csv", f"{CACHE}/volumen.csv"
    if not refrescar and os.path.exists(f_close):
        return (pd.read_csv(f_close, index_col=0, parse_dates=True),
                pd.read_csv(f_vol, index_col=0, parse_dates=True))

    univ = universo_kraken()
    print(f"Kraken: {len(univ)} activos en USD")
    tickers = [f"{b}-USD" for b in univ]
    raw = yf.download(tickers, start=desde, interval="1d", group_by="ticker",
                      auto_adjust=False, progress=False, threads=True)
    close, vol, descartados = {}, {}, []
    for b in univ:
        t = f"{b}-USD"
        if t not in raw.columns.get_level_values(0):
            descartados.append(b); continue
        c = raw[t]["Close"].dropna()
        if len(c) < 120:
            descartados.append(b); continue
        # Validación: Yahoo a veces usa el mismo ticker para otro token.
        # Se descarta si su último precio difiere >10% del de Kraken.
        if abs(c.iloc[-1] / univ[b]["precio"] - 1) > 0.10:
            descartados.append(b); continue
        close[b] = raw[t]["Close"]
        vol[b] = raw[t]["Volume"]  # en Yahoo, volumen de cripto viene en USD
    close, vol = pd.DataFrame(close), pd.DataFrame(vol)
    print(f"Con historia válida: {close.shape[1]} | descartados: {len(descartados)}")
    close.to_csv(f_close); vol.to_csv(f_vol)
    return close, vol


def limpiar(close, ret_max, ret_min):
    """Elimina precios no positivos y saltos diarios imposibles (errores de Yahoo).
    El precio del día anómalo se deja vacío, lo que corta ese retorno."""
    close = close.where(close > 0)
    ret = close.pct_change(fill_method=None)
    malos = (ret > ret_max) | (ret < ret_min)
    print(f"Limpieza: {int(malos.sum().sum())} precios anómalos eliminados "
          f"en {int(malos.any().sum())} activos")
    return close.mask(malos)
