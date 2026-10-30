"""Escáner de viajes: comprar en A con pesos, transferir la moneda, vender en B.
También observa spreads de monedas de bajo volumen entre exchanges extranjeros.
No ejecuta operaciones: alerta por mail y guarda historial."""
import csv
import itertools
import os
import smtplib
import statistics as st
from datetime import datetime, timezone
from email.message import EmailMessage

import config_viajes as C
import fuentes_chile
import fuentes_extranjero

CSV_PATH = "data/viajes.csv"
CAMPOS = ["timestamp", "tipo", "moneda", "ruta", "neto", "bruto", "ganancia_clp",
          "precio_compra", "precio_venta", "volumen_usd", "nota"]


def miles(x):
    return f"{x:,.0f}".replace(",", ".")


# ---------- Chile: ciclo completo con profundidad ----------
def comprar(asks, monto):
    qty, gastado = 0.0, 0.0
    for p, q in asks:
        costo = p * q
        if gastado + costo >= monto:
            qty += (monto - gastado) / p
            return qty
        qty += q
        gastado += costo
    return None                                   # no alcanza la profundidad


def vender(bids, qty):
    clp, resto = 0.0, qty
    for p, q in bids:
        tomar = min(q, resto)
        clp += tomar * p
        resto -= tomar
        if resto <= 1e-12:
            return clp
    return None


def fee_retiro(retiros, ex, mon):
    info = retiros.get(ex, {}).get(mon, {})
    if info.get("fee") is not None:
        return info["fee"], "api"
    if mon in C.RETIRO_CRIPTO_DEFAULT:
        return C.RETIRO_CRIPTO_DEFAULT[mon], "supuesto"
    return None, "desconocido"


def precios_sospechosos(libros, mon):
    """Descarta plataformas cuyo precio se aleja demasiado de la mediana (unidades mal leídas
    o un token distinto con el mismo código)."""
    mids = {ex: (lb[mon]["bids"][0][0] + lb[mon]["asks"][0][0]) / 2
            for ex, lb in libros.items() if mon in lb and lb[mon]["bids"] and lb[mon]["asks"]}
    if len(mids) < 2:
        return set(), mids
    med = st.median(mids.values())
    return {ex for ex, m in mids.items() if abs(m / med - 1) > C.DESVIO_MAX_SOSPECHOSO}, mids


def escanear_chile(libros, retiros, ahora):
    filas = []
    monedas = set().union(*[set(lb) for lb in libros.values()]) if libros else set()
    for mon in sorted(monedas):
        malos, _ = precios_sospechosos(libros, mon)
        exs = [e for e in libros if mon in libros[e] and e not in malos]
        for a, b in itertools.permutations(exs, 2):
            la, lb = libros[a][mon], libros[b][mon]
            if not la["asks"] or not lb["bids"]:
                continue
            bruto = lb["bids"][0][0] / la["asks"][0][0] - 1
            if bruto <= 0:
                continue                           # ni siquiera el mejor precio cruza
            ret, origen_fee = fee_retiro(retiros, a, mon)
            notas = []
            ia, ib = retiros.get(a, {}).get(mon, {}), retiros.get(b, {}).get(mon, {})
            if ia.get("habilitado") is False:
                notas.append(f"retiros de {mon} deshabilitados en {a}")
            if ib.get("deposito") is False:
                notas.append(f"depósitos de {mon} deshabilitados en {b}")
            if ret is None:
                notas.append("costo de retiro desconocido")
                ret = 0.0
            elif origen_fee == "supuesto":
                notas.append("costo de retiro supuesto")

            qty = comprar(la["asks"], C.MONTO_CLP)
            if qty is None:
                notas.append(f"profundidad insuficiente para comprar ${miles(C.MONTO_CLP)} en {a}")
                neto, gan = None, None
            else:
                qty = qty * (1 - C.COMISION_TAKER[a]) - ret
                clp = vender(lb["bids"], qty) if qty > 0 else None
                if clp is None:
                    notas.append(f"profundidad insuficiente para vender en {b}")
                    neto, gan = None, None
                else:
                    clp = clp * (1 - C.COMISION_TAKER[b]) - C.RETIRO_CLP[b]
                    neto, gan = clp / C.MONTO_CLP - 1, clp - C.MONTO_CLP
            filas.append({"timestamp": ahora, "tipo": "chile", "moneda": mon,
                          "ruta": f"{a}->{b}", "neto": "" if neto is None else round(neto, 5),
                          "bruto": round(bruto, 5),
                          "ganancia_clp": "" if gan is None else round(gan),
                          "precio_compra": la["asks"][0][0], "precio_venta": lb["bids"][0][0],
                          "volumen_usd": "", "nota": "; ".join(notas)})
    return filas


