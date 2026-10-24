"""봇이 매달 꺼내는 돈(계좌의 1%)을 생활비 · 배당주 · 비트코인 보유로 나누면? (2018.1~2026.10)

봇: 규칙 A(변동성 돌파, 손절 -3%), 비트코인·이더리움 50만원씩, 업비트 비용, 레버리지 1배 (PLAN 3-7과 같음).
매달 말에 봇 계좌의 1%를 꺼내 정해진 비율로 나눈다.
- 비트코인 보유: 그날 업비트 가격으로 산다 (수수료 0.05% + 슬리피지 0.05%). 팔지 않고 끝까지 들고 있음.
- 배당주: 그날 환율로 달러로 바꿔(환전 비용 0.1%) 미국 종가로 산다 (수수료 0.07% + 슬리피지 0.05%).
  배당은 미국 세금 15%를 떼고 같은 주식을 다시 산다. 예시 2개: SCHD(배당성장형), O(리얼티인컴, 매달 배당).
- 생활비: 꺼낸 그대로 쓴다.
실행: python research/fetch_us.py && COIN_DATA_DIR=data/merged python -I research/split_check.py
"""
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import withdraw_check as wc  # noqa: E402
from validate import load_unit  # noqa: E402

ROOT = HERE.parent
US = ROOT / "data" / "us"
RES = ROOT / "results"
START_KRW = wc.START_KRW
MONTHS = pd.date_range("2018-01-31", "2026-10-31", freq="ME")
SPLITS = [("생활비 100% (지금까지 계획)", 1.0, 0.0, 0.0), ("생활비 50 · 배당주 25 · 비트코인 25", 0.5, 0.25, 0.25),
          ("3분의 1씩", 1 / 3, 1 / 3, 1 / 3), ("생활비 0 · 배당주 50 · 비트코인 50 (모으기만)", 0.0, 0.5, 0.5)]
UPBIT = (1 + 0.0005) * (1 + 0.0005)
FX_SPREAD, US_FEE, US_SLIP, TAX = 0.001, 0.0007, 0.0005, 0.15


def bot_withdrawals():
    """3-7의 '매달 계좌의 1%' 규칙. 반환: 달별 인출액, 마지막 봇 계좌."""
    per_coin = wc.trade_returns("A", 1)
    acct = [START_KRW / 2, START_KRW / 2]
    prev_end, out = pd.Timestamp("2017-12-31 23:59"), {}
    for me in MONTHS:
        end = me + pd.Timedelta(hours=23, minutes=59)
        for i, s in enumerate(per_coin):
            for r in s[(s.index > prev_end) & (s.index <= end)]:
                acct[i] = max(0.0, acct[i] * (1 + r))
        out[me] = 0.01 * sum(acct)
        acct = [a * 0.99 for a in acct]
        prev_end = end
    return pd.Series(out), sum(acct)


def load_us(name):
    j = json.loads((US / f"{name}_1d.json").read_text())["chart"]["result"][0]
    tz = j["meta"]["exchangeTimezoneName"]
    idx = pd.to_datetime(j["timestamp"], unit="s", utc=True).tz_convert(tz).tz_localize(None).normalize()
    px = pd.Series(j["indicators"]["quote"][0]["close"], index=idx, dtype=float).dropna()
    px = px[px > 0]
    px = px[~px.index.duplicated(keep="last")].sort_index()
    ev = j.get("events", {}).get("dividends", {})
    dv = pd.Series({pd.Timestamp(v["date"], unit="s", tz="UTC").tz_convert(tz).tz_localize(None).normalize(): float(v["amount"])
                    for v in ev.values()}, dtype=float).sort_index()
    return px, dv.groupby(level=0).sum()


def worst(path):
    """달말 평가액 경로 → (넣은 돈 대비 가장 나빴던 때, 그 달)."""
    rel = path["value"] / path["invested"] - 1
    return float(rel.min()), rel.idxmin().strftime("%Y-%m")


def btc_bucket(amounts, btc):
    units, inv, path = 0.0, 0.0, []
    for me, a in amounts.items():
        p = float(btc.asof(me + pd.Timedelta(hours=23, minutes=55)))
        if a > 0:
            units += a / (p * UPBIT)
            inv += a
        path.append({"month": me, "value": units * p, "invested": inv})
    path = pd.DataFrame(path).set_index("month")
    return units * float(btc.iloc[-1]), worst(path), path


