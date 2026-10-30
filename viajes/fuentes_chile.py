"""Fuentes chilenas.
- Buda: libro de órdenes CLP (precios ejecutables) y costos de retiro.
- CryptoMKT: solo precio de referencia de su página pública (NO es un precio ejecutable;
  sirve para avisar que vale la pena revisar a mano).
- Orionx: eliminada (anunció cierre definitivo de operaciones en 2026)."""
import time

import requests

T = 20
UA = {"User-Agent": "Mozilla/5.0 (escaner-viajes)"}


def _lv(niveles):
    return [(float(p), float(q)) for p, q in niveles if float(q) > 0]


def buda():
    base = "https://www.buda.com/api/v2"
    mercados = requests.get(f"{base}/markets", timeout=T).json()["markets"]
    libros, retiros = {}, {}
    for m in mercados:
        if m["quote_currency"] != "CLP":
            continue
        mon = m["base_currency"]
        ob = requests.get(f"{base}/markets/{m['id']}/order_book", timeout=T).json()["order_book"]
        libros[mon] = {"bids": sorted(_lv(ob["bids"]), reverse=True), "asks": sorted(_lv(ob["asks"]))}
        try:
            f = requests.get(f"{base}/currencies/{mon}/fees/withdrawal", timeout=T).json()["fee"]
            retiros[mon] = {"fee": float(f["base"][0]), "habilitado": None}
        except Exception:
            pass
        time.sleep(0.2)
    return libros, retiros


def _codigo(item):
    for k in ("symbol", "currency", "code", "base", "asset", "ticker", "name"):
        v = item.get(k)
        if isinstance(v, str) and 2 <= len(v) <= 10:
            return v.upper()
        if isinstance(v, dict):
            for kk in ("symbol", "code"):
                if isinstance(v.get(kk), str):
                    return v[kk].upper()
    return None


def cryptomkt_ref():
    """{MONEDA: precio_referencia_CLP} desde el endpoint de la página pública."""
    url = "https://www.cryptomkt.com/api/v1/landing/market_data/CLP"
    j = requests.get(url, params={"page": 1, "page_size": 100}, headers=UA, timeout=T).json()
    datos = j.get("data", [])
    if datos:
        print(f"[diag] cryptomkt: {len(datos)} activos; claves del primero: {list(datos[0].keys())}")
    refs = {}
    for it in datos:
        cod = _codigo(it)
        precio = (it.get("D1") or {}).get("new_price") or it.get("price")
        if cod and precio:
            refs[cod] = float(precio)
    return refs


def todas():
    libros, retiros, estado, refs = {}, {}, {}, {}
    try:
        libros["buda"], retiros["buda"] = buda()
        estado["buda"] = f"OK ({len(libros['buda'])} mercados CLP)"
    except Exception as e:
        estado["buda"] = f"ERROR: {str(e)[:150]}"
    try:
        refs = cryptomkt_ref()
        estado["cryptomkt (referencia)"] = f"OK ({len(refs)} precios)" if refs else \
            "OK pero sin códigos reconocibles (ver [diag] en el log)"
    except Exception as e:
        estado["cryptomkt (referencia)"] = f"ERROR: {str(e)[:150]}"
    return libros, retiros, estado, refs
