"""1단계 타당성 조사: 여러 단타 전략을 과거 3년 데이터로 시험한다.

원칙 (과최적화 = '과거에만 잘 맞는 전략' 방지)
- 학습 기간(2023-10 ~ 2025-09)에서만 설정값을 고른다.
- 고른 설정을 검증 기간(2025-10 ~ 현재)에 '딱 한 번' 적용해 성적을 본다.
- 처음 보는 코인 4개(DOGE·ADA·LINK·NEAR)에서도 통하는지 본다.
- 무작위로 샀을 때와 비교해 '운'인지 '실력'인지 본다.

실행: python research/run_study.py   (결과: results/study.json, results/summary.md)
"""
import json
import math
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from engine import COSTS, EXIT_NAMES, Exit, equity, max_drawdown, simulate, trade_stats
from strategies import Market, Signals, bb_revert, breakout, pullback, random_entries, rsi2, vol_breakout

MAIN = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]
EXTRA = ["KRW-DOGE", "KRW-ADA", "KRW-LINK", "KRW-NEAR"]
PERIODS = {"is": ("2023-10-01", "2025-10-01"), "oos": ("2025-10-01", "2100-01-01")}
OUT = Path(__file__).resolve().parent.parent / "results"
MIN_TRADES = 100                                             # 후보가 되려면 학습 기간 거래 100회 이상

BARS = {"5min": 1, "15min": 3, "1h": 12, "1D": 288}           # 5분봉 몇 개인지
HOLD = {"5min": 144, "15min": 288, "1h": 864}                # 단타 시간 제한: 12시간 / 24시간 / 72시간
G_SL = [0.007, 0.01, 0.015, 0.02, 0.03]
G_TP = [0.005, 0.007, 0.01, 0.015, 0.02, 0.03, 0.05]
TF_KO = {"5min": "5분봉", "15min": "15분봉", "1h": "1시간봉", "1D": "일봉"}
FAMILY_KO = {
    "pullback": "눌림목 체크리스트(이전 세션)",
    "bb": "볼린저 하단 반등",
    "rsi2": "RSI(2) 단기 과매도",
    "volbo": "변동성 돌파",
    "breakout": "고점 돌파+거래량",
}


@dataclass(frozen=True)
class Cfg:
    family: str
    sig: tuple
    ex: Exit
    original: bool = False

    @property
    def key(self):
        e = self.ex
        return f"{self.family}|{','.join(map(str, self.sig))}|sl={e.sl}|tp={e.tp}|hold={e.max_hold}"

    @property
    def tf(self):
        return "1D" if self.family == "volbo" else self.sig[0]

    def label(self):
        e = self.ex
        sl = f"손절 -{e.sl * 100:g}%" if e.sl else "손절 없음"
        tp = f"익절 +{e.tp * 100:g}%" if e.tp else ""
        if self.family == "pullback":
            s = f"{TF_KO[self.sig[0]]}, {self.sig[1]}점 이상"
        elif self.family == "bb":
            s = f"{TF_KO[self.sig[0]]}" + (", 상승추세만" if self.sig[1] else "")
        elif self.family == "rsi2":
            s = f"{TF_KO[self.sig[0]]}, RSI(2)<{self.sig[1]}"
        elif self.family == "volbo":
            s = f"k={self.sig[0]}" + (", 5일선 필터" if self.sig[1] else "")
            tp = "다음날 09시 매도"
        else:
            s = f"{TF_KO[self.sig[0]]}"
        return f"{FAMILY_KO[self.family]} ({s}) · {sl}" + (f" · {tp}" if tp else "")