# ---------- Extranjero: monedas de bajo volumen ----------
def escanear_extranjero(datos, ahora):
    filas = []
    for simbolo, por_ex in datos.items():
        if len(por_ex) < 2:
            continue
        vols = [v["vol"] for v in por_ex.values()]
        if min(vols) > C.VOL_MAX_USD:
            continue                               # no es de bajo volumen en ningún lado
        validos = {e: v for e, v in por_ex.items() if v["vol"] >= C.VOL_MIN_USD}
        if len(validos) < 2:
            continue
        a = min(validos, key=lambda e: validos[e]["ask"])
        b = max(validos, key=lambda e: validos[e]["bid"])
        if a == b:
            continue
        bruto = validos[b]["bid"] / validos[a]["ask"] - 1
        if bruto > 1.0 or bruto <= 0:              # >100% suele ser otro token con el mismo ticker
            continue
        neto = bruto - 2 * C.COMISION_EXT
        filas.append({"timestamp": ahora, "tipo": "extranjero", "moneda": simbolo,
                      "ruta": f"{a}->{b}", "neto": round(neto, 5), "bruto": round(bruto, 5),
                      "ganancia_clp": "", "precio_compra": validos[a]["ask"],
                      "precio_venta": validos[b]["bid"],
                      "volumen_usd": round(min(validos[a]["vol"], validos[b]["vol"])),
                      "nota": "sin costo de retiro ni profundidad; verificar depósitos/retiros"})
    return filas


# ---------- Historial, persistencia y alertas ----------
def leer_historial(max_filas=20_000):
    """Solo las últimas filas: basta para medir persistencia."""
    if not os.path.exists(CSV_PATH):
        return []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))[-max_filas:]


def guardar(filas):
    nuevo = not os.path.exists(CSV_PATH)
    os.makedirs("data", exist_ok=True)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        if nuevo:
            w.writeheader()
        w.writerows(filas)


def umbral(f):
    return C.UMBRAL_NETO_CL if f["tipo"] == "chile" else C.UMBRAL_NETO_EXT


def sobre_umbral(f):
    return f["neto"] != "" and float(f["neto"]) >= umbral(f)


def lecturas_seguidas(historial, f):
    """Cuántas lecturas anteriores consecutivas (incluida la actual) tuvo esta ruta sobre el umbral."""
    marcas = sorted({h["timestamp"] for h in historial if h["tipo"] == "lectura"}, reverse=True)
    sobre = {h["timestamp"] for h in historial
             if h["tipo"] == f["tipo"] and h["moneda"] == f["moneda"] and h["ruta"] == f["ruta"]
             and sobre_umbral(h)}
    n = 1
    for t in marcas:
        if t in sobre:
            n += 1
        else:
            break
    return n


