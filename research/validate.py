"""추가 검증: 사전 등록(PREREG_2019-2023.md)한 규칙을 다른 기간·코인·봉 단위로 그대로 시험한다.

실행 예:
    # 처음 보는 2019~2023년 (15분봉)
    python research/validate.py --name old --unit 15 --start 2019-01-01 --end 2023-09-01 \
        --main KRW-BTC,KRW-ETH,KRW-XRP,KRW-ADA --extra KRW-ETC,KRW-BCH,KRW-XLM,KRW-TRX
    # 최근 1년 (5분봉, 1단계와 같은 데이터)
    python research/validate.py --name recent --unit 5 --start 2025-10-01 --end 2100-01-01 \
        --main KRW-BTC,KRW-ETH,KRW-XRP,KRW-SOL --extra KRW-DOGE,KRW-ADA,KRW-LINK,KRW-NEAR
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from engine import COSTS, Cost, Exit, equity, max_drawdown, simulate, trade_stats
from run_study import clean
from indicators import DATA_DIR
from strategies import Market, random_entries, rsi2, vol_breakout

OUT = Path(__file__).resolve().parent.parent / "results"
START_KRW = 300_000


def load_unit(market: str, unit: int, source: int) -> pd.DataFrame:
    """N분봉을 불러와 빠진 봉을 직전 종가로 채운다. source=5면 5분봉 파일을 N분으로 합친다."""
    path = DATA_DIR / f"{market}_{source}m.csv.gz"
    df = pd.read_csv(path, parse_dates=["ts"], index_col="ts")
    df = df[~df.index.duplicated()].sort_index()
    if path.name.endswith("_5m.csv.gz") and unit != 5:
        df = df.resample(f"{unit}min").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                            "volume": "sum", "value": "sum"}).dropna()
    full = pd.date_range(df.index[0], df.index[-1], freq=f"{unit}min")
    df = df.reindex(full)
    close = df["close"].ffill()
    for col in ("open", "high", "low"):
        df[col] = df[col].fillna(close)
    df["close"] = close
    df[["volume", "value"]] = df[["volume", "value"]].fillna(0.0)
    df.index.name = "ts"
    return df


def rules(unit: int):
    """사전 등록한 규칙 + 공개용 변동성 돌파 전체/주변 설정."""
    per_hour = 60 // unit
    out = {
        "A": ("volbo", (0.6, True), Exit(0.03, None, None)),
        "B": ("volbo", (0.5, True), Exit(None, None, None)),
        "C": ("rsi2", ("1h", 5), Exit(None, None, 100 * per_hour)),
    }
    for k in (0.4, 0.5, 0.6):
        for ma in (False, True):
            for sl in (None, 0.02, 0.03):
                out[f"fam|k={k}|ma={ma}|sl={sl}"] = ("volbo", (k, ma), Exit(sl, None, None))
    for k in (0.4, 0.5, 0.6, 0.7, 0.8):
        for sl in (None, 0.02, 0.03, 0.04, 0.05):
            out[f"grid|k={k}|sl={sl}"] = ("volbo", (k, True), Exit(sl, None, None))
    return out


def signals(m: Market, family: str, sig: tuple):
    if family == "volbo":
        return vol_breakout(m, *sig)
    return rsi2(m, *sig)


def random_population(m: Market, family: str, sig: tuple, ex: Exit, lo: int, hi: int, unit: int, seed: int = 7):
    """같은 매도 규칙으로 '아무 때나' 샀을 때의 거래들 (p값 계산용)."""
    if family == "volbo":
        rnd = random_entries(m, f"{unit}min" if unit != 60 else "1h", 1500, lo, hi, seed)
        day0 = m.ts[rnd.entries] - pd.Timedelta("9h")
        nxt = day0.normalize() + pd.Timedelta("1D") + pd.Timedelta("9h")
        dl = m.ts.searchsorted(nxt)
        keep = dl < m.n
        e, x, pe, px, t = simulate(m.o, m.h, m.l, m.c, rnd.entries[keep], ex, None, None, dl[keep], overlap=True)
    else:
        rnd = random_entries(m, "1h", 1500, lo, hi, seed)
        s = signals(m, family, sig)
        e, x, pe, px, t = simulate(m.o, m.h, m.l, m.c, rnd.entries, ex, s.exit_sig, overlap=True)
    return pe, px


def p_value(strat_r, pop_r):
    if len(strat_r) < 20 or len(pop_r) < 20:
        return None
    z = (strat_r.mean() - pop_r.mean()) / (pop_r.std(ddof=1) / math.sqrt(len(strat_r)))
    return float(0.5 * math.erfc(z / math.sqrt(2)))


def run(name, unit, start, end, main, extra, years, slip_mult=1.0, source=None):
    mk_all = main + extra
    mkts = {mk: Market(mk, load_unit(mk, unit, source or unit)) for mk in mk_all}
    costs = {"upbit": COSTS["upbit"], "free": COSTS["free_api"]}
    if slip_mult != 1.0:
        costs = {k: Cost(fee=v.fee, slip=v.slip * slip_mult) for k, v in costs.items()}
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    rng_idx = {mk: (int(m.ts.searchsorted(t0)), int(m.ts.searchsorted(t1))) for mk, m in mkts.items()}
    res = {"name": name, "unit": unit, "start": start, "end": str(min(t1, max(m.ts[-1] for m in mkts.values()))),
           "main": main, "extra": extra, "slip_mult": slip_mult, "rules": {}}

    # 그냥 들고 있기 (주력 코인 균등)
    def hold_between(a, b):
        vals = []
        for mk in main:
            m = mkts[mk]
            lo, hi = int(m.ts.searchsorted(a)), min(int(m.ts.searchsorted(b)), m.n) - 1
            if hi > lo:
                vals.append(pd.Series(m.c[lo:hi + 1] / m.o[lo], index=m.ts[lo:hi + 1]))
        port = pd.concat(vals, axis=1).ffill().bfill().mean(axis=1)
        return float(port.iloc[-1] - 1), float(port.min()), max_drawdown(port.to_numpy()), port

    hr, hmin, hmdd, hport = hold_between(t0, t1)
    hdaily = hport.resample("1D").last()
    res["hold"] = {"ret": hr, "final_krw": round(START_KRW * (1 + hr)), "low_krw": round(START_KRW * hmin), "mdd": hmdd,
                   "years": {y: hold_between(pd.Timestamp(a), pd.Timestamp(b))[0] for y, (a, b) in years.items()},
                   "curve": {"dates": [d.strftime("%Y-%m-%d") for d in hdaily.index],
                             "krw": [round(START_KRW * v) for v in hdaily.to_numpy()]}}

    for key, (family, sig, ex) in rules(unit).items():
        sim = {}
        for mk in mk_all:
            m = mkts[mk]
            s = signals(m, family, sig)
            sim[mk] = simulate(m.o, m.h, m.l, m.c, s.entries, ex, s.exit_sig, s.levels, s.deadlines)
        out = {"family": family, "sig": list(sig), "sl": ex.sl}
        for cname, cost in costs.items():
            per = {}
            for group, mks in (("main", main), ("extra", extra)):
                rs = []
                for mk in mks:
                    e, x, pe, px, t = sim[mk]
                    lo, hi = rng_idx[mk]
                    sel = (e >= lo) & (e < hi)
                    rs.append(cost.net(pe[sel], px[sel]))
                r = np.concatenate(rs) if rs else np.array([])
                per[group] = trade_stats(r)
                if group == "main":
                    main_r = r
            # 30만원 계좌 (주력 코인 25%씩)
            eqs = []
            for mk in main:
                m = mkts[mk]
                lo, hi = rng_idx[mk]
                e, x, pe, px, t = sim[mk]
                eqs.append(pd.Series(equity(m.c, e, x, pe, px, cost, lo, hi), index=m.ts[lo:hi]))
            port = pd.concat(eqs, axis=1).ffill().bfill().mean(axis=1)
            per["ret"] = float(port.iloc[-1] - 1)
            per["final_krw"] = round(START_KRW * port.iloc[-1])
            per["low_krw"] = round(START_KRW * port.min())
            per["mdd"] = max_drawdown(port.to_numpy())
            daily = port.resample("1D").last()
            monthly = daily.resample("MS").last()
            mret = (monthly / pd.concat([pd.Series([1.0]), monthly.iloc[:-1]]).to_numpy() - 1).dropna()
            per["months"] = {"total": int(len(mret)), "up": int((mret > 0).sum()), "down": int((mret < 0).sum()),
                             "worst": float(mret.min()) if len(mret) else None, "best": float(mret.max()) if len(mret) else None}
            per["years"] = {}
            for y, (a, b) in years.items():
                seg = daily[(daily.index >= pd.Timestamp(a)) & (daily.index < pd.Timestamp(b))]
                prev = daily[daily.index < pd.Timestamp(a)]
                base = prev.iloc[-1] if len(prev) else 1.0
                per["years"][y] = float(seg.iloc[-1] / base - 1) if len(seg) else None
            if key in ("A", "B", "C"):
                per["curve"] = {"dates": [d.strftime("%Y-%m-%d") for d in daily.index],
                                "krw": [round(START_KRW * v) for v in daily.to_numpy()]}
                pops = []
                for mk in main:
                    m = mkts[mk]
                    lo, hi = rng_idx[mk]
                    pe, px = random_population(m, family, sig, ex, lo, hi, unit)
                    pops.append(cost.net(pe, px))
                pop = np.concatenate(pops)
                per["random_exp"] = float(pop.mean())
                per["p_value"] = p_value(main_r, pop)
                # 운에 따른 흔들림: 거래 순서를 무작위로 다시 뽑아 1년 결과 범위 추정 (4코인 25%씩 근사)
                if len(main_r) >= 20:
                    rng = np.random.default_rng(1)
                    sims = rng.choice(main_r, size=(5000, len(main_r)), replace=True)
                    # 4개 계좌에 거래가 고르게 나뉜다고 보고, 계좌별 복리 → 평균
                    k = len(main_r) // 4
                    parts = sims[:, :4 * k].reshape(5000, 4, k)
                    finals = START_KRW * np.prod(1 + parts, axis=2).mean(axis=1)
                    per["boot_p05"] = round(float(np.percentile(finals, 5)))
                    per["boot_p50"] = round(float(np.percentile(finals, 50)))
                    per["boot_p95"] = round(float(np.percentile(finals, 95)))
                    per["boot_loss_prob"] = float((finals < START_KRW).mean())
            out[cname] = per
        res["rules"][key] = out
        print(f"  {key}: 업비트 {out['upbit']['ret'] * 100:+.1f}% ({out['upbit']['final_krw']:,}원), "
              f"승률 {out['upbit']['main'].get('win_rate', 0) * 100:.1f}%, 거래 {out['upbit']['main'].get('n', 0)}회", flush=True)
    path = OUT / f"validation_{name}.json"
    path.write_text(json.dumps(clean(res), ensure_ascii=False))
    print(f"저장 → {path}")
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--unit", type=int, default=5)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--main", required=True)
    p.add_argument("--extra", default="")
    p.add_argument("--years", default="", help="구간 이름=시작~끝 쉼표 구분, 예: 2019=2019-01-01~2020-01-01")
    p.add_argument("--slip-mult", type=float, default=1.0)
    p.add_argument("--source", type=int, default=None, help="어떤 분봉 파일에서 읽을지 (기본: --unit과 같음)")
    a = p.parse_args()
    years = {}
    for part in filter(None, a.years.split(",")):
        nm, rg = part.split("=")
        s, e = rg.split("~")
        years[nm] = (s, e)
    run(a.name, a.unit, a.start, a.end, a.main.split(","), [x for x in a.extra.split(",") if x], years, a.slip_mult, a.source)


if __name__ == "__main__":
    main()
