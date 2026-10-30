"""Exchanges extranjeros vía ccxt: tops de libro, estado de redes y profundidad.
Algunos bloquean servidores de EE.UU. (donde corre GitHub Actions): se registran y se omiten."""
import ccxt

_instancias = {}


def instancia(nombre):
    if nombre not in _instancias:
        _instancias[nombre] = getattr(ccxt, nombre)({"enableRateLimit": True, "timeout": 20000})
    return _instancias[nombre]


def tickers(exchanges, quotes):
    datos, estado = {}, {}
    for nombre in exchanges:
        try:
            ex = instancia(nombre)
            ex.load_markets()
            simbolos = [s for s, m in ex.markets.items()
                        if m.get("spot") and m.get("active") is not False and m.get("quote") in quotes]
            tk = ex.fetch_tickers()
            n = 0
            for s in simbolos:
                t = tk.get(s)
                if not t or not t.get("bid") or not t.get("ask"):
                    continue
                vol = t.get("quoteVolume") or (t.get("baseVolume") or 0) * (t.get("last") or 0)
                datos.setdefault(s, {})[nombre] = {"bid": float(t["bid"]), "ask": float(t["ask"]),
                                                   "vol": float(vol or 0)}
                n += 1
            estado[nombre] = f"OK ({n} pares)"
        except Exception as e:
            estado[nombre] = f"ERROR: {type(e).__name__}: {str(e)[:120]}"
    return datos, estado


def redes(nombres):
    """Por exchange: {MONEDA: {"retiro": {red: fee}, "deposito": {red}}} o None si no es público."""
    out, estado = {}, {}
    for nombre in nombres:
        try:
            cur = instancia(nombre).fetch_currencies() or {}
            mapa = {}
            for cod, c in cur.items():
                nets = c.get("networks") or {}
                ret = {str(k).upper(): (n.get("fee") if n.get("fee") is not None else c.get("fee"))
                       for k, n in nets.items() if n.get("withdraw") is not False}
                dep = {str(k).upper() for k, n in nets.items() if n.get("deposit") is not False}
                if not nets:   # sin detalle por red: se usa el estado general
                    ret = {"*": c.get("fee")} if c.get("withdraw") is not False else {}
                    dep = {"*"} if c.get("deposit") is not False else set()
                mapa[cod] = {"retiro": ret, "deposito": dep}
            out[nombre] = mapa
            estado[nombre] = f"redes OK ({len(mapa)} monedas)"
        except Exception as e:
            out[nombre] = None
            estado[nombre] = f"redes no públicas ({type(e).__name__})"
    return out, estado


def libro(nombre, simbolo, limite=50):
    ob = instancia(nombre).fetch_order_book(simbolo, limite)
    return ([(float(p), float(q)) for p, q, *_ in ob["bids"]],
            [(float(p), float(q)) for p, q, *_ in ob["asks"]])
