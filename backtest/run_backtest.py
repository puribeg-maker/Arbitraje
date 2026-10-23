"""Uso: python run_backtest.py [--refrescar]"""
import os
import sys

import pandas as pd

import config_bt as C
import reporte
from backtest import equal_weight, metricas, simular
from datos import descargar
from walkforward import correr_grilla, walk_forward


def main():
    close, vol = descargar(C.DESDE, refrescar="--refrescar" in sys.argv)
    close, vol = close.sort_index(), vol.reindex_like(close)
    if "BTC" not in close:
        sys.exit("Falta BTC en los datos; no se puede calcular el régimen.")
    print(f"Datos: {close.shape[1]} activos, {close.index[0].date()} a {close.index[-1].date()}")

    print("Corriendo grilla...")
    claves, res = correr_grilla(close, vol, C.BASE, C.GRILLA, C.COSTO_TOTAL)

    inicio = close.index[max(C.GRILLA["lookback"]) + C.BASE["salto"] + 60
                         + max(C.GRILLA["sma_regimen"])]
    oos, elecciones = walk_forward(res, claves, C.WF_TRAIN, C.WF_TEST, inicio)
    rango = oos.index

    btc = close["BTC"].pct_change(fill_method=None).loc[rango].fillna(0)
    ew, ew_rot = equal_weight(close, vol, C.BASE["vol_min_usd"], C.BASE["rebalanceo"], C.COSTO_TOTAL)
    mejor_fija = max(res, key=lambda k: metricas(res[k][0].loc[rango]).get("Sharpe", -9))
    rot_wf = pd.concat([res[k][1] for k in res], axis=1).mean(axis=1)  # aproximación

    series = {"Estrategia (walk-forward)": oos, "BTC (mantener)": btc,
              "Universo igual peso": ew.loc[rango]}
    mets = {"Estrategia (walk-forward)": metricas(oos, rot_wf),
            "BTC (mantener)": metricas(btc),
            "Universo igual peso": metricas(ew.loc[rango], ew_rot),
            f"Mejor combinación fija {dict(zip(claves, mejor_fija))} (optimista)":
                metricas(res[mejor_fija][0].loc[rango], res[mejor_fija][1])}

    filas = []
    for k, (r, _) in res.items():
        filas.append({**dict(zip(claves, k)), "Sharpe": metricas(r.loc[rango]).get("Sharpe")})
    rob = pd.DataFrame(filas).pivot_table(index=["top_n", "lookback"],
                                          columns="sma_regimen", values="Sharpe")

    notas = [
        "Sesgo de supervivencia: el universo son los activos listados HOY en Kraken; "
        "los que quebraron o se deslistaron no están, lo que infla los resultados.",
        "La historia viene de Yahoo Finance; algunos activos pueden aparecer antes de su listado real en Kraken.",
        f"Costos supuestos: {C.COMISION:.2%} comisión + {C.SLIPPAGE:.2%} slippage por lado.",
        "La fila 'Mejor combinación fija' elige los parámetros mirando todo el período: es optimista "
        "por construcción y sirve solo como techo. La cifra válida es la de walk-forward.",
        "Rotación de la estrategia walk-forward: aproximada (promedio de la grilla).",
        "Entre rebalanceos se asumen pesos constantes (no se modela la deriva de precios), "
        "lo que subestima levemente los costos.",
    ]
    os.makedirs("reporte", exist_ok=True)
    reporte.generar("reporte/reporte.html", series, mets, elecciones, rob, notas)
    oos.to_csv("reporte/retornos_oos.csv")
    print("\nResumen fuera de muestra:")
    print(pd.DataFrame(mets).T.round(3).to_string())
    print("\nReporte: reporte/reporte.html")


if __name__ == "__main__":
    main()
