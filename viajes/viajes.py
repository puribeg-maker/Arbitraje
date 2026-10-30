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
def red_comun(info_redes, a, b, base):
    """Devuelve (fee_retiro_en_moneda, nota) o (None, motivo_descartar)."""
    ra, rb = info_redes.get(a), info_redes.get(b)
    if ra is None or rb is None:
        return 0.0, "estado de redes desconocido"
    ca, cb = ra.get(base), rb.get(base)
    if not ca or not cb:
        return None, "moneda sin datos de red"
    if not ca["retiro"]:
        return None, f"retiros cerrados en {a}"
    if not cb["deposito"]:
        return None, f"depósitos cerrados en {b}"
    if "*" in ca["retiro"] or "*" in cb["deposito"]:
        comunes = set(ca["retiro"])
    else:
        comunes = set(ca["retiro"]) & cb["deposito"]
    if not comunes:
        return None, "sin red común (posible token distinto con el mismo ticker)"
    fees = [ca["retiro"][n] for n in comunes if ca["retiro"].get(n) is not None]
    return (min(fees) if fees else 0.0), ("" if fees else "fee de retiro desconocido")


def ciclo_usd(asks_a, bids_b, monto, fee_ret):
    qty = comprar(asks_a, monto)
    if qty is None:
        return None
    qty = qty * (1 - C.COMISION_EXT) - fee_ret
    usd = vender(bids_b, qty) if qty > 0 else None
    return None if usd is None else usd * (1 - C.COMISION_EXT) / monto - 1


def escanear_extranjero(datos, info_redes, ahora):
    # 1) Candidatos por top de libro
    cand = []
    for simbolo, por_ex in datos.items():
        if len(por_ex) < 2 or min(v["vol"] for v in por_ex.values()) > C.VOL_MAX_USD:
            continue
        validos = {e: v for e, v in por_ex.items() if v["vol"] >= C.VOL_MIN_USD}
        for a, b in itertools.permutations(validos, 2):
            bruto = validos[b]["bid"] / validos[a]["ask"] - 1
            if 2 * C.COMISION_EXT < bruto <= 1.0:
                cand.append((bruto, simbolo, a, b, validos))
    cand.sort(reverse=True)

    # 3) Filtro de redes y profundidad sobre los mejores candidatos
    filas, revisados = [], 0
    for bruto, simbolo, a, b, validos in cand:
        if revisados >= C.TOP_PROFUNDIDAD:
            break
        base = simbolo.split("/")[0]
        fee_ret, nota = red_comun(info_redes, a, b, base)
        if fee_ret is None:
            continue
        revisados += 1
        try:
            _, asks_a = fuentes_extranjero.libro(a, simbolo)
            bids_b, _ = fuentes_extranjero.libro(b, simbolo)
        except Exception as e:
            continue
        neto = ciclo_usd(asks_a, bids_b, C.MONTO_USD, fee_ret)
        if neto is None:
            continue                                   # sin profundidad para el monto
        filas.append({"timestamp": ahora, "tipo": "extranjero", "moneda": simbolo,
                      "ruta": f"{a}->{b}", "neto": round(neto, 5), "bruto": round(bruto, 5),
                      "ganancia_clp": "", "precio_compra": validos[a]["ask"],
                      "precio_venta": validos[b]["bid"],
                      "volumen_usd": round(min(validos[a]["vol"], validos[b]["vol"])),
                      "nota": nota})
    return filas


# ---------- Buda <-> extranjero (dos traslados, todo con precios ejecutables) ----------
def redes_moneda(info_redes, ex, mon, preferida=None):
    """(fee_retiro, deposito_ok, retiro_ok, nota). None en flags = desconocido."""
    r = info_redes.get(ex)
    if r is None:
        return None, None, None, f"redes de {ex} no públicas"
    c = r.get(mon)
    if not c:
        return None, None, None, f"{mon} sin datos de red en {ex}"
    ret = c["retiro"]
    fee = None
    if preferida and preferida in ret and ret[preferida] is not None:
        fee = ret[preferida]
    elif ret:
        fees = [v for v in ret.values() if v is not None]
        fee = min(fees) if fees else None
    return fee, bool(c["deposito"]), bool(ret), ""