def build_configs():
    cfgs = []
    for ms in (4, 5):  # 이전 세션 원본 규칙: 1시간봉, 손절 -5%, 익절 +10% (사실상 시간 제한 없음 = 30일)
        cfgs.append(Cfg("pullback", ("1h", ms), Exit(0.05, 0.10, 8640), original=True))
    for tf in ("5min", "15min", "1h"):
        for ms in (4, 5):
            for sl in G_SL:
                for tp in G_TP:
                    cfgs.append(Cfg("pullback", (tf, ms), Exit(sl, tp, HOLD[tf])))
    for tf in ("5min", "15min", "1h"):
        for trend in (False, True):
            for sl in (0.01, 0.02, 0.03, 0.05):
                cfgs.append(Cfg("bb", (tf, trend), Exit(sl, None, 48 * BARS[tf])))
    for tf in ("15min", "1h"):
        for thr in (5, 10):
            for sl in (None, 0.03, 0.05):
                cfgs.append(Cfg("rsi2", (tf, thr), Exit(sl, None, 100 * BARS[tf])))
    for k in (0.4, 0.5, 0.6):
        for ma in (False, True):
            for sl in (None, 0.02, 0.03):
                cfgs.append(Cfg("volbo", (k, ma), Exit(sl, None, None)))
    for tf in ("15min", "1h"):
        for sl in G_SL:
            for tp in G_TP:
                cfgs.append(Cfg("breakout", (tf,), Exit(sl, tp, HOLD[tf])))
    return cfgs


def make_signals(m: Market, btc: Market, family: str, sig: tuple) -> Signals:
    if family == "pullback":
        return pullback(m, btc, *sig)
    if family == "bb":
        return bb_revert(m, *sig)
    if family == "rsi2":
        return rsi2(m, *sig)
    if family == "volbo":
        return vol_breakout(m, *sig)
    if family == "breakout":
        return breakout(m, *sig)
    raise ValueError(family)


def period_idx(m: Market):
    return {p: (m.idx(a), m.idx(b)) for p, (a, b) in PERIODS.items()}


def run_market(market):
    t0 = time.time()
    m = Market(market)
    btc = m if market == "KRW-BTC" else Market("KRW-BTC")
    sig_cache, out = {}, {}
    for cfg in build_configs():
        sk = (cfg.family, cfg.sig)
        if sk not in sig_cache:
            sig_cache[sk] = make_signals(m, btc, *sk)
        s = sig_cache[sk]
        e, x, pe, px, t = simulate(m.o, m.h, m.l, m.c, s.entries, cfg.ex, s.exit_sig, s.levels, s.deadlines)
        out[cfg.key] = (e.astype(np.int32), x.astype(np.int32), pe, px, t)
    print(f"  {market}: {len(out)}개 설정 계산 완료 ({time.time() - t0:.0f}초)", flush=True)
    return market, out, period_idx(m)


def pooled(trades, markets, cfg_key, period, pidx, cost):
    rs, holds = [], []
    for mk in markets:
        e, x, pe, px, t = trades[mk][cfg_key]
        lo, hi = pidx[mk][period]
        sel = (e >= lo) & (e < hi)
        rs.append(COSTS[cost].net(pe[sel], px[sel]))
        holds.append(x[sel] - e[sel])
    return np.concatenate(rs), np.concatenate(holds)


def stats_for(trades, markets, cfg_key, period, pidx, cost, days):
    r, hold = pooled(trades, markets, cfg_key, period, pidx, cost)
    s = trade_stats(r, hold)
    s["trades_per_day"] = s["n"] / days if s["n"] else 0.0
    return s


