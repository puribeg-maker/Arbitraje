"""Simulación diaria con costos y métricas."""
import numpy as np
import pandas as pd


def simular(close, W, costo):
    ret = close.pct_change(fill_method=None).fillna(0.0)
    bruto = (W.shift(1).fillna(0.0) * ret).sum(axis=1)      # pesos de t-1 x retorno de t
    rotacion = (W - W.shift(1).fillna(0.0)).abs().sum(axis=1)
    return bruto - rotacion * costo, rotacion


def metricas(r, rotacion=None):
    r = r.dropna()
    if len(r) < 30 or r.std() == 0:
        return {}
    eq = (1 + r).cumprod()
    años = len(r) / 365
    dd = (eq / eq.cummax() - 1).min()
    cagr = eq.iloc[-1] ** (1 / años) - 1
    m = {"CAGR": cagr, "Volatilidad": r.std() * np.sqrt(365),
         "Sharpe": r.mean() / r.std() * np.sqrt(365),
         "Máx. drawdown": dd, "Calmar": cagr / abs(dd) if dd < 0 else np.nan,
         "Retorno total": eq.iloc[-1] - 1}
    if rotacion is not None:
        m["Rotación anual"] = rotacion.loc[r.index].sum() / años
    return m


def equal_weight(close, vol_usd, vol_min, rebalanceo, costo):
    """Benchmark: todo el universo líquido, mismo peso, rebalanceo periódico."""
    liq = (vol_usd.rolling(30).median() >= vol_min) & close.notna()
    W = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for t in close.index[90::rebalanceo]:
        e = liq.loc[t]
        W.loc[t] = (e / e.sum()).fillna(0) if e.sum() else 0
    return simular(close, W.ffill().fillna(0.0), costo)
