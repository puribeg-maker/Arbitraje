"""Momentum relativo ajustado por volatilidad + filtro de régimen + sizing por volatilidad.
Todo es causal: los pesos del día t solo usan datos hasta el cierre de t."""
import numpy as np
import pandas as pd


def pesos(close, vol_usd, p):
    ret = close.pct_change(fill_method=None)
    L, s = p["lookback"], p["salto"]

    mom = close.shift(s) / close.shift(L + s) - 1
    volat = ret.rolling(L).std() * np.sqrt(365)
    score = mom / volat

    liquido = vol_usd.rolling(30).median() >= p["vol_min_usd"]
    con_historia = close.notna().rolling(L + s + 60).sum() == L + s + 60
    elegible = liquido & con_historia & score.notna()

    btc = close["BTC"]
    regimen = btc > btc.rolling(p["sma_regimen"]).mean()

    W = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    fechas = close.index[L + s + 60::p["rebalanceo"]]
    for t in fechas:
        w = pd.Series(0.0, index=close.columns)
        sc = score.loc[t][elegible.loc[t]]
        top = sc[sc > 0].nlargest(p["top_n"])          # solo momentum positivo
        if len(top):
            iv = 1 / volat.loc[t, top.index]
            w_top = iv / iv.sum()                       # paridad de riesgo simple
            cov = ret[top.index].loc[:t].tail(60).cov() * 365
            vol_port = float(np.sqrt(w_top @ cov @ w_top))
            escala = min(1.0, p["vol_objetivo"] / vol_port) if vol_port > 0 else 0
            w[top.index] = (w_top * escala).clip(upper=p["max_peso"])
        W.loc[t] = w

    W = W.ffill().fillna(0.0)
    # El régimen se revisa a diario: si BTC pierde su media, la cartera pasa a caja
    return W.mul(regimen.astype(float), axis=0)