def div_bucket(amounts, ticker, fx, reinvest=True):
    """reinvest=False면 배당을 다시 사지 않고 현금(생활비)으로 받는다.
    반환: 지금 가치, 지금 매달 나오는 배당, 가장 나빴던 때, 달별 경로, 받은 배당(원, 세후)."""
    px, dv = load_us(ticker)
    buy_mult = (1 + US_SLIP) * (1 + US_FEE)
    events = [(me, 1, a) for me, a in amounts.items() if a > 0]                                   # 매달 말 매수
    events += [(d, 0, amt) for d, amt in dv.items() if MONTHS[0] - pd.Timedelta("31D") < d <= px.index[-1]]  # 배당락일 (같은 날이면 먼저)
    shares, inv, path, divs = 0.0, 0.0, [], {}
    for d, kind, v in sorted(events):
        p = float(px.asof(d))
        if kind == 1:
            shares += v / (float(fx.asof(d)) * (1 + FX_SPREAD)) / (p * buy_mult)
            inv += v
            path.append({"month": d, "value": shares * p * float(fx.asof(d)), "invested": inv})
        else:
            divs[d] = shares * v * (1 - TAX) * float(fx.asof(d))
            if reinvest:
                shares += shares * v * (1 - TAX) / (p * buy_mult)
    last12 = dv[dv.index > px.index[-1] - pd.Timedelta("365D")].sum()
    fx_last = float(fx.iloc[-1])
    path = pd.DataFrame(path).set_index("month")
    return (shares * float(px.iloc[-1]) * fx_last, shares * last12 * (1 - TAX) * fx_last / 12, worst(path), path,
            pd.Series(divs, dtype=float))


