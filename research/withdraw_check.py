"""'100만원 넣어두고 한 달에 한 번 확인, 번 돈의 일부를 생활비로 빼기'를 9년(2018~2026)에 적용해 본다.

인출 규칙: 매달 말 계좌가 지금까지의 최고 기록(인출 후 기준)보다 높으면, 넘긴 금액의 일부(기본 50%)를 뺀다.
규칙 A(변동성 돌파, 손절 -3%), 비트코인·이더리움 50만원씩. 레버리지 1배/2배.
실행: COIN_DATA_DIR=data/merged python research/withdraw_check.py
"""
import numpy as np
import pandas as pd

import leverage_check as lc
from strategies import Market
from validate import load_unit

START_KRW = 1_000_000


def trade_returns(key, lev):
    out = []
    for mk in lc.COINS:
        m = Market(mk, load_unit(mk, 5, 5))
        when, g, mae, hold_h = lc.trades(m, key)
        rs = []
        for gi, ai, hi in zip(g, mae, hold_h):
            if lev == 1:
                r = (1 + gi) * (1 - lc.SLIP) * (1 - lc.FEE) / ((1 + lc.SLIP) * (1 + lc.FEE)) - 1
            elif ai <= -(1 / lev - lc.MM):
                r = -1.0
            else:
                r = lev * gi - lev * 2 * (lc.FEE + lc.SLIP) - lev * lc.FUND_H * hi
            rs.append(r)
        out.append(pd.Series(rs, index=when))
    return out


def simulate_plan(key, lev, share):
    per_coin = trade_returns(key, lev)
    months = pd.date_range("2018-01-31", "2026-10-31", freq="ME")
    acct = [START_KRW / 2, START_KRW / 2]
    hwm, taken, log = START_KRW, 0.0, []
    prev_end = pd.Timestamp("2017-12-31 23:59")
    for me in months:
        end = me + pd.Timedelta(hours=23, minutes=59)
        for i, s in enumerate(per_coin):
            seg = s[(s.index > prev_end) & (s.index <= end)]
            for r in seg:
                acct[i] = max(0.0, acct[i] * (1 + r))
        v = sum(acct)
        w = share * (v - hwm) if v > hwm else 0.0
        if w > 0:
            acct = [a * (v - w) / v for a in acct]
            v -= w
            hwm = v
        taken += w
        log.append({"month": me.strftime("%Y-%m"), "value": v, "withdraw": w})
        prev_end = end
    df = pd.DataFrame(log)
    df["year"] = df["month"].str[:4]
    by_year = df.groupby("year")["withdraw"].sum()
    paid = df[df["withdraw"] > 0]
    # 생활비를 못 가져간 가장 긴 기간
    gap, best_gap, gap_start, best_start = 0, 0, None, None
    for _, r in df.iterrows():
        if r["withdraw"] > 0:
            gap = 0
        else:
            if gap == 0:
                gap_start = r["month"]
            gap += 1
            if gap > best_gap:
                best_gap, best_start = gap, gap_start
    return df, by_year, paid, taken, best_gap, best_start


if __name__ == "__main__":
    for lev in (1, 2):
        for share in (0.5,):
            df, by_year, paid, taken, gap, gap_start = simulate_plan("A", lev, share)
            v = df["value"]
            print(f"\n변동성 돌파 {lev}배 · 최고 기록 넘긴 금액의 {int(share * 100)}% 인출")
            print(f"  생활비로 가져간 돈 합계: {taken:,.0f}원 | 남은 계좌: {v.iloc[-1]:,.0f}원 | 합계(가져간 돈+남은 계좌): {taken + v.iloc[-1]:,.0f}원")
            print(f"  돈을 가져간 달: {len(paid)}/{len(df)}개월 | 그 달 평균 {paid['withdraw'].mean():,.0f}원 | 가장 많이 가져간 달 {paid['withdraw'].max():,.0f}원 ({paid.loc[paid['withdraw'].idxmax(), 'month']})")
            print(f"  한 푼도 못 가져간 가장 긴 기간: {gap}개월 ({gap_start}부터) | 계좌가 가장 적었을 때(월말): {v.min():,.0f}원")
            print("  연도별 생활비:", " / ".join(f"{y}: {w:,.0f}원" for y, w in by_year.items()))