def texto_alerta(f, n):
    a, b = f["ruta"].split("->")
    dur = f"{n} lecturas seguidas (~{(n - 1) * 15} min)" if n > 1 else "primera lectura"
    if f["tipo"] == "chile":
        t = C.TIEMPO_TRASLADO_MIN.get(f["moneda"])
        traslado = f"~{t} min" if t else "desconocido"
        return (f"• {f['moneda']}: comprar en {a} a ${miles(f['precio_compra'])} → transferir "
                f"(traslado {traslado}) → vender en {b} a ${miles(f['precio_venta'])}\n"
                f"  Con ${miles(C.MONTO_CLP)}: neto {float(f['neto']):.2%} "
                f"(≈ ${miles(float(f['ganancia_clp']))}). Spread visto: {dur}."
                + (f"\n  Ojo: {f['nota']}" if f["nota"] else ""))
    return (f"• {f['moneda']}: comprar en {a} a {f['precio_compra']} → vender en {b} a "
            f"{f['precio_venta']}. Neto aprox. {float(f['neto']):.2%} | volumen 24h "
            f"del lado más chico: US${miles(float(f['volumen_usd']))}. Spread visto: {dur}.\n"
            f"  Ojo: {f['nota']}")


def enviar_mail(asunto, texto):
    usuario, clave = os.getenv("GMAIL_USER"), os.getenv("GMAIL_APP_PASSWORD")
    if not usuario or not clave:
        print("[info] Sin credenciales de Gmail; alerta solo en el log.")
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = asunto, usuario, os.getenv("MAIL_TO") or usuario
    msg.set_content(texto)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(usuario, clave)
        s.send_message(msg)


def resumen(estado, filas):
    lineas = ["### Fuentes", "| Fuente | Estado |", "|---|---|"]
    lineas += [f"| {k} | {v} |" for k, v in estado.items()]
    top = sorted([f for f in filas if f["neto"] != ""], key=lambda f: float(f["neto"]), reverse=True)[:15]
    lineas += ["", "### Mejores rutas de esta lectura", "| Tipo | Moneda | Ruta | Bruto | Neto | Nota |",
               "|---|---|---|---:|---:|---|"]
    lineas += [f"| {f['tipo']} | {f['moneda']} | {f['ruta']} | {float(f['bruto']):.2%} | "
               f"{float(f['neto']):.2%} | {f['nota']} |" for f in top]
    txt = "\n".join(lineas)
    print(txt)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.getenv("GITHUB_STEP_SUMMARY"), "a", encoding="utf-8") as fh:
            fh.write(txt + "\n")


def main():
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    historial = leer_historial()

    libros, retiros, est_cl = fuentes_chile.todas()
    datos_ext, est_ext = fuentes_extranjero.tickers(C.EXCHANGES_EXT, C.QUOTES_EXT)
    filas = escanear_chile(libros, retiros, ahora) + escanear_extranjero(datos_ext, ahora)
    resumen({**est_cl, **est_ext}, filas)

    alertas = []
    for f in filas:
        if not sobre_umbral(f):
            continue
        if f["tipo"] == "chile" and "deshabilitados" in f["nota"]:
            continue
        n = lecturas_seguidas(historial, f)
        if n >= C.LECTURAS_MIN:
            alertas.append((f, n))
    if alertas:
        alertas.sort(key=lambda x: (x[0]["tipo"] != "chile", -float(x[0]["neto"])))
        cuerpo = "\n\n".join(texto_alerta(f, n) for f, n in alertas)
        cuerpo += ("\n\nAntes de operar: confirma en ambas plataformas que la red de retiro y la de "
                   "depósito coincidan, que no haya retiros suspendidos y que el precio siga ahí.")
        f0 = alertas[0][0]
        enviar_mail(f"🚚 Viaje: {f0['moneda']} {f0['ruta']} neto {float(f0['neto']):.1%}", cuerpo)

    # Para no inflar el CSV: todas las rutas chilenas con bruto > 0, y en el extranjero solo
    # las que superan la mitad del umbral. Una fila "lectura" marca cada corrida.
    guardar_filas = [f for f in filas if f["tipo"] == "chile"
                     or float(f["neto"]) >= C.UMBRAL_NETO_EXT / 2]
    guardar_filas.append({k: "" for k in CAMPOS} | {"timestamp": ahora, "tipo": "lectura"})
    guardar(guardar_filas)


if __name__ == "__main__":
    main()