def main():
    OUT.mkdir(exist_ok=True)
    cfgs = build_configs()
    by_key = {c.key: c for c in cfgs}
    print(f"설정 {len(cfgs)}개 × 코인 {len(MAIN) + len(EXTRA)}개 계산 시작", flush=True)
    with Pool(4) as pool:
        res = pool.map(run_market, MAIN + EXTRA)
    trades = {mk: tr for mk, tr, _ in res}
    pidx = {mk: p for mk, _, p in res}
    ref = Market("KRW-BTC")
    days = {p: (min(ref.ts[-1], pd.Timestamp(b)) - pd.Timestamp(a)).days for p, (a, b) in PERIODS.items()}

    # 1) 모든 설정의 성적표
    table = []
    for c in cfgs:
        row = {"key": c.key, "family": c.family, "label": c.label(), "tf": c.tf, "original": c.original,
               "sl": c.ex.sl, "tp": c.ex.tp}
        for p in PERIODS:
            for cost in ("upbit", "free_api"):
                for name, mks in (("main", MAIN), ("extra", EXTRA)):
                    row[f"{p}_{cost}_{name}"] = stats_for(trades, mks, c.key, p, pidx, cost, days[p])
        table.append(row)

    # 2) 학습 기간(IS)만 보고 전략군별 후보 고르기 (주력 4코인, 거래 100회 이상)
    shortlist = {}
    for cost in ("upbit", "free_api"):
        for fam in FAMILY_KO:
            rows = [r for r in table if r["family"] == fam and r[f"is_{cost}_main"]["n"] >= MIN_TRADES]
            if not rows:
                continue
            best = max(rows, key=lambda r: r[f"is_{cost}_main"]["expectancy"])
            shortlist.setdefault(best["key"], set()).add(f"{cost}:최고기대값")
            wr = [r for r in rows if r[f"is_{cost}_main"]["win_rate"] >= 0.60 and r[f"is_{cost}_main"]["expectancy"] > 0]
            if wr:
                b2 = max(wr, key=lambda r: r[f"is_{cost}_main"]["expectancy"])
                shortlist.setdefault(b2["key"], set()).add(f"{cost}:승률60%+")
    for r in table:
        if r["original"]:
            shortlist.setdefault(r["key"], set()).add("이전세션원본")
    # 리포트 설명용 예시(후보 아님): 이전 세션 체크리스트 설정 중 검증 기간 승률이 가장 높았던 것
    pool = [r for r in table if r["family"] == "pullback" and not r["original"] and r["oos_upbit_main"].get("n", 0) >= MIN_TRADES]
    showcase = max(pool, key=lambda r: r["oos_upbit_main"]["win_rate"])["key"] if pool else None
    if showcase:
        shortlist.setdefault(showcase, set()).add("예시:승률최고(사후)")
    print(f"후보 {len(shortlist)}개 선정 (학습 기간 기준)", flush=True)

    # 3) 후보 정밀 분석: 무작위 기준선, 같은봉 가정 민감도, 포트폴리오 수익곡선/최대낙폭
    mk_obj = {mk: Market(mk) for mk in MAIN + EXTRA}
    btc = mk_obj["KRW-BTC"]
    detail = {}
    for key, why in shortlist.items():
        c = by_key[key]
        d = {"label": c.label(), "family": c.family, "why": sorted(why)}
        # 3-1) 무작위 진입 기준선 (같은 청산 규칙)
        for p in PERIODS:
            pop = []
            for mk in MAIN:
                m = mk_obj[mk]
                lo, hi = pidx[mk][p]
                rnd = random_entries(m, "5min" if c.family == "volbo" else c.tf, 1500, lo, hi, seed=7)
                s = make_signals(m, btc, c.family, c.sig) if c.family in ("bb", "rsi2") else None
                dl = None
                if c.family == "volbo":
                    day0 = m.ts[rnd.entries] - pd.Timedelta("9h")
                    nxt = day0.normalize() + pd.Timedelta("1D") + pd.Timedelta("9h")
                    dl = m.ts.searchsorted(nxt)
                    keep = dl < m.n
                    rnd.entries, dl = rnd.entries[keep], dl[keep]
                e, x, pe, px, t = simulate(m.o, m.h, m.l, m.c, rnd.entries, c.ex,
                                           s.exit_sig if s else None, None, dl, overlap=True)
                pop.append(COSTS["upbit"].net(pe, px))
            pop = np.concatenate(pop)
            strat_r, _ = pooled(trades, MAIN, key, p, pidx, "upbit")
            # p값: 무작위로 같은 횟수만큼 샀을 때 이 전략만큼(또는 더) 벌 확률 (정규근사)
            if len(strat_r) >= 20:
                z = (strat_r.mean() - pop.mean()) / (pop.std(ddof=1) / np.sqrt(len(strat_r)))
                pval = float(0.5 * math.erfc(z / math.sqrt(2)))
            else:
                pval = None
            d[f"random_{p}"] = {"expectancy": float(pop.mean()), "win_rate": float((pop > 0).mean()),
                                "p_value": pval}
        # 3-2) 같은 5분봉 안에서 손절·익절 순서를 '낙관적'으로 바꾸면?
        if c.ex.sl and c.ex.tp:
            opt = []
            for mk in MAIN:
                m = mk_obj[mk]
                s = make_signals(m, btc, c.family, c.sig)
                ex2 = Exit(c.ex.sl, c.ex.tp, c.ex.max_hold, tie="tp")
                e, x, pe, px, t = simulate(m.o, m.h, m.l, m.c, s.entries, ex2, s.exit_sig, s.levels, s.deadlines)
                lo, hi = pidx[mk]["oos"]
                sel = (e >= lo) & (e < hi)
                opt.append(COSTS["upbit"].net(pe[sel], px[sel]))
            d["oos_upbit_main_tie_optimistic"] = trade_stats(np.concatenate(opt))
        # 3-3) 청산 종류 비율, 코인별 성적 (검증 기간, 업비트 비용)
        kinds, per_coin = {}, {}
        for mk in MAIN + EXTRA:
            e, x, pe, px, t = trades[mk][key]
            lo, hi = pidx[mk]["oos"]
            sel = (e >= lo) & (e < hi)
            if mk in MAIN:
                for kk in t[sel]:
                    kinds[EXIT_NAMES[int(kk)]] = kinds.get(EXIT_NAMES[int(kk)], 0) + 1
            per_coin[mk] = trade_stats(COSTS["upbit"].net(pe[sel], px[sel]))
        d["oos_exit_kinds"] = kinds
        d["oos_per_coin"] = per_coin
        # 위험 지표: 가장 큰 손실 거래, 최장 연속 손실 (검증 기간, 주력 4코인, 업비트 비용)
        worst, streak = 0.0, 0
        for mk in MAIN:
            e, x, pe, px, t = trades[mk][key]
            lo, hi = pidx[mk]["oos"]
            sel = (e >= lo) & (e < hi)
            r = COSTS["upbit"].net(pe[sel], px[sel])
            if len(r):
                worst = min(worst, float(r.min()))
            run = 0
            for v in r:
                run = run + 1 if v <= 0 else 0
                streak = max(streak, run)
        d["oos_worst_trade"] = worst
        d["oos_max_loss_streak"] = streak
        for cost in ("upbit", "free_api"):  # 전체 기간(학습 시작 ~ 끝) 거래 통계
            rs_all, hold_all = [], []
            for mk in MAIN:
                e, x, pe, px, t = trades[mk][key]
                sel = e >= pidx[mk]["is"][0]
                rs_all.append(COSTS[cost].net(pe[sel], px[sel]))
                hold_all.append(x[sel] - e[sel])
            d[f"all_{cost}_main"] = trade_stats(np.concatenate(rs_all), np.concatenate(hold_all))
        for p in PERIODS:  # 비용 0 가정(참고용): 수수료가 결과를 얼마나 바꾸는지 보기 위해
            r0, _ = pooled(trades, MAIN, key, p, pidx, "zero")
            d[f"{p}_zero_main"] = trade_stats(r0)
        # 3-4) 포트폴리오(4코인 각 25%) 수익 곡선과 최대 낙폭
        for cost in ("upbit", "free_api"):
            for p in list(PERIODS) + ["all"]:
                eqs = []
                for mk in MAIN:
                    m = mk_obj[mk]
                    lo, hi = (pidx[mk]["is"][0], m.n) if p == "all" else pidx[mk][p]
                    e, x, pe, px, t = trades[mk][key]
                    eqs.append(pd.Series(equity(m.c, e, x, pe, px, COSTS[cost], lo, hi), index=m.ts[lo:hi]))
                port = pd.concat(eqs, axis=1).ffill().bfill().mean(axis=1)
                d[f"port_{p}_{cost}"] = {"return": float(port.iloc[-1] - 1), "mdd": max_drawdown(port.to_numpy())}
                if p in ("all", "oos"):
                    daily = port.resample("1D").last()
                    tag = "" if p == "all" else "oos_"
                    d[f"curve_{tag}{cost}"] = [round(float(v), 5) for v in daily.to_numpy()]
                    d[f"curve_{tag}dates"] = [ts.strftime("%Y-%m-%d") for ts in daily.index]
                    d[f"port_{p}_{cost}"]["min"] = float(port.min())
                if p == "oos" and cost == "upbit":
                    mon = port.resample("MS").last()
                    prev = pd.concat([pd.Series([1.0]), mon.iloc[:-1]]).to_numpy()
                    d["oos_monthly_upbit"] = {ts.strftime("%Y-%m"): float(v / pv - 1)
                                              for ts, v, pv in zip(mon.index, mon.to_numpy(), prev)}
        detail[key] = d

    # 4) 단순 보유(사서 가만히 두기) 기준선
    hold = {}
    for p in list(PERIODS) + ["all"]:
        curves = []
        for mk in MAIN:
            m = mk_obj[mk]
            lo, hi = (pidx[mk]["is"][0], m.n) if p == "all" else pidx[mk][p]
            curves.append(pd.Series(m.c[lo:hi] / m.o[lo], index=m.ts[lo:hi]))
        port = pd.concat(curves, axis=1).ffill().bfill().mean(axis=1)
        hold[p] = {"return": float(port.iloc[-1] - 1), "mdd": max_drawdown(port.to_numpy()), "min": float(port.min()),
                   "per_coin": {mk: float(cv.iloc[-1] - 1) for mk, cv in zip(MAIN, curves)}}
        if p == "all":
            hold["curve"] = [round(float(v), 5) for v in port.resample("1D").last().to_numpy()]
        if p == "oos":
            daily = port.resample("1D").last()
            hold["curve_oos"] = [round(float(v), 5) for v in daily.to_numpy()]
            hold["curve_oos_dates"] = [ts.strftime("%Y-%m-%d") for ts in daily.index]

    # 5) 교육용: 무작위 진입 + 손절/익절 조합 → '승률은 설정으로 만들 수 있다'
    grid = []
    for sl in G_SL:
        for tp in G_TP:
            ex = Exit(sl, tp, HOLD["15min"])
            rs = []
            for mk in MAIN:
                m = mk_obj[mk]
                lo, hi = pidx[mk]["is"][0], m.n
                rnd = random_entries(m, "15min", 2000, lo, hi, seed=3)
                e, x, pe, px, t = simulate(m.o, m.h, m.l, m.c, rnd.entries, ex, overlap=True)
                rs.append((pe, px))
            pe = np.concatenate([a for a, _ in rs])
            px = np.concatenate([b for _, b in rs])
            g = {"sl": sl, "tp": tp}
            for cost in COSTS:
                r = COSTS[cost].net(pe, px)
                g[cost] = {"win_rate": float((r > 0).mean()), "expectancy": float(r.mean())}
            grid.append(g)

    # 6) '승률 60%' 목표 점검: 학습 기간 승률 60%+ 설정들이 검증 기간에도 돈을 벌었나?
    wr_check = {}
    for cost in ("upbit", "free_api"):
        hi_wr = [r for r in table if r[f"is_{cost}_main"].get("n", 0) >= MIN_TRADES and r[f"is_{cost}_main"]["win_rate"] >= 0.6]
        prof = [r for r in hi_wr if r[f"is_{cost}_main"]["expectancy"] > 0]
        prof_oos = [r for r in prof if r[f"oos_{cost}_main"].get("n", 0) > 0 and r[f"oos_{cost}_main"]["expectancy"] > 0]
        wr_check[cost] = {"configs_total": len([r for r in table if r[f"is_{cost}_main"].get("n", 0) >= MIN_TRADES]),
                          "is_wr60": len(hi_wr), "is_wr60_profitable": len(prof),
                          "is_wr60_profitable_and_oos_profitable": len(prof_oos),
                          "examples": [r["label"] for r in prof_oos[:10]]}

    # 7) 워크포워드: 실제 봇처럼 '지난 12개월 성적 1등 설정'을 골라 다음 3개월에 적용, 이를 반복
    #    (지난 12개월 1등도 기대값이 0 이하면 그 3개월은 쉰다)
    def idx(mk, when):
        return int(mk_obj[mk].ts.searchsorted(pd.Timestamp(when)))

    def window_returns(key, a, b, cost, markets=MAIN):
        out = {}
        for mk in markets:
            e, x, pe, px, t = trades[mk][key]
            sel = (e >= idx(mk, a)) & (e < idx(mk, b))
            out[mk] = COSTS[cost].net(pe[sel], px[sel])
        return out

    walk = {}
    starts = pd.date_range("2024-10-01", ref.ts[-1], freq="3MS")
    for cost in ("upbit", "free_api"):
        steps = []
        for s0 in starts:
            tr0, s1 = s0 - pd.DateOffset(months=12), s0 + pd.DateOffset(months=3)
            best, best_mean = None, -np.inf
            for c in cfgs:
                r = np.concatenate(list(window_returns(c.key, tr0, s0, cost).values()))
                if len(r) >= MIN_TRADES // 2 and r.mean() > best_mean:
                    best, best_mean = c, float(r.mean())
            step = {"start": s0.strftime("%Y-%m"), "end": min(s1, ref.ts[-1]).strftime("%Y-%m-%d"),
                    "pick": best.label() if best else None, "train_expectancy": best_mean}
            hold_r = []  # 같은 3개월 동안 4코인을 그냥 들고 있었다면
            for mk in MAIN:
                m = mk_obj[mk]
                a, b = idx(mk, s0), min(idx(mk, s1), m.n) - 1
                if b > a:
                    hold_r.append(m.c[b] / m.o[a] - 1)
            step["hold_return"] = float(np.mean(hold_r)) if hold_r else 0.0
            if best is None or best_mean <= 0:
                step.update({"traded": False, "return": 0.0, "n": 0})
            else:
                per = window_returns(best.key, s0, s1, cost)
                allr = np.concatenate(list(per.values()))
                step.update({"traded": True, "n": int(len(allr)),
                             "win_rate": float((allr > 0).mean()) if len(allr) else None,
                             "expectancy": float(allr.mean()) if len(allr) else None,
                             # 4코인 각 25% 계좌, 거래별 복리
                             "return": float(np.mean([np.prod(1 + v) - 1 for v in per.values()]))})
            steps.append(step)
        total = float(np.prod([1 + s["return"] for s in steps]) - 1)
        hold_total = float(np.prod([1 + s["hold_return"] for s in steps]) - 1)
        walk[cost] = {"steps": steps, "total_return": total, "hold_total_return": hold_total}

    # 8) 손절·익절 조합별 성적표(히트맵용): 후보가 속한 전략군(같은 신호)만
    heat = {}
    for key in shortlist:
        c = by_key[key]
        if c.family not in ("pullback", "breakout") or c.original:
            continue
        hk = f"{c.family}|{','.join(map(str, c.sig))}"
        if hk in heat:
            continue
        cells = []
        for r in table:
            cc = by_key[r["key"]]
            if cc.family == c.family and cc.sig == c.sig and not cc.original:
                cells.append({"sl": cc.ex.sl, "tp": cc.ex.tp,
                              "is": r["is_upbit_main"].get("expectancy"), "oos": r["oos_upbit_main"].get("expectancy"),
                              "is_wr": r["is_upbit_main"].get("win_rate"), "oos_wr": r["oos_upbit_main"].get("win_rate"),
                              "is_free": r["is_free_api_main"].get("expectancy"),
                              "oos_free": r["oos_free_api_main"].get("expectancy")})
        heat[hk] = {"label": FAMILY_KO[c.family] + f" ({TF_KO[c.sig[0]]}" + (f", {c.sig[1]}점 이상)" if c.family == "pullback" else ")"),
                    "cells": cells}

    result = {
        "generated": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M KST"),
        "data_end": str(ref.ts[-1]),
        "periods": PERIODS, "days": days, "markets_main": MAIN, "markets_extra": EXTRA,
        "costs": {k: {"fee": v.fee, "slip": v.slip} for k, v in COSTS.items()},
        "n_configs": len(cfgs),
        "n_trades_simulated": int(sum(len(v[0]) for mk in trades for v in trades[mk].values())),
        "table": table, "shortlist": {k: sorted(v) for k, v in shortlist.items()}, "detail": detail,
        "buy_hold": hold, "random_grid": grid, "winrate_check": wr_check, "walk_forward": walk, "heat": heat,
    }
    (OUT / "study.json").write_text(json.dumps(clean(result), ensure_ascii=False))
    write_summary(result)
    print("완료 → results/study.json, results/summary.md", flush=True)


