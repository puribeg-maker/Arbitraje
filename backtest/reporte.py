"""Reporte HTML autocontenido con métricas, gráficos y robustez."""
import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

FMT_PCT = {"CAGR", "Volatilidad", "Máx. drawdown", "Retorno total"}


def _img(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return f'<img src="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}">'


def _tabla_metricas(m):
    df = pd.DataFrame(m).T
    out = df.copy().astype(object)
    for c in df.columns:
        out[c] = [("—" if pd.isna(v) else f"{v:.1%}" if c in FMT_PCT
                   else f"{v:.0%}" if c == "Rotación anual" else f"{v:.2f}")
                  for v in df[c]]
    return out.to_html(classes="t", border=0)


def generar(ruta, series, metricas_, elecciones, robustez, notas):
    fig, ax = plt.subplots(2, 1, figsize=(10, 7), sharex=True,
                           gridspec_kw={"height_ratios": [2, 1]})
    for nombre, r in series.items():
        eq = (1 + r).cumprod()
        ax[0].plot(eq, label=nombre)
        ax[1].plot(eq / eq.cummax() - 1, label=nombre)
    ax[0].set_yscale("log"); ax[0].set_title("Valor de US$1 (escala log, período fuera de muestra)")
    ax[0].legend(); ax[1].set_title("Drawdown")
    for a in ax: a.grid(alpha=.3)

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Backtest momentum cripto</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#222}}
.t{{border-collapse:collapse;font-size:14px;margin:8px 0 20px}}
.t td,.t th{{padding:5px 10px;border-bottom:1px solid #ddd;text-align:right}}
.t th:first-child,.t td:first-child{{text-align:left}} .nota{{background:#fff6e0;padding:10px 14px;border-radius:6px}}
img{{max-width:100%}}</style></head><body>
<h1>Backtest: momentum relativo + filtro de régimen</h1>
<h2>Resultados fuera de muestra</h2>{_tabla_metricas(metricas_)}
{_img(fig)}
<h2>Parámetros elegidos en cada ventana</h2>
<p>Si cambian mucho de una ventana a otra, la estrategia no es estable.</p>
{elecciones.to_html(classes="t", border=0, index=False, float_format=lambda v: f"{v:.2f}")}
<h2>Robustez: Sharpe de cada combinación (período completo)</h2>
<p>Lo sano es que combinaciones vecinas den resultados parecidos. Una sola celda brillante rodeada de malas es casualidad.</p>
{robustez.to_html(classes="t", border=0, float_format=lambda v: f"{v:.2f}")}
<div class="nota"><b>Limitaciones:</b><ul>{''.join(f'<li>{n}</li>' for n in notas)}</ul></div>
</body></html>"""
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(html)
