"""Tops de libro (bid/ask) y volumen de exchanges extranjeros vía ccxt.
Algunos bloquean servidores de EE.UU. (donde corre GitHub Actions): se registran y se omiten."""
import ccxt


def tickers(exchanges, quotes):
    datos, estado = {}, {}
    for nombre in exchanges:
        try:
            ex = getattr(ccxt, nombre)({"enableRateLimit": True, "timeout": 20000})
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
