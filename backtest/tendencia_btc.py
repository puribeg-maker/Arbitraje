"""Backtest: BTC o caja según filtro de tendencia (media móvil con banda).
Uso: python tendencia_btc.py
Criterios de éxito definidos ANTES de ver resultados (ver CRITERIOS)."""
import base64
import io
import itertools
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

DESDE = "2014-01-01"
COSTO = 0.006                      # 0,4% comisión + 0,2% slippage, por lado
GRILLA = {"sma": [50, 100, 200], "banda": [0.0, 0.03, 0.05],
          "frecuencia": ["diaria", "semanal"]}
WF_TRAIN, WF_TEST = 730, 90        # entrena con 2 años, prueba en los 90 días siguientes
CRITERIOS = {"dd_max_vs_btc": 2 / 3, "min_combos_dd_menor": 14}   # 14 de 18


# ---------- Datos ----------
def descargar():
    h = yf.Ticker("BTC-USD").history(start=DESDE, auto_adjust=False)
    c = h["Close"]
    c.index = c.index.tz_localize(None).normalize()
    c = c[c > 0]
    r = c.pct_change()
    return c.mask((r > 3) | (r < -0.9)).ffill()


# ---------- Estrategia ----------
def posicion(close, sma_n, banda, frecuencia):
    """1 = en BTC, 0 = en caja. Decidida al cierre de t, rige desde t+1."""
    sma = close.rolling(sma_n).mean().values
    px = close.values
    pos = np.zeros(len(px))
    dentro = False
    paso = 1 if frecuencia == "diaria" else 7
    for i in range(len(px)):
        if not np.isnan(sma[i]) and (i - sma_n) % paso == 0:
            if dentro and px[i] < sma[i] * (1 - banda):
                dentro = False
            elif not dentro and px[i] > sma[i] * (1 + banda):
                dentro = True
        pos[i] = dentro
    return pd.Series(pos, index=close.index)


def simular(close, pos):
    ret = close.pct_change().fillna(0)
    cambios = pos.diff().abs().fillna(0)
    return pos.shift(1).fillna(0) * ret - cambios * COSTO, cambios


def metricas(r, cambios=None):
    r = r.dropna()
    eq = (1 + r).cumprod()
    años = len(r) / 365
    dd = (eq / eq.cummax() - 1).min()
    cagr = eq.iloc[-1] ** (1 / años) - 1
    m = {"CAGR": cagr, "Volatilidad": r.std() * np.sqrt(365),
         "Sharpe": r.mean() / r.std() * np.sqrt(365) if r.std() > 0 else np.nan,
         "Máx. drawdown": dd, "Calmar": cagr / abs(dd) if dd < 0 else np.nan,
         "Retorno total": eq.iloc[-1] - 1}
    if cambios is not None:
        m["Operaciones/año"] = cambios.loc[r.index].sum() / años
        m["% tiempo en BTC"] = (r != 0).mean()
    return m


# ---------- Walk-forward ----------
def walk_forward(res, inicio):
    fechas = next(iter(res.values()))[0].index
    i = fechas.get_loc(inicio)
    tramos, cambios, elecciones = [], [], []
    while i + WF_TRAIN < len(fechas):
        tr, te = fechas[i:i + WF_TRAIN], fechas[i + WF_TRAIN:i + WF_TRAIN + WF_TEST]
        mejor = max(res, key=lambda k: np.nan_to_num(metricas(res[k][0].loc[tr])["Calmar"], nan=-9))
        tramos.append(res[mejor][0].loc[te]); cambios.append(res[mejor][1].loc[te])
        elecciones.append({"desde": te[0].date(), "hasta": te[-1].date(),
                           "sma": mejor[0], "banda": f"{mejor[1]:.0%}", "frecuencia": mejor[2]})
        i += WF_TEST
    return pd.concat(tramos), pd.concat(cambios), pd.DataFrame(elecciones), mejor


# ---------- Reporte ----------
FMT = {"CAGR", "Volatilidad", "Máx. drawdown", "Retorno total", "% tiempo en BTC"}


def tabla(m):
    df = pd.DataFrame(m).T.astype(object)
    for c in df.columns:
        df[c] = ["—" if pd.isna(v) else f"{v:.1%}" if c in FMT else f"{v:.2f}" for v in df[c]]
    return df.to_html(classes="t", border=0)


def img(fig):
    b = io.BytesIO(); fig.savefig(b, format="png", dpi=110, bbox_inches="tight"); plt.close(fig)
    return f'<img src="data:image/png;base64,{base64.b64encode(b.getvalue()).decode()}">'


