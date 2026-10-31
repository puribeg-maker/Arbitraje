"""Analiza los exports del Keyword Tool de eRank que subes a nichos/erank/.
No se conecta a eRank: solo procesa archivos que tú exportas (respeta sus términos).
Calcula ratio demanda/competencia, filtra, marca riesgos, compara con lecturas anteriores
y te manda un reporte por mail con el ranking completo adjunto."""
import csv
import glob
import hashlib
import io
import os
import re
import smtplib
from datetime import date
from email.message import EmailMessage

CARPETA = "erank"
HIST = "data/erank_historial.csv"
PROCESADOS = "data/erank_procesados.txt"
RANKING = "data/erank_ranking.csv"

MIN_BUSQUEDAS = 30          # bajo esto, demanda insuficiente para partir
MIN_CTR = 60                # % de búsquedas que terminan en clic
VOLUMEN_ALTO = 1000         # búsquedas/mes para la tabla de "volumen alto"
TOP = 25

# Términos que conviene no usar en productos: marcas de medicamentos, autolesión/suicidio,
# y marcas o personajes protegidos. La lista es orientativa; agrega los que veas.
RIESGO_MEDICAMENTO = ["zoloft", "lexapro", "sertraline", "prozac", "xanax", "adderall",
                      "ritalin", "wellbutrin", "ozempic", "klonopin", "lithium", "seroquel"]
RIESGO_SENSIBLE = ["suicide", "suicidal", "self harm", "self-harm", "988", "stay alive",
                   "lobotomy", "cutting"]
RIESGO_MARCA = ["disney", "inside out", "stanley", "hydro flask", "taylor swift", "harry potter",
                "pokemon", "sanrio", "hello kitty", "marvel", "nike", "starbucks", "barbie"]

CAMPOS_HIST = ["fecha", "keyword", "busquedas", "clics", "ctr", "dificultad", "competencia",
               "google", "archivo"]


def num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def leer_export(ruta):
    texto = open(ruta, encoding="utf-8-sig", errors="replace").read()
    delim = "\t" if texto.count("\t") > texto.count(",") else ","
    filas = []
    for r in csv.DictReader(io.StringIO(texto), delimiter=delim):
        r = {re.sub(r"^[^a-z]+", "", k.strip().lower().replace("\ufeff", "")): v
             for k, v in r.items() if k}
        kw = (r.get("keywords") or r.get("keyword") or "").strip().lower()
        if not kw:
            continue
        filas.append({"keyword": kw,
                      "busquedas": num(r.get("average searches")),
                      "clics": num(r.get("average clicks")),
                      "ctr": num(r.get("ctr")),
                      "dificultad": num(r.get("keyword difficulty")),
                      "competencia": num(r.get("competition")),
                      "google": num(r.get("google searches"))})
    return filas


def huella(ruta):
    return hashlib.sha1(open(ruta, "rb").read()).hexdigest()[:12]


def riesgos(kw):
    out = []
    if any(t in kw for t in RIESGO_MEDICAMENTO):
        out.append("marca de medicamento")
    if any(t in kw for t in RIESGO_SENSIBLE):
        out.append("tema sensible")
    if any(t in kw for t in RIESGO_MARCA):
        out.append("marca/personaje protegido")
    return out


def enriquecer(f):
    s, c, ctr = f["busquedas"] or 0, f["competencia"] or 0, f["ctr"] or 0
    f["ratio"] = round(s / c * 1000, 1) if c > 0 else None
    alertas = riesgos(f["keyword"])
    if s >= 20 and ctr == 0:
        alertas.append("CTR 0%: dato dudoso")
    if c == 0:
        alertas.append("sin dato de competencia")
    f["alertas"] = "; ".join(alertas)
    f["apto"] = (s >= MIN_BUSQUEDAS and ctr >= MIN_CTR and f["ratio"] is not None
                 and not any(a for a in alertas if "dudoso" in a or "medicamento" in a
                             or "sensible" in a or "protegido" in a))
    return f


