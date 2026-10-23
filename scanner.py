"""Escáner de spreads: USDT/CLP vs dólar y PAXG vs oro.
No ejecuta operaciones: registra lecturas y alerta por mail (Gmail)."""
import csv
import itertools
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import ccxt
import requests
import yfinance as yf

import config

CSV_PATH = "data/spreads.csv"
CAMPOS = ["timestamp", "caso", "detalle", "precio", "referencia",
          "spread_bruto", "spread_neto", "volumen_usdt", "neto_promedio"]


# ---------- Fuentes de datos ----------

def dolar_referencia():
    """USD/CLP intradía desde Yahoo; si falla, dólar observado (diario)."""
    try:
        h = yf.Ticker("CLP=X").history(period="1d", interval="5m")
        if not h.empty:
            return float(h["Close"].iloc[-1]), "Yahoo CLP=X"
    except Exception as e:
        print(f"[aviso] Yahoo CLP=X falló: {e}")
    r = requests.get("https://mindicador.cl/api/dolar", timeout=15)
    r.raise_for_status()
    return float(r.json()["serie"][0]["valor"]), "dólar observado (diario)"


def buda_libro(mercado):
    """Libro de órdenes de Buda: listas de (precio, cantidad), mejor precio primero."""
    r = requests.get(f"https://www.buda.com/api/v2/markets/{mercado}/order_book",
                     timeout=15)
    r.raise_for_status()
    libro = r.json()["order_book"]
    bids = sorted(((float(p), float(q)) for p, q in libro["bids"]), reverse=True)
    asks = sorted((float(p), float(q)) for p, q in libro["asks"])
    return bids, asks


def capturable(niveles, ref, costos, venta):
    """Recorre el libro mientras cada nivel deje un neto >= umbral.
    Devuelve (volumen en USDT, neto promedio ponderado de ese volumen)."""
    volumen, suma_neto = 0.0, 0.0
    for precio, cantidad in niveles:
        bruto = precio / ref - 1 if venta else ref / precio - 1
        neto = bruto - costos
        if neto < config.UMBRAL_ALERTA:
            break
        volumen += cantidad
        suma_neto += neto * cantidad
    return volumen, (suma_neto / volumen if volumen else None)


def precio_oro(ticker):
    h = yf.Ticker(ticker).history(period="1d", interval="5m")
    if h.empty:
        h = yf.Ticker(ticker).history(period="5d")
    return float(h["Close"].iloc[-1])


def ticker_exchange(nombre, simbolo):
    ex = getattr(ccxt, nombre)({"enableRateLimit": True})
    t = ex.fetch_ticker(simbolo)
    return float(t["bid"]), float(t["ask"])


# ---------- Casos ----------

def caso_usdt_clp(ahora):
    c = config.USDT_CLP
    costos = c["comision_buda"] + c["costo_fx"] + c["costo_transferencia"]
    ref, fuente = dolar_referencia()
    bids, asks = buda_libro(c["mercado_buda"])
    bid, ask = bids[0][0], asks[0][0]

    filas = []
    # USDT caro en Chile: vender inventario de USDT en Buda (se recorren los bids)
    bruto = bid / ref - 1
    vol, neto_prom = capturable(bids, ref, costos, venta=True)
    filas.append(fila(ahora, "USDT/CLP", f"vender USDT en Buda vs {fuente}",
                      bid, ref, bruto, bruto - costos, vol, neto_prom))
    # USDT barato en Chile: comprar en Buda (se recorren los asks)
    bruto = ref / ask - 1
    vol, neto_prom = capturable(asks, ref, costos, venta=False)
    filas.append(fila(ahora, "USDT/CLP", f"comprar USDT en Buda vs {fuente}",
                      ask, ref, bruto, bruto - costos, vol, neto_prom))
    return filas


def caso_paxg(ahora):
    c = config.PAXG
    oro = precio_oro(c["ref_oro"])
    precios = {}
    for nombre, simbolo in c["exchanges"].items():
        try:
            precios[nombre] = ticker_exchange(nombre, simbolo)
        except Exception as e:
            print(f"[aviso] {nombre} falló: {e}")

    filas = []
    # Premio/descuento vs oro (señal: realizarlo exige cubrirse en futuros)
    for nombre, (bid, ask) in precios.items():
        bruto = bid / oro - 1
        filas.append(fila(ahora, "PAXG", f"premio {nombre} vs oro",
                          bid, oro, bruto, bruto - c["comision_trading"]))
        bruto = oro / ask - 1
        filas.append(fila(ahora, "PAXG", f"descuento {nombre} vs oro",
                          ask, oro, bruto, bruto - c["comision_trading"]))

    # Entre exchanges: comprar en A, transferir, vender en B
    costos = 2 * c["comision_trading"] + c["costo_retiro"]
    for a, b in itertools.permutations(precios, 2):
        ask_a, bid_b = precios[a][1], precios[b][0]
        bruto = bid_b / ask_a - 1
        filas.append(fila(ahora, "PAXG", f"comprar {a} -> vender {b}",
                          bid_b, ask_a, bruto, bruto - costos))
    return filas