def main():
    close = descargar()
    print(f"BTC: {close.index[0].date()} a {close.index[-1].date()} ({len(close)} días)")

    res = {}
    for k in itertools.product(*GRILLA.values()):
        res[k] = simular(close, posicion(close, *k))

    inicio = close.index[max(GRILLA["sma"])]
    oos, cambios, elecciones, ultima = walk_forward(res, inicio)
    rango = oos.index
    btc = close.pct_change().loc[rango].fillna(0)

    m_wf, m_btc = metricas(oos, cambios), metricas(btc)
    filas = []
    for k, (r, c) in res.items():
        mk = metricas(r.loc[rango], c)
        filas.append({"sma": k[0], "banda": f"{k[1]:.0%}", "frecuencia": k[2],
                      "CAGR": mk["CAGR"], "Máx. drawdown": mk["Máx. drawdown"],
                      "Calmar": mk["Calmar"], "Operaciones/año": mk["Operaciones/año"]})
    rob = pd.DataFrame(filas)

    # Criterios
    c1 = m_wf["Máx. drawdown"] >= CRITERIOS["dd_max_vs_btc"] * m_btc["Máx. drawdown"]
    c2 = m_wf["Calmar"] > m_btc["Calmar"]
    n_mejor = int((rob["Máx. drawdown"] > m_btc["Máx. drawdown"]).sum())
    c3 = n_mejor >= CRITERIOS["min_combos_dd_menor"]
    pasa = c1 and c2 and c3
    ok = lambda b: "✅" if b else "❌"
    criterios = f"""<ul>
<li>{ok(c1)} Drawdown máx. ≤ 2/3 del de BTC: {m_wf['Máx. drawdown']:.1%} vs límite {CRITERIOS['dd_max_vs_btc'] * m_btc['Máx. drawdown']:.1%}</li>
<li>{ok(c2)} Calmar mayor que BTC: {m_wf['Calmar']:.2f} vs {m_btc['Calmar']:.2f}</li>
<li>{ok(c3)} Combinaciones con drawdown menor que BTC: {n_mejor} de {len(rob)} (mínimo {CRITERIOS['min_combos_dd_menor']})</li>
</ul><p><b>Veredicto: {'PASA' if pasa else 'NO PASA'}</b></p>"""

    # Estado actual con la última combinación elegida
    pos_hoy = posicion(close, *ultima)
    cambios_hist = pos_hoy.diff().fillna(0)
    ult_cambio = cambios_hist[cambios_hist != 0].index[-1] if (cambios_hist != 0).any() else None
    sma_hoy = close.rolling(ultima[0]).mean().iloc[-1]
    estado = (f"Parámetros vigentes: SMA {ultima[0]}, banda {ultima[1]:.0%}, revisión {ultima[2]}. "
              f"Estado al {close.index[-1].date()}: <b>{'EN BTC' if pos_hoy.iloc[-1] else 'EN CAJA'}</b> "
              f"(BTC ${close.iloc[-1]:,.0f} vs media ${sma_hoy:,.0f})"
              + (f"; último cambio el {ult_cambio.date()}." if ult_cambio is not None else "."))

    anual = pd.DataFrame({"Estrategia (walk-forward)": (1 + oos).groupby(oos.index.year).prod() - 1,
                          "BTC (mantener)": (1 + btc).groupby(btc.index.year).prod() - 1})

    fig, ax = plt.subplots(2, 1, figsize=(10, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    for n, r in {"Estrategia (walk-forward)": oos, "BTC (mantener)": btc}.items():
        eq = (1 + r).cumprod()
        ax[0].plot(eq, label=n); ax[1].plot(eq / eq.cummax() - 1, label=n)
    ax[0].set_yscale("log"); ax[0].set_title("Valor de US$1 (log, fuera de muestra)"); ax[0].legend()
    ax[1].set_title("Drawdown")
    for a in ax: a.grid(alpha=.3)

    fmt_rob = rob.copy()
    for c in ["CAGR", "Máx. drawdown"]: fmt_rob[c] = fmt_rob[c].map(lambda v: f"{v:.1%}")
    for c in ["Calmar", "Operaciones/año"]: fmt_rob[c] = fmt_rob[c].map(lambda v: f"{v:.2f}")

    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Tendencia BTC</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#222}}
.t{{border-collapse:collapse;font-size:14px;margin:8px 0 20px}}.t td,.t th{{padding:5px 10px;border-bottom:1px solid #ddd;text-align:right}}
.t th:first-child,.t td:first-child{{text-align:left}}.box{{background:#f2f6ff;padding:10px 14px;border-radius:6px}}img{{max-width:100%}}</style></head><body>
<h1>BTC o caja: filtro de tendencia</h1>
<p>Fuera de muestra: {rango[0].date()} a {rango[-1].date()}. Walk-forward: entrena {WF_TRAIN} días (maximiza Calmar), prueba {WF_TEST}.</p>
<div class="box"><h2>Criterios (definidos antes de correr)</h2>{criterios}</div>
<h2>Resultados</h2>{tabla({"Estrategia (walk-forward)": m_wf, "BTC (mantener)": m_btc})}
{img(fig)}
<h2>Retorno por año</h2>{anual.to_html(classes="t", border=0, float_format=lambda v: f"{v:.1%}")}
<h2>Estado actual</h2><p>{estado}</p>
<h2>Parámetros elegidos en cada ventana</h2>{elecciones.to_html(classes="t", border=0, index=False)}
<h2>Robustez: las 18 combinaciones en el período fuera de muestra</h2>
<p>Referencia BTC: drawdown {m_btc['Máx. drawdown']:.1%}, Calmar {m_btc['Calmar']:.2f}.</p>
{fmt_rob.to_html(classes="t", border=0, index=False)}
<p><small>Costos: {COSTO:.1%} por cambio de posición. La caja no rinde interés (supuesto conservador). Datos: Yahoo Finance BTC-USD.</small></p>
</body></html>"""
    os.makedirs("reporte_btc", exist_ok=True)
    with open("reporte_btc/reporte_btc.html", "w", encoding="utf-8") as f:
        f.write(html)
    oos.to_csv("reporte_btc/retornos_oos_btc.csv")
    print(pd.DataFrame({"Estrategia": m_wf, "BTC": m_btc}).round(3).to_string())
    print(f"\nVeredicto: {'PASA' if pasa else 'NO PASA'} | criterios {c1}, {c2}, {c3} ({n_mejor}/18)")
    print(estado.replace("<b>", "").replace("</b>", ""))


if __name__ == "__main__":
    main()