def main():
    w, bot_end = bot_withdrawals()
    btc = load_unit("KRW-BTC", 5, 5)["close"]
    fx, _ = load_us("USDKRW")
    rows = []
    for name, live, div, coin in SPLITS:
        coin_now, coin_worst, _ = btc_bucket(w * coin, btc) if coin else (0.0, (0.0, "-"), None)
        r = {"name": name, "live": float(w.sum() * live), "coin_in": float(w.sum() * coin), "div_in": float(w.sum() * div),
             "coin_now": coin_now, "coin_worst": coin_worst, "bot_end": bot_end}
        for t in ("SCHD", "O"):
            v, monthly, wst, _, _ = div_bucket(w * div, t, fx) if div else (0.0, 0.0, (0.0, "-"), None, None)
            r[f"{t}_now"], r[f"{t}_monthly"], r[f"{t}_worst"] = v, monthly, wst
        rows.append(r)
    res = {"withdraw_total": float(w.sum()), "withdraw_first": float(w.iloc[0]), "withdraw_last": float(w.iloc[-1]),
           "months": len(w), "bot_end": bot_end, "fx_first": float(fx.asof(MONTHS[0])), "fx_last": float(fx.iloc[-1]),
           "btc_first": float(btc.asof(MONTHS[0] + pd.Timedelta(hours=23, minutes=55))), "btc_last": float(btc.iloc[-1]), "rows": rows}
    # 배당 자세히: 두 번째 비율(생활비 50 · 배당주 25 · 비트코인 25), SCHD — 다시 사기 vs 생활비로 쓰기
    div1 = SPLITS[1][2]
    d_re = div_bucket(w * div1, "SCHD", fx)[4]
    v_cash, _, _, _, d_cash = div_bucket(w * div1, "SCHD", fx, reinvest=False)
    px, dv = load_us("SCHD")
    dps, yend = dv.groupby(dv.index.year).sum(), px.groupby(px.index.year).last()
    res["div_detail"] = {"total": float(d_re.sum()), "by_year": {int(k): float(v) for k, v in d_re.groupby(d_re.index.year).sum().items()},
                         "cash_total": float(d_cash.sum()), "value_cash": v_cash,
                         "dps": {int(k): float(v) for k, v in dps.items() if k >= 2018},
                         "px_2021": float(yend[2021]), "px_2022": float(yend[2022])}
    (RES / "split_plan.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    write_md(res)


def man(x):
    return f"{x / 10_000:,.1f}만원"


def write_md(res):
    L = ["# 봇이 매달 꺼내는 돈을 생활비 · 배당주 · 비트코인 보유로 나누면? (2018.1 ~ 2026.10)", "",
         "조건: 100만원으로 시작, 변동성 돌파(A) 봇, 비트코인·이더리움, 업비트 수수료, 레버리지 1배. 매달 말 봇 계좌의 1%를 꺼냄 (PLAN 3-7).",
         f"9년 동안 꺼낸 돈 합계 {res['withdraw_total']:,.0f}원 ({res['months']}개월, 첫 달 {res['withdraw_first']:,.0f}원 → 마지막 달 {res['withdraw_last']:,.0f}원). "
         f"봇 계좌는 마지막에 {res['bot_end']:,.0f}원.", "",
         "비트코인은 업비트 수수료, 배당주는 환전 0.1% + 수수료 0.07% + 슬리피지 0.05%, 배당 세금 15% 뗀 뒤 다시 투자. 팔지 않은 평가액이며 매매차익 세금은 뺌.",
         f"환율 {res['fx_first']:,.0f}원 → {res['fx_last']:,.0f}원, 비트코인 {res['btc_first'] / 1e4:,.0f}만원 → {res['btc_last'] / 1e4:,.0f}만원 (2018년 1월 말 → 지금).",
         "결과는 과거 데이터 기준이며 미래를 보장하지 않습니다.", "",
         "| 나누는 비율 | 생활비로 쓴 돈 | 비트코인 (넣은 돈 → 지금) | 배당주 SCHD (넣은 돈 → 지금) | SCHD에서 지금 매달 나오는 배당 | 배당주 O로 했다면 (지금 / 매달 배당) | 봇 계좌 | 남은 돈 합계 (봇 + 비트 + SCHD) |",
         "|---|---|---|---|---|---|---|---|"]
    for r in res["rows"]:
        L.append(f"| {r['name']} | {man(r['live'])} | {man(r['coin_in'])} → {man(r['coin_now'])} | {man(r['div_in'])} → {man(r['SCHD_now'])} | "
                 f"{r['SCHD_monthly']:,.0f}원 | {man(r['O_now'])} / {r['O_monthly']:,.0f}원 | {man(r['bot_end'])} | "
                 f"{man(r['bot_end'] + r['coin_now'] + r['SCHD_now'])} |")
    r = res["rows"][1]
    L += ["", "중간에 가장 나빴던 때 (넣은 돈 대비 평가액, 달말 기준 — 비율은 나누는 비율과 상관없이 같음):",
          f"- 비트코인 보유분: {r['coin_worst'][0] * 100:+.0f}% ({r['coin_worst'][1]})",
          f"- 배당주 SCHD: {r['SCHD_worst'][0] * 100:+.0f}% ({r['SCHD_worst'][1]}) / O: {r['O_worst'][0] * 100:+.0f}% ({r['O_worst'][1]})"]
    dd = res["div_detail"]
    L += ["", f"## 배당은 어떻게 계산했나 ({r['name']}, SCHD)", "",
          "- 배당은 미국 세금 15%를 떼고 같은 주식을 다시 샀음 → 위 표의 '지금' 금액에 이미 들어 있음",
          f"- 9년 동안 받은 배당 합계 {dd['total']:,.0f}원 (세후). 해마다: " + " · ".join(f"{y}년 {v:,.0f}원" for y, v in dd["by_year"].items()),
          f"- 배당을 다시 사지 않고 생활비로 쓰면: 생활비 {man(r['live'])} → {man(r['live'] + dd['cash_total'])}, "
          f"배당주 {man(r['SCHD_now'])} → {man(dd['value_cash'])}",
          "- SCHD 1주당 배당(달러, 분할 반영): " + " · ".join(f"{y}년 {v:.2f}" for y, v in dd["dps"].items() if y < 2026)
          + f". 2022년 주가가 {dd['px_2022'] / dd['px_2021'] * 100 - 100:+.0f}%일 때 배당은 {dd['dps'][2022] / dd['dps'][2021] * 100 - 100:+.0f}%",
          "", "100만원이 아니라 1,000만원으로 시작하면 모든 금액이 10배입니다."]
    (RES / "split_plan.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
