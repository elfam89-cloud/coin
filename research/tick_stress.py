"""호가 단위 스트레스 테스트.

가격이 낮던 시절(리플·에이다 등)에는 호가 1칸이 가격의 0.2~1%나 되어서, 실제 체결 손해가
가정(0.05%)보다 훨씬 클 수 있다. 그래서 달마다 실제 데이터에서 호가 1칸 크기를 재고,
사고팔 때마다 'max(0.05%, 호가 1칸)'만큼 불리하게 체결된다고 보고 다시 계산한다.

실행: COIN_DATA_DIR=data/merged python research/tick_stress.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from engine import simulate
from strategies import Market
from validate import load_unit, rules, signals

OUT = Path(__file__).resolve().parent.parent / "results"
MAIN = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-ADA"]
FEE = 0.0005
BASE_SLIP = 0.0005
START, START_KRW = pd.Timestamp("2018-01-01"), 300_000


def monthly_tick_rel(df):
    """달마다 '서로 다른 가격 사이의 가장 작은 간격 ÷ 그달 중간 가격' = 호가 1칸의 비율."""
    out = {}
    for m, g in df.groupby(df.index.to_period("M")):
        px = np.unique(np.round(np.concatenate([g[c].to_numpy() for c in ("open", "high", "low", "close")]), 8))
        d = np.diff(px)
        d = d[d > 1e-9]
        if len(d) == 0:
            continue
        tick = np.percentile(d, 5)          # 가장 작은 간격 쪽 (잡음 방지로 5% 지점)
        out[str(m)] = float(tick / np.median(g["close"]))
    return out


def main(coins=MAIN, tag="all4"):
    res, res_r = {}, {}
    for key in ("A", "C"):
        family, sig, ex = rules(5)[key]
        all_r = None
        per_coin, acct_paths = {}, []
        for mk in coins:
            df = load_unit(mk, 5, 5)
            m = Market(mk, df)
            ticks = monthly_tick_rel(df)
            s = signals(m, family, sig)
            e, x, pe, px, t = simulate(m.o, m.h, m.l, m.c, s.entries, ex, s.exit_sig, s.levels, s.deadlines)
            sel = m.ts[e] >= START
            e, x, pe, px = e[sel], x[sel], pe[sel], px[sel]
            ent_m = m.ts[e].to_period("M").astype(str)
            ext_m = m.ts[x].to_period("M").astype(str)
            s_in = np.array([max(BASE_SLIP, ticks.get(k, BASE_SLIP)) for k in ent_m])
            s_out = np.array([max(BASE_SLIP, ticks.get(k, BASE_SLIP)) for k in ext_m])
            r_base = px * (1 - BASE_SLIP) * (1 - FEE) / (pe * (1 + BASE_SLIP) * (1 + FEE)) - 1
            r_tick = px * (1 - s_out) * (1 - FEE) / (pe * (1 + s_in) * (1 + FEE)) - 1
            unit_krw = START_KRW / len(coins)
            per_coin[mk] = {"n": int(len(r_base)), "win_rate": float((r_tick > 0).mean()),
                            "base_final": round(unit_krw * float(np.prod(1 + r_base))),
                            "tick_final": round(unit_krw * float(np.prod(1 + r_tick))),
                            "avg_tick_slip": float(np.mean((s_in + s_out) / 2))}
            acct_paths.append(pd.Series(np.cumprod(1 + r_tick), index=m.ts[x]))
            all_r = r_tick if all_r is None else np.concatenate([all_r, r_tick])
        # 연도별 (거래가 끝난 날 기준 계좌 가치, 4코인 평균)
        years = {}
        idx = pd.date_range("2018-12-31", "2026-12-31", freq="YE")
        prev = 1.0
        for y_end in list(idx) + [pd.Timestamp("2100-01-01")]:
            vals = []
            for p in acct_paths:
                p2 = p[p.index <= y_end]
                vals.append(p2.iloc[-1] if len(p2) else 1.0)
            v = float(np.mean(vals))
            label = str(y_end.year) if y_end.year < 2100 else None
            if label:
                years[label] = v / prev - 1
                prev = v
        final = float(np.mean([p.iloc[-1] for p in acct_paths]))
        # 월별: 거래가 끝난 날 기준 계좌 가치
        months = []
        midx = pd.date_range("2018-01-31", "2026-10-31", freq="ME")
        prevm = 1.0
        for me in midx:
            vals = [(p[p.index <= me].iloc[-1] if (p.index <= me).any() else 1.0) for p in acct_paths]
            v = float(np.mean(vals)); months.append(v / prevm - 1); prevm = v
        months = np.array(months)
        res[key] = {"coins": coins, "per_coin": per_coin, "years": years, "final_krw": round(START_KRW * final),
                    "n": int(len(all_r)), "win_rate": float((all_r > 0).mean()), "avg_win": float(all_r[all_r > 0].mean()),
                    "avg_loss": float(all_r[all_r <= 0].mean()), "expectancy": float(all_r.mean()),
                    "months_up": int((months > 0).sum()), "months_total": int(len(months)), "worst_month": float(months.min()),
                    "best_month": float(months.max())}
        print(f"\n== {key} [{tag}] (호가 1칸 손해 적용, 업비트 수수료) → 30만원 → {START_KRW * final:,.0f}원, "
              f"거래 {len(all_r)}회, 승률 {(all_r > 0).mean() * 100:.1f}%, 이익 본 달 {(months > 0).sum()}/{len(months)}, 최악의 달 {months.min() * 100:+.1f}%")
        print("  연도별:", {y: f"{v * 100:+.1f}%" for y, v in years.items()})
        for mk, v in per_coin.items():
            print(f"  {mk}: {v['n']}회, {START_KRW // len(coins):,}원 → 기본 가정 {v['base_final']:,}원 / 호가 손해 적용 {v['tick_final']:,}원 "
                  f"(평균 한쪽 체결 손해 {v['avg_tick_slip'] * 100:.3f}%)")
    (OUT / f"tick_stress_{tag}.json").write_text(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    import sys
    coins = sys.argv[1].split(",") if len(sys.argv) > 1 else MAIN
    main(coins, sys.argv[2] if len(sys.argv) > 2 else "all4")
