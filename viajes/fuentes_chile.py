"""Libros de órdenes CLP de Buda, CryptoMKT y Orionx.
Cada fuente devuelve {MONEDA: {"bids": [(p, q)...], "asks": [(p, q)...]}} y
{MONEDA: info_retiro}. Si una fuente falla, se registra y se sigue con las demás."""
import time

import requests

T = 20


def _lv(niveles):
    return [(float(p), float(q)) for p, q in niveles if float(q) > 0]


# ---------- Buda ----------
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


# ---------- CryptoMKT ----------
def cryptomkt():
    base = "https://api.exchange.cryptomkt.com/api/3/public"
    simbolos = requests.get(f"{base}/symbol", timeout=T).json()
    clp = {s: v["base_currency"] for s, v in simbolos.items()
           if v.get("quote_currency") == "CLP" and v.get("type", "spot") == "spot"}
    libros = {}
    if clp:
        obs = requests.get(f"{base}/orderbook", params={"symbols": ",".join(clp), "depth": 50},
                           timeout=T).json()
        for s, ob in obs.items():
            libros[clp[s]] = {"bids": sorted(_lv(ob.get("bid", [])), reverse=True),
                              "asks": sorted(_lv(ob.get("ask", [])))}
    retiros = {}
    try:
        cur = requests.get(f"{base}/currency", timeout=T).json()
        for mon, c in cur.items():
            redes = [n for n in c.get("networks", []) if n.get("payout_enabled")]
            fees = [float(n["payout_fee"]) for n in redes if n.get("payout_fee") not in (None, "")]
            retiros[mon] = {"fee": min(fees) if fees else None,
                            "habilitado": bool(c.get("payout_enabled")),
                            "deposito": bool(c.get("payin_enabled"))}
    except Exception as e:
        print(f"[aviso] cryptomkt currency: {e}")
    return libros, retiros


# ---------- Orionx (GraphQL) ----------
def orionx():
    url = "https://api.orionx.com/graphql"

    def q(query):
        r = requests.post(url, json={"query": query}, timeout=T)
        r.raise_for_status()
        j = r.json()
        if j.get("errors"):
            raise RuntimeError(j["errors"][0].get("message"))
        return j["data"]

    mercados = q("{ markets { code mainCurrency { code units } secondaryCurrency { code units } } }")["markets"]
    libros = {}
    for m in mercados:
        if m["secondaryCurrency"]["code"] != "CLP":
            continue
        mon, u = m["mainCurrency"]["code"], 10 ** (m["mainCurrency"].get("units") or 0)
        ob = q(f'{{ marketOrderBook(marketCode: "{m["code"]}", limit: 50) '
               f'{{ buy {{ limitPrice amount }} sell {{ limitPrice amount }} }} }}')["marketOrderBook"]
        conv = lambda lado: [(float(o["limitPrice"]), float(o["amount"]) / u) for o in lado if o["amount"]]
        libros[mon] = {"bids": sorted(conv(ob["buy"]), reverse=True), "asks": sorted(conv(ob["sell"]))}
        time.sleep(0.2)
    return libros, {}


FUENTES = {"buda": buda, "cryptomkt": cryptomkt, "orionx": orionx}


def todas():
    libros, retiros, estado = {}, {}, {}
    for nombre, f in FUENTES.items():
        try:
            libros[nombre], retiros[nombre] = f()
            estado[nombre] = f"OK ({len(libros[nombre])} mercados CLP)"
        except Exception as e:
            estado[nombre] = f"ERROR: {str(e)[:150]}"
    return libros, retiros, estado
