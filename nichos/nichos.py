"""Investigación de nichos en Etsy: competencia vs señales de demanda.
Etsy no publica ventas por API; se usan favoritos y visitas por día como proxy."""
import csv
import os
import smtplib
import statistics as st
import time
from collections import Counter
from datetime import datetime, timezone
from email.message import EmailMessage

import requests

API = "https://openapi.etsy.com/v3/application/listings/active"
TOP = 50                   # resultados que mira un comprador (aprox. primera página)
MAX_DESCUBIERTAS = 25      # palabras nuevas a evaluar por corrida
MIN_FRECUENCIA_TAG = 4     # un tag debe repetirse al menos esto para considerarse
CSV_PATH = "data/nichos.csv"
CAMPOS = ["fecha", "keyword", "origen", "competencia", "fav_dia", "visitas_dia",
          "precio_usd", "pct_nuevos", "puntaje"]


# ---------- API ----------
def _headers(con_secreto=True):
    k = os.environ["ETSY_KEYSTRING"].strip()
    s = os.getenv("ETSY_SHARED_SECRET", "").strip()
    return {"x-api-key": f"{k}:{s}" if con_secreto and s else k}


def diagnostico():
    """Verifica la key antes de buscar, sin imprimir secretos."""
    k, sec = os.getenv("ETSY_KEYSTRING", ""), os.getenv("ETSY_SHARED_SECRET", "")
    print(f"[diag] ETSY_KEYSTRING: {len(k)} caracteres | ETSY_SHARED_SECRET: {len(sec)} caracteres")
    if k != k.strip() or sec != sec.strip():
        print("[diag] Ojo: algún secret tiene espacios o saltos de línea al inicio o al final.")
    url = "https://openapi.etsy.com/v3/application/openapi-ping"
    for con_secreto in (True, False):
        r = requests.get(url, headers=_headers(con_secreto), timeout=30)
        formato = "keystring:secret" if con_secreto else "solo keystring"
        print(f"[diag] ping ({formato}): {r.status_code} {r.text[:200]}")
        if r.ok:
            return con_secreto
    raise SystemExit("La API de Etsy rechazó la key en ambos formatos (ver [diag] arriba).")


def buscar(keyword):
    params = {"keywords": keyword, "limit": 100, "sort_on": "score"}
    r = requests.get(API, headers=_headers(), params=params, timeout=30)
    if r.status_code == 403:   # Etsy documenta dos formatos de key; se prueba el otro
        r = requests.get(API, headers=_headers(False), params=params, timeout=30)
    if r.status_code == 429:
        time.sleep(5)
        r = requests.get(API, headers=_headers(), params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"{r.status_code} {r.text[:200]}")
    time.sleep(0.25)           # bajo el límite de Etsy
    return r.json()


# ---------- Métricas ----------
def analizar(keyword, data, origen, ahora):
    res = data.get("results", [])[:TOP]
    hoy = ahora.timestamp()
    fav_dia, vis_dia, precios, nuevos = [], [], [], 0
    for l in res:
        creado = l.get("original_creation_timestamp") or l.get("creation_timestamp") or hoy
        dias = max((hoy - creado) / 86400, 7)
        fav_dia.append((l.get("num_favorers") or 0) / dias)
        vis_dia.append((l.get("views") or 0) / dias)
        nuevos += dias <= 180
        p = l.get("price") or {}
        if p.get("currency_code") == "USD" and p.get("divisor"):
            precios.append(p["amount"] / p["divisor"])
    competencia = int(data.get("count", 0))
    fav = st.median(fav_dia) if fav_dia else 0
    # Puntaje: demanda por producto visible, castigada por la cantidad de competidores
    puntaje = fav * 1000 / (competencia ** 0.5) if competencia else 0
    return {"fecha": ahora.date().isoformat(), "keyword": keyword, "origen": origen,
            "competencia": competencia, "fav_dia": round(fav, 3),
            "visitas_dia": round(st.median(vis_dia), 2) if vis_dia else 0,
            "precio_usd": round(st.median(precios), 2) if precios else "",
            "pct_nuevos": round(nuevos / len(res), 2) if res else 0,
            "puntaje": round(puntaje, 2)}


