"""레버리지를 쓰면? — 규칙 A·C를 비트코인·이더리움(2018~2026)에 1배·2배·3배·5배로 계산해 본다.

가정 (선물처럼 계산):
- 수수료 0.05% + 체결 손해 0.05%를 사고팔 때마다 '빌린 돈까지 포함한 전체 금액'에 매김
- 2배 이상이면 보유 시간 동안 펀딩비 0.01%/8시간 (롱이 낸다고 가정)
- 거래 중 가격이 '1/레버리지 - 0.5%' 이상 불리하게 움직이면 강제 청산 → 그 코인 계좌는 0원
실행: COIN_DATA_DIR=data/merged python research/leverage_check.py
"""
import numpy as np
import pandas as pd

from engine import simulate
from strategies import Market
from validate import load_unit, rules, signals

FEE, SLIP, FUND_H, MM = 0.0005, 0.0005, 0.0001 / 8, 0.005
START = pd.Timestamp("2018-01-01")
COINS = ["KRW-BTC", "KRW-ETH"]


def trades(m, key):
    family, sig, ex = rules(5)[key]
    s = signals(m, family, sig)
    e, x, pe, px, t = simulate(m.o, m.h, m.l, m.c, s.entries, ex, s.exit_sig, s.levels, s.deadlines)
    keep = m.ts[e] >= START
    e, x, pe, px = e[keep], x[keep], pe[keep], px[keep]
    start = e + (1 if s.levels is not None else 0)
    mae = np.array([min((m.l[a:b].min() if b > a else p0) / p0 - 1, p1 / p0 - 1) for a, b, p0, p1 in zip(start, x, pe, px)])
    hold_h = (x - e) * 5 / 60
    return m.ts[x], px / pe - 1, mae, hold_h


def run(key, lev):
    paths, liq = [], 0
    for mk in COINS:
        m = Market(mk, load_unit(mk, 5, 5))
        when, g, mae, hold_h = trades(m, key)
        acct, vals, low = 1.0, [], 1.0
        for gi, ai, hi in zip(g, mae, hold_h):
            if acct <= 0:
                vals.append(0.0)
                continue
            if lev == 1:
                r = (1 + gi) * (1 - SLIP) * (1 - FEE) / ((1 + SLIP) * (1 + FEE)) - 1
            elif ai <= -(1 / lev - MM):
                r, liq = -1.0, liq + 1
            else:
                r = lev * gi - lev * 2 * (FEE + SLIP) - lev * FUND_H * hi
            low = min(low, acct * max(0.0, 1 + lev * ai))
            acct = max(0.0, acct * (1 + r))
            vals.append(acct)
        paths.append(pd.Series(vals, index=when))
    # 연도별 (두 코인 계좌 평균)
    yrs, prev = {}, 1.0
    for y in range(2018, 2027):
        end = pd.Timestamp(f"{y}-12-31 23:59")
        v = float(np.mean([(p[p.index <= end].iloc[-1] if (p.index <= end).any() else 1.0) for p in paths]))
        yrs[y] = v / prev - 1 if prev > 0 else -1.0
        prev = v
    allv = pd.concat(paths, axis=1, sort=True).ffill().fillna(1.0).mean(axis=1)
    mdd = float((allv / allv.cummax() - 1).min())
    return float(allv.iloc[-1]), yrs, mdd, liq


if __name__ == "__main__":
    for key, name in (("A", "변동성 돌파"), ("C", "RSI2")):
        for lev in (1, 2, 3, 5):
            fin, yrs, mdd, liq = run(key, lev)
            worst = min(yrs, key=yrs.get)
            print(f"{name} {lev}배: 30만원 → {300000 * fin:>12,.0f}원 | 가장 나쁜 해 {worst} {yrs[worst] * 100:+.1f}% | "
                  f"고점 대비 최대 하락 {mdd * 100:.0f}% | 강제 청산 {liq}회 | 연도별 {[f'{y % 100}:{v * 100:+.0f}%' for y, v in yrs.items()]}", flush=True)
