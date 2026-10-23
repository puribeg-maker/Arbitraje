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
          "spread_bruto", "spread_neto"]


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


def buda_bid_ask(mercado):
    r = requests.get(f"https://www.buda.com/api/v2/markets/{mercado}/ticker",
                     timeout=15)
    r.raise_for_status()
    t = r.json()["ticker"]
    return float(t["max_bid"][0]), float(t["min_ask"][0])


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
    bid, ask = buda_bid_ask(c["mercado_buda"])

    filas = []
    # USDT caro en Chile: traer USD -> USDT -> vender en Buda
    bruto = bid / ref - 1
    filas.append(fila(ahora, "USDT/CLP", f"vender USDT en Buda vs {fuente}",
                      bid, ref, bruto, bruto - costos))
    # USDT barato en Chile: comprar en Buda -> sacar a USD
    bruto = ref / ask - 1
    filas.append(fila(ahora, "USDT/CLP", f"comprar USDT en Buda vs {fuente}",
                      ask, ref, bruto, bruto - costos))
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

def fila(ahora, caso, detalle, precio, ref, bruto, neto):
    return {"timestamp": ahora, "caso": caso, "detalle": detalle,
            "precio": round(precio, 4), "referencia": round(ref, 4),
            "spread_bruto": round(bruto, 5), "spread_neto": round(neto, 5)}


def leer_historial():
    if not os.path.exists(CSV_PATH):
        return []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def guardar(filas):
    nuevo = not os.path.exists(CSV_PATH)
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
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


def resumen_markdown(filas):
    """Tabla visible en la pestaña Actions de GitHub."""
    ruta = os.getenv("GITHUB_STEP_SUMMARY")
    lineas = ["| Caso | Detalle | Bruto | Neto |", "|---|---|---:|---:|"]
    for f in filas:
        marca = " 🔔" if f["spread_neto"] >= config.UMBRAL_ALERTA else ""
        lineas.append(f"| {f['caso']} | {f['detalle']} | "
                      f"{f['spread_bruto']:.2%} | {f['spread_neto']:.2%}{marca} |")
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
               if f["spread_neto"] >= config.UMBRAL_ALERTA and persiste(historial, f)]
    if alertas:
        cuerpo = "Spreads sobre umbral:\n\n" + "\n".join(
            f"• {f['caso']} | {f['detalle']}: neto {f['spread_neto']:.2%} "
            f"(bruto {f['spread_bruto']:.2%}, precio {f['precio']}, ref {f['referencia']})"
            for f in alertas) + f"\n\nLectura: {ahora}"
        mejor = max(alertas, key=lambda f: f["spread_neto"])
        enviar_mail(f"🔔 Arbitraje: {mejor['caso']} neto {mejor['spread_neto']:.2%}", cuerpo)
    guardar(filas)


if __name__ == "__main__":
    main()