def main():
    os.makedirs("data", exist_ok=True)
    hechos = set(open(PROCESADOS).read().split()) if os.path.exists(PROCESADOS) else set()
    historial = list(csv.DictReader(open(HIST, encoding="utf-8"))) if os.path.exists(HIST) else []
    hoy = date.today().isoformat()

    archivos = sorted(p for ext in ("csv", "tsv", "txt")
                      for p in glob.glob(f"{CARPETA}/**/*.{ext}", recursive=True))
    nuevos = [(p, huella(p)) for p in archivos if huella(p) not in hechos]
    if not nuevos:
        print("No hay exports nuevos en nichos/erank/.")
        return

    actuales = {}
    for ruta, h in nuevos:
        for f in leer_export(ruta):
            f["archivo"] = os.path.basename(ruta)
            actuales[f["keyword"]] = f            # si una frase se repite, queda la última
    print(f"{len(nuevos)} archivos nuevos, {len(actuales)} frases únicas")

    # Comparación con la lectura anterior de cada frase
    previo = {}
    for h in historial:
        if h["fecha"] < hoy:
            previo[h["keyword"]] = h
    filas = [enriquecer(f) for f in actuales.values()]
    for f in filas:
        p = previo.get(f["keyword"])
        f["delta_busq"] = (f"{(f['busquedas'] / float(p['busquedas']) - 1):+.0%}"
                           if p and num(p["busquedas"]) and f["busquedas"] is not None else "")
        f["delta_comp"] = (f"{(f['competencia'] / float(p['competencia']) - 1):+.0%}"
                           if p and num(p["competencia"]) and f["competencia"] is not None else "")

    ranking = sorted(filas, key=lambda f: (f["apto"], f["ratio"] or 0), reverse=True)
    campos = ["keyword", "busquedas", "competencia", "ratio", "ctr", "dificultad", "google",
              "delta_busq", "delta_comp", "apto", "alertas", "archivo"]
    with open(RANKING, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(ranking)

    nuevo_hist = not os.path.exists(HIST)
    with open(HIST, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS_HIST, extrasaction="ignore")
        if nuevo_hist:
            w.writeheader()
        w.writerows({**f, "fecha": hoy} for f in filas)
    with open(PROCESADOS, "a") as fh:
        fh.write("".join(f"{h}\n" for _, h in nuevos))

    enviar(reporte_html(ranking, len(nuevos)), RANKING)


def tabla(filas, titulo, nota=""):
    def n(v): return "—" if v is None or v == "" else f"{v:,.0f}".replace(",", ".")
    rows = "".join(
        f"<tr><td>{f['keyword']}</td><td>{n(f['busquedas'])}</td><td>{n(f['competencia'])}</td>"
        f"<td><b>{str(f['ratio']).replace('.', ',') if f['ratio'] is not None else '—'}</b></td><td>{n(f['ctr'])}%</td>"
        f"<td>{n(f['dificultad'])}</td><td>{f['delta_busq']}</td><td>{f['delta_comp']}</td>"
        f"<td>{f['alertas']}</td></tr>" for f in filas)
    return (f"<h3>{titulo}</h3><p>{nota}</p><table border='1' cellpadding='4' cellspacing='0' "
            f"style='border-collapse:collapse;font-size:12px'><tr style='background:#eee'>"
            f"<th>Frase</th><th>Búsq./mes</th><th>Competencia</th><th>Ratio</th><th>CTR</th>"
            f"<th>Dificultad</th><th>Δ búsq.</th><th>Δ comp.</th><th>Alertas</th></tr>{rows}</table>")


def reporte_html(ranking, n_archivos):
    aptos = [f for f in ranking if f["apto"]]
    volumen = sorted([f for f in aptos if (f["busquedas"] or 0) >= VOLUMEN_ALTO],
                     key=lambda f: f["ratio"] or 0, reverse=True)[:10]
    alertados = [f for f in ranking if f["alertas"] and (f["busquedas"] or 0) >= MIN_BUSQUEDAS][:20]
    return f"""<html><body style="font-family:Arial,sans-serif;font-size:13px">
<h2>Nichos eRank — {date.today().isoformat()}</h2>
<p>{n_archivos} exports procesados · {len(ranking)} frases · {len(aptos)} pasan los filtros
(≥{MIN_BUSQUEDAS} búsquedas/mes, CTR ≥{MIN_CTR}%, sin alertas de riesgo).</p>
<p><b>Ratio</b> = búsquedas ÷ competencia × 1.000: demanda por cada mil productos competidores.
Úsalo para comparar frases entre sí; los números de eRank son estimaciones.</p>
{tabla(aptos[:TOP], f"Top {TOP} por ratio")}
{tabla(volumen, "Volumen alto (≥1.000 búsquedas/mes) ordenado por ratio",
       "Nichos grandes: más ventas posibles, pero más difícil destacar.")}
{tabla(alertados, "Frases con demanda pero con alertas",
       "Revisar antes de usar: datos dudosos, marcas registradas o temas sensibles.")}
<p>Ranking completo adjunto (erank_ranking.csv).</p></body></html>"""


def enviar(html, adjunto):
    u, clave = os.getenv("GMAIL_USER"), os.getenv("GMAIL_APP_PASSWORD")
    if not u or not clave:
        print("[info] Sin credenciales de Gmail; reporte solo generado.")
        return
    msg = EmailMessage()
    msg["Subject"] = f"🔎 Ranking de nichos eRank — {date.today().isoformat()}"
    msg["From"], msg["To"] = u, os.getenv("MAIL_TO") or u
    msg.set_content("Tu cliente de correo no muestra HTML.")
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(open(adjunto, "rb").read(), maintype="text", subtype="csv",
                       filename="erank_ranking.csv")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(u, clave)
        s.send_message(msg)
    print("Reporte enviado.")


if __name__ == "__main__":
    main()
