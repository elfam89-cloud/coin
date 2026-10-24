"""미래 재테크 계획: 시드 100만원 + 매달 10만원을 봇 · 비트코인 · 배당주 비율로 나눠 넣으면? (2018.1~2026.10)

- 들어오는 돈(시작 100만원, 매달 말 10만원)은 정한 비율로 봇 · 비트코인 · 배당주에 나눠 넣는다.
- 봇(A, BTC·ETH 반반, 업비트 비용)은 매달 말 계좌의 1%를 꺼내 비트코인 · 배당주에 같은 비율로 옮긴다 (봇 수익으로 보유분을 늘림).
- 비트코인 · 배당주는 팔지 않는다. 배당은 세금 15% 떼고 다시 산다. 생활비 인출 없음. 배당주 예시는 SCHD (O도 함께 공개).
- 연도별 성적과 최대 하락은 넣은 돈을 뺀 '시간가중 수익률'로 본다.
실행: COIN_DATA_DIR=data/merged python -I research/future_plan.py  (먼저 python research/fetch_us.py)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import split_check as sc  # noqa: E402
import withdraw_check as wc  # noqa: E402
from validate import load_unit  # noqa: E402

RES = HERE.parent / "results"
SEED, MONTHLY = 1_000_000, 100_000
START = pd.Timestamp("2017-12-31")  # 시드는 2018년 1월 1일 시작 직전 가격으로 산다
PLANS = [("봇만 (100 · 0 · 0)", 1.0, 0.0, 0.0), ("50 · 25 · 25", 0.5, 0.25, 0.25), ("40 · 30 · 30", 0.4, 0.3, 0.3),
         ("3분의 1씩", 1 / 3, 1 / 3, 1 / 3), ("봇 없이 (0 · 50 · 50, 참고)", 0.0, 0.5, 0.5)]
MIX = [("40 · 40 · 20 (비트코인 많이)", 0.4, 0.4, 0.2), ("40 · 30 · 30", 0.4, 0.3, 0.3), ("40 · 20 · 40 (배당주 많이)", 0.4, 0.2, 0.4)]


def run_bot(seed, contrib, transfer):
    """contrib: 달별 봇에 넣는 돈. transfer=True면 매달 말 계좌의 1%를 꺼냄. 반환: 달말 계좌, 달별 꺼낸 돈."""
    per_coin = wc.trade_returns("A", 1)
    acct = [seed / 2, seed / 2]
    prev_end, vals, outs = pd.Timestamp("2017-12-31 23:59"), {}, {}
    for me in sc.MONTHS:
        end = me + pd.Timedelta(hours=23, minutes=59)
        for i, s in enumerate(per_coin):
            for r in s[(s.index > prev_end) & (s.index <= end)]:
                acct[i] = max(0.0, acct[i] * (1 + r))
        out = 0.01 * sum(acct) if transfer else 0.0
        acct = [a * (0.99 if transfer else 1.0) + float(contrib[me]) / 2 for a in acct]
        vals[me], outs[me] = sum(acct), out
        prev_end = end
    return pd.Series(vals), pd.Series(outs)


def simulate(bot_s, coin_s, div_s, btc, fx, ticker="SCHD", transfer=True, skip_every=0):
    """skip_every=4면 4달에 한 번은 10만원을 못 넣는다고 가정."""
    contrib = pd.Series([0.0 if skip_every and (k + 1) % skip_every == 0 else float(MONTHLY) for k in range(len(sc.MONTHS))], index=sc.MONTHS)
    hold = coin_s + div_s
    bot_vals, outs = run_bot(SEED * bot_s, contrib * bot_s, transfer and hold > 0)
    idx = pd.DatetimeIndex([START]).append(sc.MONTHS)
    to_coin = pd.Series(0.0, index=idx)
    to_div = pd.Series(0.0, index=idx)
    to_coin[START], to_div[START] = SEED * coin_s, SEED * div_s
    if hold > 0:
        to_coin[sc.MONTHS] = contrib * coin_s + outs * coin_s / hold
        to_div[sc.MONTHS] = contrib * div_s + outs * div_s / hold
    coin_end, _, coin_path = sc.btc_bucket(to_coin, btc) if coin_s else (0.0, None, None)
    div_end, div_monthly, _, div_path, _ = sc.div_bucket(to_div, ticker, fx) if div_s else (0.0, 0.0, None, None, None)
    wealth = bot_vals.copy()
    if coin_s:
        wealth += coin_path["value"].reindex(sc.MONTHS).to_numpy()
    if div_s:
        wealth += div_path["value"].reindex(sc.MONTHS).to_numpy()
    # 넣은 돈을 뺀 달별 수익률 → 시간가중 지수
    prev = np.concatenate([[float(SEED)], wealth.to_numpy()[:-1]])
    r = (wealth.to_numpy() - contrib.to_numpy()) / prev - 1
    index = pd.Series(np.cumprod(1 + r), index=sc.MONTHS)
    years, last = {}, 1.0
    for y in sorted(set(index.index.year)):
        v = float(index[index.index.year == y].iloc[-1])
        years[int(y)] = v / last - 1
        last = v
    invested = SEED + contrib.cumsum()
    rel = wealth / invested - 1
    return {"invested": float(invested.iloc[-1]), "bot": float(bot_vals.iloc[-1]), "coin": coin_end, "div": div_end,
            "total": float(bot_vals.iloc[-1]) + coin_end + div_end, "div_monthly": div_monthly,
            "mdd": float((index / index.cummax() - 1).min()), "years": years, "worst_year": min(years.values()),
            "years_up": sum(v > 0 for v in years.values()), "worst_vs_in": float(rel.min()), "worst_vs_in_month": rel.idxmin().strftime("%Y-%m")}


def main():
    btc = load_unit("KRW-BTC", 5, 5)["close"]
    fx, _ = sc.load_us("USDKRW")
    res = {"plans": [], "mix": [], "extra": {}}
    for name, b, c, d in PLANS:
        res["plans"].append({"name": name, **simulate(b, c, d, btc, fx)})
    for name, b, c, d in MIX:
        res["mix"].append({"name": name, **simulate(b, c, d, btc, fx)})
    res["extra"]["no_transfer"] = simulate(0.4, 0.3, 0.3, btc, fx, transfer=False)
    res["extra"]["skip4"] = simulate(0.4, 0.3, 0.3, btc, fx, skip_every=4)
    res["extra"]["O"] = simulate(0.4, 0.3, 0.3, btc, fx, ticker="O")
    (RES / "future_plan.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    write_md(res)


def write_md(res):
    man = sc.man
    L = ["# 미래 재테크 계획: 시드 100만원 + 매달 10만원 → 봇 · 비트코인 · 배당주 (2018.1 ~ 2026.10)", "",
         "들어오는 돈은 비율대로 나눠 넣고, 봇은 매달 계좌의 1%를 비트코인 · 배당주로 옮김. 비트코인 · 배당주는 팔지 않고 배당은 다시 투자 (배당주 = SCHD 예시).",
         "봇 = 변동성 돌파(A), 비트코인·이더리움, 업비트 비용. 팔지 않은 평가액이며 세금(매매차익)은 뺌. 결과는 과거 데이터 기준이며 미래를 보장하지 않습니다.", "",
         f"넣은 돈 합계: {man(res['plans'][0]['invested'])} (시드 100만원 + 10만원 × {len(sc.MONTHS)}개월)", "",
         "| 비율 (봇 · 비트코인 · 배당주) | 지금 가치 | 봇 | 비트코인 | 배당주 | 지금 매달 배당 | 플러스인 해 | 가장 나쁜 해 | 최고점 대비 최대 하락 | 넣은 돈보다 가장 적었을 때 |",
         "|---|---|---|---|---|---|---|---|---|---|"]

    def row(p):
        return (f"| {p['name']} | **{man(p['total'])}** | {man(p['bot'])} | {man(p['coin'])} | {man(p['div'])} | {p['div_monthly']:,.0f}원 | "
                f"{p['years_up']}/{len(p['years'])} | {p['worst_year'] * 100:+.0f}% | {p['mdd'] * 100:+.0f}% | {p['worst_vs_in'] * 100:+.0f}% ({p['worst_vs_in_month']}) |")
    L += [row(p) for p in res["plans"]]
    header = L[7:9]
    L += ["", "## 봇 40%일 때 비트코인 : 배당주 비율", "", *header]
    L += [row(p) for p in res["mix"]]
    e = res["extra"]
    L += ["", "## 40 · 30 · 30 기준 참고", "",
          f"- 봇 수익을 옮기지 않고 봇에 그대로 두면: 지금 가치 {man(e['no_transfer']['total'])} (봇 {man(e['no_transfer']['bot'])}), "
          f"가장 나쁜 해 {e['no_transfer']['worst_year'] * 100:+.0f}%",
          f"- 4달에 한 번은 10만원을 못 넣으면: 넣은 돈 {man(e['skip4']['invested'])} → 지금 가치 {man(e['skip4']['total'])}",
          f"- 배당주를 O(리얼티인컴)로 하면: 지금 가치 {man(e['O']['total'])}, 지금 매달 배당 {e['O']['div_monthly']:,.0f}원", "",
          "## 연도별 (넣은 돈을 뺀 수익률)", "", "| 연도 | " + " | ".join(p["name"] for p in res["plans"]) + " |",
          "|---|" + "---|" * len(res["plans"])]
    for y in res["plans"][0]["years"]:
        L.append(f"| {y}{' (1~10월)' if y == 2026 else ''} | " + " | ".join(f"{p['years'][y] * 100:+.0f}%" for p in res["plans"]) + " |")
    (RES / "future_plan.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