# ---------- Utilidades ----------

def fila(ahora, caso, detalle, precio, ref, bruto, neto,
         volumen=None, neto_prom=None):
    return {"timestamp": ahora, "caso": caso, "detalle": detalle,
            "precio": round(precio, 4), "referencia": round(ref, 4),
            "spread_bruto": round(bruto, 5), "spread_neto": round(neto, 5),
            "volumen_usdt": "" if volumen is None else round(volumen, 2),
            "neto_promedio": "" if neto_prom is None else round(neto_prom, 5)}


def leer_historial():
    if not os.path.exists(CSV_PATH):
        return []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def guardar(filas):
    nuevo = not os.path.exists(CSV_PATH)
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    if not nuevo:
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            if r.fieldnames != CAMPOS:   # CSV antiguo: se migra a las columnas nuevas
                antiguas = list(r)
                with open(CSV_PATH, "w", newline="", encoding="utf-8") as g:
                    w = csv.DictWriter(g, fieldnames=CAMPOS, restval="")
                    w.writeheader()
                    w.writerows({k: v for k, v in a.items() if k in CAMPOS}
                                for a in antiguas)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        if nuevo:
            w.writeheader()
        w.writerows(filas)


def persiste(historial, f_actual):
    """True si las N-1 lecturas previas del mismo par también superaron el umbral."""
    n = config.LECTURAS_CONSECUTIVAS - 1
    if n <= 0:
        return True
    previas = [h for h in historial
               if h["caso"] == f_actual["caso"] and h["detalle"] == f_actual["detalle"]][-n:]
    return len(previas) == n and all(
        float(h["spread_neto"]) >= config.UMBRAL_ALERTA for h in previas)


def enviar_mail(asunto, texto):
    usuario = os.getenv("GMAIL_USER")
    clave = os.getenv("GMAIL_APP_PASSWORD")
    destino = os.getenv("MAIL_TO") or usuario
    if not usuario or not clave:
        print("[info] Sin credenciales de Gmail; alerta solo en el log.")
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = asunto, usuario, destino
    msg.set_content(texto)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(usuario, clave)
        s.send_message(msg)
    print(f"[info] Alerta enviada a {destino}")


def miles(x):
    """Formato chileno: 3.500 / 3.437.000"""
    return f"{x:,.0f}".replace(",", ".")


def es_alerta(f):
    """Spread neto sobre umbral y, si hay libro de órdenes, volumen suficiente."""
    if f["spread_neto"] < config.UMBRAL_ALERTA:
        return False
    return f["volumen_usdt"] == "" or f["volumen_usdt"] >= config.VOLUMEN_MINIMO_USDT


def detalle_volumen(f):
    if f["volumen_usdt"] == "":
        return ""
    clp = f["volumen_usdt"] * f["precio"]
    return (f"\n   Volumen capturable: {miles(f['volumen_usdt'])} USDT (~${miles(clp)} CLP), "
            f"neto promedio {f['neto_promedio']:.2%}")


def resumen_markdown(filas):
    """Tabla visible en la pestaña Actions de GitHub."""
    ruta = os.getenv("GITHUB_STEP_SUMMARY")
    lineas = ["| Caso | Detalle | Bruto | Neto | Vol. capturable (USDT) |",
              "|---|---|---:|---:|---:|"]
    for f in filas:
        marca = " 🔔" if es_alerta(f) else ""
        vol = "" if f["volumen_usdt"] == "" else miles(f["volumen_usdt"])
        lineas.append(f"| {f['caso']} | {f['detalle']} | "
                      f"{f['spread_bruto']:.2%} | {f['spread_neto']:.2%}{marca} | {vol} |")
    texto = "\n".join(lineas)
    print(texto)
    if ruta:
        with open(ruta, "a", encoding="utf-8") as fh:
            fh.write(texto + "\n")


def main():
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    historial = leer_historial()
    filas = []
    for caso in (caso_usdt_clp, caso_paxg):
        try:
            filas += caso(ahora)
        except Exception as e:
            print(f"[error] {caso.__name__}: {e}")

    if not filas:
        print("Sin lecturas.")
        return

    resumen_markdown(filas)
    alertas = [f for f in filas
               if es_alerta(f) and persiste(historial, f)]
    if alertas:
        cuerpo = "Spreads sobre umbral:\n\n" + "\n".join(
            f"• {f['caso']} | {f['detalle']}: neto {f['spread_neto']:.2%} "
            f"(bruto {f['spread_bruto']:.2%}, precio {f['precio']}, ref {f['referencia']})"
            + detalle_volumen(f)
            for f in alertas) + f"\n\nLectura: {ahora}"
        mejor = max(alertas, key=lambda f: f["spread_neto"])
        enviar_mail(f"🔔 Arbitraje: {mejor['caso']} neto {mejor['spread_neto']:.2%}", cuerpo)
    guardar(filas)


if __name__ == "__main__":
    main()
