"""v2: momentum relativo vs BTC + régimen con banda (solo en rebalanceos)
+ buffer de rotación + sizing por volatilidad.
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
    sma = btc.rolling(p["sma_regimen"]).mean()

    W = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    fechas = close.index[L + s + 60::p["rebalanceo"]]
    en_mercado, cartera = False, []
    for t in fechas:
        # Régimen con banda, revisado solo al rebalancear
        if pd.notna(sma.loc[t]):
            if en_mercado and btc.loc[t] < sma.loc[t] * (1 - p["banda_regimen"]):
                en_mercado = False
            elif not en_mercado and btc.loc[t] > sma.loc[t] * (1 + p["banda_regimen"]):
                en_mercado = True

        w = pd.Series(0.0, index=close.columns)
        if not en_mercado or pd.isna(score.loc[t, "BTC"]):
            cartera = []
            W.loc[t] = w
            continue

        # Momentum dual: solo activos que le ganan a BTC (BTC siempre califica)
        sc = score.loc[t][elegible.loc[t]]
        sc_btc = score.loc[t, "BTC"]
        cand = sc[(sc >= sc_btc) & ((sc > 0) | (sc.index == "BTC"))]
        cand = pd.concat([cand, pd.Series({"BTC": sc_btc})]).groupby(level=0).first()
        ranking = cand.sort_values(ascending=False)

        # Buffer: se mantienen los actuales que sigan dentro del top ampliado
        top_amplio = set(ranking.index[: p["top_n"] * p["buffer_mult"]])
        mantener = [a for a in cartera if a in top_amplio]
        nuevos = [a for a in ranking.index if a not in mantener]
        cartera = (mantener + nuevos)[: p["top_n"]]

        iv = 1 / volat.loc[t, cartera].replace(0, np.nan).dropna()
        cartera = list(iv.index)
        w_top = iv / iv.sum()
        cov = ret[cartera].loc[:t].tail(60).cov() * 365
        vol_port = float(np.sqrt(w_top @ cov @ w_top))
        escala = min(1.0, p["vol_objetivo"] / vol_port) if vol_port > 0 else 0
        w_pre = w_top * escala
        w_cap = w_pre.copy()
        alts = [a for a in cartera if a != "BTC"]
        w_cap[alts] = w_cap[alts].clip(upper=p["max_peso"])
        # Lo que excede los topes de altcoins se va a BTC
        w_cap["BTC"] = w_cap.get("BTC", 0.0) + (w_pre.sum() - w_cap.sum())
        w[w_cap.index] = w_cap
        W.loc[t] = w

    return W.ffill().fillna(0.0)