def escanear_buda_ext(libros, retiros, datos, info_redes, ahora):
    buda = libros.get("buda", {})
    usdt = buda.get("USDT")
    if not usdt or not usdt["bids"] or not usdt["asks"]:
        return []
    fee_b = C.COMISION_TAKER["buda"]
    ret_b_usdt, _ = fee_retiro(retiros, "buda", "USDT")
    filas = []
    for mon, lb in buda.items():
        if mon in ("USDT", "CLP") or not lb["bids"] or not lb["asks"]:
            continue
        simbolo = f"{mon}/USDT"
        for ex, tk in datos.get(simbolo, {}).items():
            # Prefiltro barato con tops de libro
            ida = tk["bid"] * usdt["bids"][0][0] / lb["asks"][0][0] - 1
            vuelta = lb["bids"][0][0] / (tk["ask"] * usdt["asks"][0][0]) - 1
            if max(ida, vuelta) < 0.01:
                continue
            try:
                bids_x, asks_x = fuentes_extranjero.libro(ex, simbolo)
            except Exception:
                continue
            ret_b_mon, _ = fee_retiro(retiros, "buda", mon)
            t = C.TIEMPO_TRASLADO_MIN.get(mon, 30) + C.TIEMPO_TRASLADO_MIN["USDT"]

            # IDA: CLP -> mon (Buda) -> vender en ex por USDT -> USDT a Buda -> CLP
            fee_x_usdt, _, ret_ok_usdt, n1 = redes_moneda(info_redes, ex, "USDT", C.RED_USDT_PREFERIDA)
            _, dep_ok_mon, _, n2 = redes_moneda(info_redes, ex, mon)
            notas = [n for n in (n1, n2) if n]
            if dep_ok_mon is False:
                notas.append(f"depósitos de {mon} cerrados en {ex}")
            if ret_ok_usdt is False:
                notas.append(f"retiros de USDT cerrados en {ex}")
            fx = fee_x_usdt if fee_x_usdt is not None else C.RETIRO_CRIPTO_DEFAULT["USDT"]
            q = comprar(lb["asks"], C.MONTO_CLP)
            neto = None
            if q is not None and ret_b_mon is not None:
                q = q * (1 - fee_b) - ret_b_mon
                u = vender(bids_x, q) if q > 0 else None
                if u is not None:
                    u = u * (1 - C.COMISION_EXT) - fx
                    clp = vender(usdt["bids"], u) if u > 0 else None
                    if clp is not None:
                        neto = (clp * (1 - fee_b) - C.RETIRO_CLP["buda"]) / C.MONTO_CLP - 1
            if neto is not None:
                filas.append({"timestamp": ahora, "tipo": "buda-ext", "moneda": mon,
                              "ruta": f"buda->{ex}->buda (ida)", "neto": round(neto, 5),
                              "bruto": round(ida, 5), "ganancia_clp": round(neto * C.MONTO_CLP),
                              "precio_compra": lb["asks"][0][0], "precio_venta": tk["bid"],
                              "volumen_usd": round(tk["vol"]),
                              "nota": "; ".join(notas + [f"2 traslados (~{t} min)"])})

            # VUELTA: CLP -> USDT (Buda) -> comprar mon en ex -> mon a Buda -> CLP
            fee_x_mon, _, ret_ok_mon, n3 = redes_moneda(info_redes, ex, mon)
            _, dep_ok_usdt, _, n4 = redes_moneda(info_redes, ex, "USDT")
            notas = [n for n in (n3, n4) if n]
            if dep_ok_usdt is False:
                notas.append(f"depósitos de USDT cerrados en {ex}")
            if ret_ok_mon is False:
                notas.append(f"retiros de {mon} cerrados en {ex}")
            fm = fee_x_mon if fee_x_mon is not None else C.RETIRO_CRIPTO_DEFAULT.get(mon)
            u = comprar(usdt["asks"], C.MONTO_CLP)
            neto = None
            if u is not None and ret_b_usdt is not None and fm is not None:
                u = u * (1 - fee_b) - ret_b_usdt
                q = comprar(asks_x, u) if u > 0 else None
                if q is not None:
                    q = q * (1 - C.COMISION_EXT) - fm
                    clp = vender(lb["bids"], q) if q > 0 else None
                    if clp is not None:
                        neto = (clp * (1 - fee_b) - C.RETIRO_CLP["buda"]) / C.MONTO_CLP - 1
            if neto is not None:
                filas.append({"timestamp": ahora, "tipo": "buda-ext", "moneda": mon,
                              "ruta": f"buda->{ex}->buda (vuelta)", "neto": round(neto, 5),
                              "bruto": round(vuelta, 5), "ganancia_clp": round(neto * C.MONTO_CLP),
                              "precio_compra": tk["ask"], "precio_venta": lb["bids"][0][0],
                              "volumen_usd": round(tk["vol"]),
                              "nota": "; ".join(notas + [f"2 traslados (~{t} min)"])})
    return filas


