"""미국 배당주 아이디어 점검 — research/PREREG_us_dividend.md에 적은 그대로 계산한다.

시험 1: 배당락 전 거래일 종가 풀매수 → 배당락일 시가 매도 (배당 따먹기)
시험 2: 코인 규칙 A(변동성 돌파)·C(RSI2)를 숫자 그대로 배당주에
시험 3: A + 배당락 전날 풀매수 (사용자 아이디어 그대로)
실행: python research/fetch_us.py && python -I research/us_dividend_check.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from engine import Cost, Exit, simulate, trade_stats  # noqa: E402
from indicators import rsi, sma  # noqa: E402

ROOT = HERE.parent
DATA = ROOT / "data" / "us"
RES = ROOT / "results"
TICKERS = ["O", "MAIN", "STAG", "AGNC", "JEPI", "JEPQ", "QYLD", "SCHD"]
NAMES = {"O": "리얼티인컴", "MAIN": "메인스트리트", "STAG": "STAG 인더스트리얼", "AGNC": "AGNC (모기지 리츠)",
         "JEPI": "JEPI (커버드콜)", "JEPQ": "JEPQ (커버드콜)", "QYLD": "QYLD (커버드콜)", "SCHD": "SCHD (분기 배당)"}
START, END = pd.Timestamp("2016-10-01"), pd.Timestamp("2026-10-23")
TAX = 0.15
COSTS = {"event": Cost(fee=0.0007, slip=0.0005), "basic": Cost(fee=0.0025, slip=0.0005)}
ZERO = Cost(fee=0.0, slip=0.0)  # 참고용: 매매 비용이 0이라면 (배당 세금 15%는 그대로)
K, SL = 0.6, 0.03
START_KRW = 1_000_000


def load(t, iv):
    """Yahoo JSON → (가격 DataFrame, 배당 Series). 시간은 뉴욕 기준, 일봉은 날짜만."""
    j = json.loads((DATA / f"{t}_{iv}.json").read_text())["chart"]["result"][0]
    q = j["indicators"]["quote"][0]
    idx = pd.to_datetime(j["timestamp"], unit="s", utc=True).tz_convert("America/New_York").tz_localize(None)
    df = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close")}, index=idx, dtype=float).dropna()
    df = df[(df > 0).all(axis=1)]
    if iv == "1d":
        df.index = df.index.normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[df.index < END + pd.Timedelta("1D")]
    ev = j.get("events", {}).get("dividends", {})
    dv = pd.Series({pd.Timestamp(v["date"], unit="s", tz="UTC").tz_convert("America/New_York").tz_localize(None).normalize():
                    float(v["amount"]) for v in ev.values()}, dtype=float).sort_index()
    dv = dv.groupby(level=0).sum()
    return df, dv


def net(pe, px, div, cost):
    return (px * (1 - cost.slip) * (1 - cost.fee) + div * (1 - TAX)) / (pe * (1 + cost.slip) * (1 + cost.fee)) - 1


# ---------- 시험 1: 배당 따먹기 ----------
def capture(d, dv, cost):
    rows, skipped = [], 0
    for ex, amt in dv[(dv.index >= START) & (dv.index <= END)].items():
        i = d.index.searchsorted(ex)
        if i == 0 or i >= len(d) or d.index[i] != ex:
            skipped += 1
            continue
        pc, o, c = d["close"].iloc[i - 1], d["open"].iloc[i], d["close"].iloc[i]
        rows.append({"ex": ex, "i": i, "amt": amt, "div_pct": amt / pc, "gap": o / pc - 1,
                     "gross_open": (o + amt * (1 - TAX)) / pc - 1, "drop_per_div": (pc - o) / amt,
                     "r_open": net(pc, o, amt, cost), "r_close": net(pc, c, amt, cost)})
    return pd.DataFrame(rows), skipped


def normal_overnight(d, dv):
    """다음 거래일이 배당락일이 아닌 보통 날: 종가 → 다음 거래일 시가 (비용 전)."""
    nxt = pd.Series(d.index, index=d.index).shift(-1)
    gap = d["open"].shift(-1) / d["close"] - 1
    mask = (d.index >= START) & nxt.notna() & ~nxt.isin(set(dv.index))
    return gap[mask].dropna()


# ---------- 시험 2: A (변동성 돌파) ----------
def volbo_daily(d, dv, cost, conservative=True):
    """일봉만으로 계산. 보수적: 그날 최저가가 손절가 이하면 손절된 것으로 본다."""
    rng = (d["high"] - d["low"]).shift(1)
    target = d["open"] + K * rng
    ok = (rng > 0) & (d["open"] > d["close"].rolling(5).mean().shift(1))
    o, h, l = d["open"].to_numpy(), d["high"].to_numpy(), d["low"].to_numpy()
    out = []
    for i in np.flatnonzero(ok.to_numpy()):
        if d.index[i] < START or i + 1 >= len(d) or h[i] < target.iloc[i]:
            continue
        pe = max(target.iloc[i], o[i])
        sl_px = pe * (1 - SL)
        if conservative and l[i] <= sl_px:
            out.append({"i": i, "x": i, "r": net(pe, sl_px, 0.0, cost), "held_close": False})
        else:
            div = dv.get(d.index[i + 1], 0.0)
            out.append({"i": i, "x": i + 1, "r": net(pe, o[i + 1], div, cost), "held_close": True})
    return pd.DataFrame(out)


def volbo_hourly(h1, dv, cost):
    """1시간봉으로 실제 순서대로. 매수한 봉 안에서 최저가가 손절가 이하면 손절 (보수적)."""
    day = h1.index.normalize()
    days = pd.DatetimeIndex(day.unique())
    g = h1.groupby(day)
    agg = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last()})
    rng = (agg["high"] - agg["low"]).shift(1)
    target = agg["open"] + K * rng
    ok = ((rng > 0) & (agg["open"] > agg["close"].rolling(5).mean().shift(1))).to_numpy()
    o, h, l = h1["open"].to_numpy(), h1["high"].to_numpy(), h1["low"].to_numpy()
    starts = np.searchsorted(day.values, days.values)
    out = []
    for k in range(len(days) - 1):
        if not ok[k]:
            continue
        s, e = starts[k], starts[k + 1]
        hit = np.flatnonzero(h[s:e] >= target.iloc[k])
        if not len(hit):
            continue
        j = s + int(hit[0])
        pe = max(target.iloc[k], o[j])
        sl_px = pe * (1 - SL)
        slh = np.flatnonzero(l[j:e] <= sl_px)
        if len(slh):
            jj = j + int(slh[0])
            px = sl_px if jj == j else min(o[jj], sl_px)
            out.append({"r": net(pe, px, 0.0, cost)})
        else:
            out.append({"r": net(pe, o[e], dv.get(days[k + 1], 0.0), cost)})
    return pd.DataFrame(out)


# ---------- 시험 2: C (RSI2, 1시간봉) ----------
def rsi2_hourly(h1, dv, cost):
    c = h1["close"]
    entries = np.flatnonzero(((c > sma(c, 200)) & (rsi(c, 2) < 5)).to_numpy()) + 1
    exits = np.flatnonzero((c > sma(c, 5)).to_numpy()) + 1
    o, h, l, cc = (h1[k].to_numpy() for k in ("open", "high", "low", "close"))
    e, x, pe, px, kind = simulate(o, h, l, cc, entries, Exit(max_hold=100), exit_sig=exits)
    day = h1.index.normalize()
    first_bar = {dd: int(np.searchsorted(day.values, np.datetime64(dd))) for dd in dv.index if day[0] < dd <= day[-1]}
    out = []
    for a, b, p0, p1 in zip(e, x, pe, px):
        div = sum(amt for dd, amt in dv.items() if dd in first_bar and a < first_bar[dd] <= b)
        out.append({"r": net(p0, p1, div, cost), "bars": int(b - a)})
    return pd.DataFrame(out)


# ---------- 시험 3과 참고 ----------
def combined(d, dv, cost):
    """A(보수적) + A 포지션이 없을 때 배당락 전날 종가 풀매수 → 배당락일 시가 매도."""
    a = volbo_daily(d, dv, cost, True)
    cap, _ = capture(d, dv, cost)
    held = set(a.loc[a["held_close"], "i"]) if len(a) else set()
    extra = cap[~cap["i"].sub(1).isin(held)] if len(cap) else cap
    return a, extra


def hold_with_div(d, dv, cost):
    seg = d[d.index >= START]
    div = dv.reindex(seg.index).fillna(0.0)
    r = (seg["close"] + div * (1 - TAX)) / seg["close"].shift(1) - 1
    v = float(np.prod(1 + r.dropna().to_numpy()))
    return v * (1 - cost.slip) * (1 - cost.fee) / ((1 + cost.slip) * (1 + cost.fee))


def stats(r):
    s = trade_stats(np.asarray(r, dtype=float))
    if s["n"] == 0:
        return {"n": 0}
    return {"n": s["n"], "win_rate": s["win_rate"], "expectancy": s["expectancy"],
            "ci_lo": s["ci_lo"], "ci_hi": s["ci_hi"], "final": float(np.prod(1 + np.asarray(r)))}


def verdict(per, pooled, need_n=1):
    pos = sum(1 for v in per.values() if v.get("n", 0) and v["expectancy"] > 0)
    ok = pooled["n"] >= need_n and pooled["expectancy"] > 0 and pos >= 4
    return ok, pos


def main():
    res = {"tickers": {}, "costs": {k: {"fee": v.fee, "slip": v.slip} for k, v in COSTS.items()}}
    pooled = {k: [] for k in ("cap_event", "cap_basic", "cap_close_event", "A_cons", "A_opt", "A_cons_basic", "A_1h", "C_1h", "C_1h_basic",
                                 "cap_zero", "A_cons_zero", "C_1h_zero")}
    drops, gaps_ex, gaps_norm = [], [], []
    for t in TICKERS:
        d, dv = load(t, "1d")
        h1, _ = load(t, "1h")
        ev, bs = COSTS["event"], COSTS["basic"]
        cap_e, skipped = capture(d, dv, ev)
        cap_b, _ = capture(d, dv, bs)
        norm = normal_overnight(d, dv)
        a_cons = volbo_daily(d, dv, ev, True)
        a_opt = volbo_daily(d, dv, ev, False)
        a_cons_b = volbo_daily(d, dv, bs, True)
        a_1h = volbo_hourly(h1, dv, ev)
        c_1h = rsi2_hourly(h1, dv, ev)
        c_1h_b = rsi2_hourly(h1, dv, bs)
        a3, extra = combined(d, dv, ev)
        first = max(START, d.index[d.index >= START][0])
        r_comb = np.concatenate([a3["r"].to_numpy(), extra["r_open"].to_numpy()]) if len(extra) else a3["r"].to_numpy()
        info = {
            "name": NAMES[t], "from": str(first.date()), "to": str(d.index[-1].date()),
            "h1_from": str(h1.index[0].date()), "n_div": int(len(cap_e)), "div_skipped": skipped,
            "div_per_payment": float(cap_e["div_pct"].mean()),
            "div_per_year": float(dv[(dv.index >= START)].sum() / d["close"][d.index >= START].mean()
                                  / ((d.index[-1] - first).days / 365.25)),
            "drop_per_div_mean": float(cap_e["drop_per_div"].mean()), "drop_per_div_median": float(cap_e["drop_per_div"].median()),
            "ex_gross_open": float(cap_e["gross_open"].mean()), "normal_gap": float(norm.mean()),
            "cap_event": stats(cap_e["r_open"]), "cap_basic": stats(cap_b["r_open"]), "cap_close_event": stats(cap_e["r_close"]),
            "A_cons": stats(a_cons["r"]), "A_opt": stats(a_opt["r"]), "A_cons_basic": stats(a_cons_b["r"]),
            "A_1h": stats(a_1h["r"]) if len(a_1h) else {"n": 0}, "C_1h": stats(c_1h["r"]) if len(c_1h) else {"n": 0},
            "C_1h_basic": stats(c_1h_b["r"]) if len(c_1h_b) else {"n": 0},
            "combo_final": float(np.prod(1 + r_comb)), "combo_extra_n": int(len(extra)),
            "hold_final": hold_with_div(d, dv, ev),
        }
        res["tickers"][t] = info
        pooled["cap_event"] += list(cap_e["r_open"]); pooled["cap_basic"] += list(cap_b["r_open"])
        pooled["cap_close_event"] += list(cap_e["r_close"])
        pooled["A_cons"] += list(a_cons["r"]); pooled["A_opt"] += list(a_opt["r"]); pooled["A_cons_basic"] += list(a_cons_b["r"])
        pooled["A_1h"] += list(a_1h["r"]) if len(a_1h) else []
        pooled["C_1h"] += list(c_1h["r"]) if len(c_1h) else []
        pooled["C_1h_basic"] += list(c_1h_b["r"]) if len(c_1h_b) else []
        pooled["cap_zero"] += list(capture(d, dv, ZERO)[0]["r_open"])
        pooled["A_cons_zero"] += list(volbo_daily(d, dv, ZERO, True)["r"])
        pooled["C_1h_zero"] += list(rsi2_hourly(h1, dv, ZERO)["r"])
        drops += list(cap_e["drop_per_div"]); gaps_ex += list(cap_e["gross_open"]); gaps_norm += list(norm)
    P = {k: stats(v) for k, v in pooled.items()}
    res["pooled"] = P
    res["drop_per_div"] = {"mean": float(np.mean(drops)), "median": float(np.median(drops))}
    res["ex_gross_open_mean"], res["normal_gap_mean"] = float(np.mean(gaps_ex)), float(np.mean(gaps_norm))
    T = res["tickers"]
    v1, pos1 = verdict({t: T[t]["cap_event"] for t in TICKERS}, P["cap_event"])
    vA, posA = verdict({t: T[t]["A_cons"] for t in TICKERS}, P["A_cons"], need_n=100)
    vAo, posAo = verdict({t: T[t]["A_opt"] for t in TICKERS}, P["A_opt"], need_n=100)
    vC, posC = verdict({t: T[t]["C_1h"] for t in TICKERS}, P["C_1h"], need_n=100)
    res["verdict"] = {"test1": v1, "test1_pos": pos1, "A_cons": vA, "A_cons_pos": posA, "A_opt": vAo, "A_opt_pos": posAo,
                      "C": vC, "C_pos": posC}
    (RES / "us_dividend.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    write_md(res)


def pct(x, d=2):
    return f"{x * 100:+.{d}f}%"


def krw(v):
    return f"{START_KRW * v:,.0f}원"


def write_md(res):
    T, P, V = res["tickers"], res["pooled"], res["verdict"]
    L = ["# 미국 배당주: '단타 + 배당락 전날 풀매수' 아이디어 점검", "",
         "사전 등록: research/PREREG_us_dividend.md (데이터 보기 전에 커밋). 계산: research/us_dividend_check.py", "",
         "비용: 수수료 한쪽 0.07%(이벤트 수준) + 슬리피지 0.05%, 배당은 미국 세금 15% 뗀 85%. 환전 비용·매매차익 세금은 뺌.",
         "결과는 과거 데이터 기준이며 미래를 보장하지 않습니다.", "",
         "## 시험 1 — 배당락 전날 종가 풀매수 → 배당락일 시가 매도", "",
         f"- 배당 1달러당 배당락일 시가는 전날 종가보다 평균 **{res['drop_per_div']['mean']:.2f}달러** 낮았음 (중앙값 {res['drop_per_div']['median']:.2f}달러)",
         f"- 배당락일 밤사이 수익(세후 배당 포함, 비용 전) 평균 {pct(res['ex_gross_open_mean'], 3)} vs 보통 날 밤사이 평균 {pct(res['normal_gap_mean'], 3)}",
         f"- 8종목 합친 1회 평균 순손익: 수수료 0.07%면 **{pct(P['cap_event']['expectancy'], 3)}**, 0.25%면 {pct(P['cap_basic']['expectancy'], 3)} "
         f"(거래 {P['cap_event']['n']}회, 이익 본 비율 {P['cap_event']['win_rate'] * 100:.0f}%)",
         f"- 판정: **{'돈이 된다' if V['test1'] else '안 된다'}** (0보다 큰 종목 {V['test1_pos']}/8)", "",
         "| 종목 | 기간 | 배당 1번 크기 | 1달러당 주가 하락 | 1회 순손익 (0.07%) | 1회 순손익 (0.25%) | 매번 했다면 100만원 → |",
         "|---|---|---|---|---|---|---|"]
    for t, v in T.items():
        L.append(f"| {v['name']} | {v['from'][:7]} ~ | {v['div_per_payment'] * 100:.2f}% | {v['drop_per_div_mean']:.2f}달러 | "
                 f"{pct(v['cap_event']['expectancy'], 3)} | {pct(v['cap_basic']['expectancy'], 3)} | {krw(v['cap_event']['final'])} |")
    L += ["", "## 시험 2 — 코인 규칙을 숫자 그대로 배당주에", "",
          f"- A 변동성 돌파 (일봉 10년, 보수적): 거래당 기대값 **{pct(P['A_cons']['expectancy'], 3)}**, 거래 {P['A_cons']['n']}회, "
          f"승률 {P['A_cons']['win_rate'] * 100:.1f}% → **{'통한다(추가 검증 필요)' if V['A_cons'] else '안 통한다'}** (플러스 종목 {V['A_cons_pos']}/8)",
          f"- A 낙관적 계산 (같은 날 손절 무시): 기대값 {pct(P['A_opt']['expectancy'], 3)}, 판정 {'통한다' if V['A_opt'] else '안 통한다'} (플러스 종목 {V['A_opt_pos']}/8)",
          f"- A 1시간봉 최근 2년 (실제 순서): 기대값 {pct(P['A_1h']['expectancy'], 3)}, 거래 {P['A_1h']['n']}회",
          f"- C RSI2 1시간봉 최근 2년: 거래당 기대값 **{pct(P['C_1h']['expectancy'], 3)}**, 거래 {P['C_1h']['n']}회, "
          f"승률 {P['C_1h']['win_rate'] * 100:.1f}% → **{'통한다(추가 검증 필요)' if V['C'] else '안 통한다'}** (플러스 종목 {V['C_pos']}/8)", "",
          "| 종목 | A 거래 | A 기대값 (보수적) | A 기대값 (낙관적) | A 100만원 → (보수적) | C 거래 (2년) | C 기대값 | C 승률 |",
          "|---|---|---|---|---|---|---|---|"]
    for t, v in T.items():
        c = v["C_1h"]
        L.append(f"| {v['name']} | {v['A_cons']['n']} | {pct(v['A_cons']['expectancy'], 3)} | {pct(v['A_opt']['expectancy'], 3)} | "
                 f"{krw(v['A_cons']['final'])} | {c.get('n', 0)} | {pct(c['expectancy'], 3) if c.get('n') else '-'} | "
                 f"{c['win_rate'] * 100:.0f}% |" if c.get("n") else "| - |")
    L += ["", "참고 — 매매 비용이 0이라면 (배당 세금 15%는 그대로):",
          f"- 배당 따먹기 1회 평균 {pct(P['cap_zero']['expectancy'], 3)} (이익 본 비율 {P['cap_zero']['win_rate'] * 100:.0f}%)",
          f"- A 거래당 {pct(P['A_cons_zero']['expectancy'], 3)} (승률 {P['A_cons_zero']['win_rate'] * 100:.0f}%)",
          f"- C 거래당 {pct(P['C_1h_zero']['expectancy'], 3)} (승률 {P['C_1h_zero']['win_rate'] * 100:.0f}%) "
          "→ 자주 이기지만 한 번에 버는 폭이 왕복 비용(약 0.24%)보다 작음"]
    L += ["", "## 시험 3 — 사용자 아이디어 그대로 (A + 배당락 전날 풀매수), 일봉 10년", "",
          "| 종목 | 기간 | A만 | A + 배당락 풀매수 | (참고) 배당 받으며 그냥 들고 있기 |", "|---|---|---|---|---|"]
    for t, v in T.items():
        L.append(f"| {v['name']} | {v['from'][:7]} ~ | {krw(v['A_cons']['final'])} | {krw(v['combo_final'])} | {krw(v['hold_final'])} |")
    L += ["", "100만원은 종목마다 따로 넣었다고 본 값 (환율 변화는 뺌)."]
    (RES / "us_dividend.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