def tags_frecuentes(respuestas, excluir):
    c = Counter()
    for data in respuestas:
        for l in data.get("results", [])[:TOP]:
            for t in set(x.lower().strip() for x in (l.get("tags") or [])):
                if len(t.split()) >= 2 and t not in excluir:   # solo frases (long tail)
                    c[t] += 1
    return [t for t, n in c.most_common() if n >= MIN_FRECUENCIA_TAG][:MAX_DESCUBIERTAS]


# ---------- Historial y reporte ----------
def leer_historial():
    if not os.path.exists(CSV_PATH):
        return []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def guardar(filas):
    nuevo = not os.path.exists(CSV_PATH)
    os.makedirs("data", exist_ok=True)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        if nuevo:
            w.writeheader()
        w.writerows(filas)


def variacion(historial, kw, competencia):
    previas = [h for h in historial if h["keyword"] == kw]
    if not previas:
        return "nuevo"
    ant = int(previas[-1]["competencia"])
    return f"{(competencia / ant - 1):+.0%}" if ant else "—"


def html_reporte(filas, historial, descubiertas):
    def miles(x): return f"{x:,.0f}".replace(",", ".")
    orden = sorted(filas, key=lambda f: f["puntaje"], reverse=True)
    rows = "".join(
        f"<tr><td>{f['keyword']}{' 🆕' if f['origen'] == 'descubierta' else ''}</td>"
        f"<td>{f['puntaje']:.2f}</td><td>{miles(f['competencia'])}</td>"
        f"<td>{variacion(historial, f['keyword'], f['competencia'])}</td>"
        f"<td>{f['fav_dia']:.2f}</td><td>{f['precio_usd'] or '—'}</td>"
        f"<td>{f['pct_nuevos']:.0%}</td></tr>" for f in orden)
    return f"""<html><body style="font-family:Arial,sans-serif;font-size:13px">
<h2>Nichos Etsy — {filas[0]['fecha']}</h2>
<p>Ordenado por puntaje (demanda por producto visible ajustada por competencia). 🆕 = palabra descubierta desde tags.</p>
<table border="1" cellpadding="5" cellspacing="0" style="border-collapse:collapse">
<tr style="background:#eee"><th>Keyword</th><th>Puntaje</th><th>Competencia</th><th>Δ comp. vs anterior</th>
<th>Favoritos/día (mediana top {TOP})</th><th>Precio mediano USD</th><th>% top nuevos (&lt;6 meses)</th></tr>
{rows}</table>
<p><b>Cómo leerlo:</b> buscas puntaje alto, competencia que no crece rápido y un % de nuevos alto
(significa que productos recientes logran llegar a la primera página).
Favoritos y visitas son aproximaciones de demanda: Etsy no publica ventas.</p>
<p>Palabras descubiertas esta semana: {', '.join(descubiertas) or 'ninguna'}</p>
</body></html>"""


def enviar_mail(asunto, html):
    usuario, clave = os.getenv("GMAIL_USER"), os.getenv("GMAIL_APP_PASSWORD")
    if not usuario or not clave:
        print("[info] Sin credenciales de Gmail; reporte solo en el log.")
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = asunto, usuario, os.getenv("MAIL_TO") or usuario
    msg.set_content("Tu cliente de correo no muestra HTML.")
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(usuario, clave)
        s.send_message(msg)


def leer_semillas():
    with open("keywords.txt", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def main():
    ahora = datetime.now(timezone.utc)
    historial = leer_historial()
    semillas = leer_semillas()
    diagnostico()
    filas, respuestas = [], []

    for kw in semillas:
        try:
            data = buscar(kw)
            respuestas.append(data)
            filas.append(analizar(kw, data, "semilla", ahora))
        except Exception as e:
            print(f"[error] {kw}: {e}")

    descubiertas = tags_frecuentes(respuestas, {s.lower() for s in semillas})
    for kw in descubiertas:
        try:
            filas.append(analizar(kw, buscar(kw), "descubierta", ahora))
        except Exception as e:
            print(f"[error] {kw}: {e}")

    if not filas:
        raise SystemExit("Sin resultados: revisa la API key de Etsy.")
    for f in sorted(filas, key=lambda f: f["puntaje"], reverse=True)[:15]:
        print(f"{f['puntaje']:8.2f}  {f['competencia']:>8}  {f['keyword']}")
    top = max(filas, key=lambda f: f["puntaje"])
    enviar_mail(f"🔎 Nichos Etsy: top '{top['keyword']}'", html_reporte(filas, historial, descubiertas))
    guardar(filas)


if __name__ == "__main__":
    main()