# ---------- CryptoMKT: solo referencia (revisar a mano) ----------
def escanear_ref(libros, refs, ahora):
    buda = libros.get("buda", {})
    filas = []
    for mon, ref in refs.items():
        lb = buda.get(mon)
        if not lb or not lb["bids"] or not lb["asks"]:
            continue
        caro = ref / lb["asks"][0][0] - 1           # CryptoMKT sobre Buda: comprar en Buda
        barato = lb["bids"][0][0] / ref - 1         # CryptoMKT bajo Buda: comprar en CryptoMKT
        for dif, ruta, pc, pv in ((caro, "buda->cryptomkt", lb["asks"][0][0], ref),
                                  (barato, "cryptomkt->buda", ref, lb["bids"][0][0])):
            if dif > 0:
                filas.append({"timestamp": ahora, "tipo": "referencia", "moneda": mon, "ruta": ruta,
                              "neto": round(dif, 5), "bruto": round(dif, 5), "ganancia_clp": "",
                              "precio_compra": pc, "precio_venta": pv, "volumen_usd": "",
                              "nota": "precio de referencia CryptoMKT, sin costos: revisar a mano"})
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
    return {"chile": C.UMBRAL_NETO_CL, "buda-ext": C.UMBRAL_NETO_CL,
            "referencia": C.UMBRAL_REF_CRYPTOMKT}.get(f["tipo"], C.UMBRAL_NETO_EXT)


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
    dur = f"{n} lecturas seguidas (~{(n - 1) * 15} min)" if n > 1 else "primera lectura"
    if f["tipo"] == "buda-ext":
        ex = f["ruta"].split("->")[1]
        if "(ida)" in f["ruta"]:
            pasos = (f"comprar {f['moneda']} en Buda (${miles(f['precio_compra'])}) → enviarlo a {ex} → "
                     f"venderlo por USDT ({f['precio_venta']}) → enviar USDT a Buda por "
                     f"{C.RED_USDT_PREFERIDA} → vender USDT por pesos")
        else:
            pasos = (f"comprar USDT en Buda → enviarlos a {ex} por {C.RED_USDT_PREFERIDA} → comprar "
                     f"{f['moneda']} ({f['precio_compra']} USDT) → enviarlo a Buda → venderlo "
                     f"(${miles(f['precio_venta'])})")
        return (f"• {f['moneda']} vía {ex}: {pasos}\n"
                f"  Con ${miles(C.MONTO_CLP)}: neto {float(f['neto']):.2%} "
                f"(≈ ${miles(float(f['ganancia_clp']))}). Spread visto: {dur}.\n  Ojo: {f['nota']}")
    if f["tipo"] == "referencia":
        a, b = f["ruta"].split("->")
        return (f"• {f['moneda']}: diferencia de {float(f['neto']):.1%} entre Buda y el precio de "
                f"referencia de CryptoMKT (comprar en {a}, vender en {b}). Spread visto: {dur}.\n"
                f"  No es precio ejecutable ni incluye costos: revisa en la app de CryptoMKT el "
                f"precio real de compra/venta antes de mover nada.")
    a, b = f["ruta"].split("->")
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
            f"  Neto calculado con US${C.MONTO_USD}, comisiones, retiro por la red común y profundidad."
            + (f"\n  Ojo: {f['nota']}" if f["nota"] else ""))


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

    libros, retiros, est_cl, refs = fuentes_chile.todas()
    datos_ext, est_ext = fuentes_extranjero.tickers(C.EXCHANGES_EXT, C.QUOTES_EXT)
    operativos = [e for e, v in est_ext.items() if v.startswith("OK") and "(0 pares)" not in v]
    info_redes, est_redes = fuentes_extranjero.redes(operativos)
    print("Redes:", est_redes)
    filas = (escanear_chile(libros, retiros, ahora)
             + escanear_buda_ext(libros, retiros, datos_ext, info_redes, ahora)
             + escanear_ref(libros, refs, ahora)
             + escanear_extranjero(datos_ext, info_redes, ahora))
    resumen({**est_cl, **est_ext}, filas)

    alertas = []
    for f in filas:
        if not sobre_umbral(f):
            continue
        if f["tipo"] == "chile" and "deshabilitados" in f["nota"]:
            continue
        if f["tipo"] == "buda-ext" and "cerrados" in f["nota"]:
            continue
        if f["tipo"] == "extranjero" and "desconocido" in f["nota"]:
            continue                                   # sin redes confirmadas no se alerta
        n = lecturas_seguidas(historial, f)
        if n >= C.LECTURAS_MIN:
            alertas.append((f, n))
    if alertas:
        orden = {"chile": 0, "buda-ext": 1, "referencia": 2, "extranjero": 3}
        alertas.sort(key=lambda x: (orden.get(x[0]["tipo"], 9), -float(x[0]["neto"])))
        cuerpo = "\n\n".join(texto_alerta(f, n) for f, n in alertas)
        cuerpo += ("\n\nAntes de operar: confirma en ambas plataformas que la red de retiro y la de "
                   "depósito coincidan, que no haya retiros suspendidos y que el precio siga ahí.")
        f0 = alertas[0][0]
        enviar_mail(f"🚚 Viaje: {f0['moneda']} {f0['ruta']} neto {float(f0['neto']):.1%}", cuerpo)

    # Para no inflar el CSV: todas las rutas chilenas con bruto > 0, y en el extranjero solo
    # las que superan la mitad del umbral. Una fila "lectura" marca cada corrida.
    guardar_filas = [f for f in filas if f["tipo"] in ("chile", "referencia")
                     or (f["neto"] != "" and float(f["neto"]) >= umbral(f) / 2)]
    guardar_filas.append({k: "" for k in CAMPOS} | {"timestamp": ahora, "tipo": "lectura"})
    guardar(guardar_filas)


if __name__ == "__main__":
    main()
