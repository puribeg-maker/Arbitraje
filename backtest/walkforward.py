"""Walk-forward: en cada ventana elige la mejor combinación con datos pasados
y la aplica en el período siguiente, que no vio."""
import itertools

import pandas as pd

from backtest import metricas, simular
from estrategia import pesos


def correr_grilla(close, vol_usd, base, grilla, costo):
    res = {}
    claves = list(grilla)
    for valores in itertools.product(*grilla.values()):
        p = {**base, **dict(zip(claves, valores))}
        r, rot = simular(close, pesos(close, vol_usd, p), costo)
        res[valores] = (r, rot)
        print(f"  {dict(zip(claves, valores))} listo")
    return claves, res


def walk_forward(res, claves, train, test, inicio):
    fechas = next(iter(res.values()))[0].index
    i = fechas.get_loc(inicio)
    tramos, rotaciones, elecciones = [], [], []
    while i + train < len(fechas):
        tr = fechas[i:i + train]
        te = fechas[i + train:i + train + test]
        mejor = max(res, key=lambda k: metricas(res[k][0].loc[tr]).get("Sharpe", -9))
        tramos.append(res[mejor][0].loc[te])
        rotaciones.append(res[mejor][1].loc[te])
        elecciones.append({"desde": te[0].date(), "hasta": te[-1].date(),
                           **dict(zip(claves, mejor)),
                           "Sharpe train": metricas(res[mejor][0].loc[tr]).get("Sharpe")})
        i += test
    return pd.concat(tramos), pd.concat(rotaciones), pd.DataFrame(elecciones)