def clean(o):
    """JSON으로 저장할 수 있게 변환 (무한대/NaN → None)."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def pct(v, d=2):
    return "-" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v * 100:+.{d}f}%"


def write_summary(res):
    L = [f"# 1단계 타당성 조사 결과 요약", "", f"- 생성: {res['generated']} / 데이터 끝: {res['data_end']}",
         f"- 학습 기간: {res['periods']['is'][0]} ~ {res['periods']['is'][1]} / 검증 기간: {res['periods']['oos'][0]} ~ 데이터 끝",
         "- 비용(한쪽): 업비트 = 수수료 0.05% + 슬리피지 0.05%, API무료 = 슬리피지 0.05%", ""]
    h = res["buy_hold"]
    L += [f"단순 보유(4코인 균등): 학습 {pct(h['is']['return'])} (최대낙폭 {pct(h['is']['mdd'])}) / "
          f"검증 {pct(h['oos']['return'])} (최대낙폭 {pct(h['oos']['mdd'])})", ""]
    L += ["| 후보 | 선정 이유 | 학습 승률 | 학습 기대값 | 검증 거래수 | 검증 승률 | 검증 기대값(업비트) | 검증 기대값(API무료) | 무작위 대비 p | 검증 낙폭 | 새 코인 검증 기대값 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    rows = {r["key"]: r for r in res["table"]}
    for k, d in res["detail"].items():
        r = rows[k]
        a, b, f, x = r["is_upbit_main"], r["oos_upbit_main"], r["oos_free_api_main"], r["oos_upbit_extra"]
        pv = d["random_oos"]["p_value"]
        L.append(f"| {d['label']} | {', '.join(d['why'])} | {pct(a.get('win_rate'), 1)} | {pct(a.get('expectancy'), 3)} | "
                 f"{b.get('n', 0)} | {pct(b.get('win_rate'), 1)} | {pct(b.get('expectancy'), 3)} | {pct(f.get('expectancy'), 3)} | "
                 f"{'-' if pv is None else f'{pv:.2f}'} | {pct(d['port_oos_upbit']['mdd'], 1)} | {pct(x.get('expectancy'), 3)} |")
    L += ["", "## 워크포워드 (12개월로 고르고 다음 3개월 적용, 반복)", ""]
    for cost, w in res["walk_forward"].items():
        L.append(f"- {cost}: 누적 {pct(w['total_return'])}")
        for s in w["steps"]:
            L.append(f"  - {s['start']}: {'쉼' if not s['traded'] else s['pick']} → {pct(s['return'])}"
                     + (f" ({s['n']}회, 승률 {pct(s.get('win_rate'), 1)})" if s["traded"] else ""))
    L += ["", "## 승률 60% 목표 점검", ""]
    for cost, w in res["winrate_check"].items():
        L.append(f"- {cost}: 거래 100회 이상 설정 {w['configs_total']}개 중 학습 승률 60%+ {w['is_wr60']}개 → "
                 f"그중 기대값 플러스 {w['is_wr60_profitable']}개 → 검증 기간에도 플러스 {w['is_wr60_profitable_and_oos_profitable']}개")
    (OUT / "summary.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
