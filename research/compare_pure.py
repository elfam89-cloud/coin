"""'나눠서 보관'(봇 + 비트코인 보유 + 배당주) vs '순수 봇'(생활비만 빼고 나머지는 봇에 그대로) 비교 (2018.1~2026.10)

두 경우 모두 생활비로 쓰는 돈은 매달 똑같은 금액으로 맞춘다 (split_check.py의 금액 그대로).
- 나눠서 보관: 매달 봇 계좌의 1%를 꺼내 생활비 · 배당주(SCHD) · 비트코인으로 나눔 (results/split_plan.md)
- 순수 봇: 같은 생활비만 꺼내고, 나머지는 꺼내지 않고 봇이 계속 굴림
남은 돈은 '봇 + 보유분' 평가액(생활비로 쓴 돈 제외), 달말 기준.
실행: COIN_DATA_DIR=data/merged python -I research/compare_pure.py  (먼저 python research/fetch_us.py)
"""
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import split_check as sc  # noqa: E402
import withdraw_check as wc  # noqa: E402
from validate import load_unit  # noqa: E402

RES = HERE.parent / "results"


def run_bot(withdraw):
    """withdraw(달, 계좌) → 꺼낼 금액. 반환: 달말 계좌(꺼낸 뒤), 달별 꺼낸 돈."""
    per_coin = wc.trade_returns("A", 1)
    acct = [sc.START_KRW / 2, sc.START_KRW / 2]
    prev_end, vals, outs = pd.Timestamp("2017-12-31 23:59"), {}, {}
    for me in sc.MONTHS:
        end = me + pd.Timedelta(hours=23, minutes=59)
        for i, s in enumerate(per_coin):
            for r in s[(s.index > prev_end) & (s.index <= end)]:
                acct[i] = max(0.0, acct[i] * (1 + r))
        v = sum(acct)
        w = min(v, withdraw(me, v))
        acct = [a * (v - w) / v for a in acct] if v > 0 else acct
        vals[me], outs[me] = v - w, w
        prev_end = end
    return pd.Series(vals), pd.Series(outs)


def summarize(wealth, live):
    """달말 남은 돈 경로 → 최종, 최고점 대비 가장 많이 빠진 비율, 연도별 수익률(생활비로 쓴 돈은 더해서 계산)."""
    path = pd.concat([pd.Series({sc.MONTHS[0] - pd.offsets.MonthEnd(1): float(sc.START_KRW)}), wealth])
    dd = float((path / path.cummax() - 1).min())
    years, prev = {}, float(sc.START_KRW)
    for y in sorted(set(wealth.index.year)):
        seg = wealth[wealth.index.year == y]
        years[int(y)] = (float(seg.iloc[-1]) + float(live[live.index.year == y].sum())) / prev - 1
        prev = float(seg.iloc[-1])
    return {"final": float(wealth.iloc[-1]), "mdd": dd, "years": years,
            "worst_year": min(years.values()), "years_up": sum(v > 0 for v in years.values())}


def main():
    w, _ = sc.bot_withdrawals()
    btc = load_unit("KRW-BTC", 5, 5)["close"]
    fx, _ = sc.load_us("USDKRW")
    split_bot, _ = run_bot(lambda me, v: 0.01 * v)
    rows = []
    for name, live, div, coin in sc.SPLITS:
        live_amt = w * live
        wealth = split_bot.copy()
        if coin:
            wealth = wealth + sc.btc_bucket(w * coin, btc)[2]["value"].reindex(wealth.index).fillna(0.0)
        if div:
            wealth = wealth + sc.div_bucket(w * div, "SCHD", fx)[3]["value"].reindex(wealth.index).fillna(0.0)
        pure, _ = run_bot(lambda me, v: float(live_amt[me]))
        rows.append({"name": name, "live": float(live_amt.sum()), "split": summarize(wealth, live_amt), "pure": summarize(pure, live_amt)})
    (RES / "compare_pure.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    write_md(rows)


def write_md(rows):
    man = sc.man
    L = ["# 나눠서 보관 vs 순수 봇 (2018.1 ~ 2026.10, 100만원 시작)", "",
         "두 경우 모두 생활비로 쓴 돈은 매달 같은 금액. 나눠서 보관 = 봇 + 비트코인 보유 + 배당주(SCHD), 순수 봇 = 나머지를 봇에 그대로 둠.",
         "남은 돈 = 생활비로 쓴 돈을 뺀 평가액 (달말 기준, 팔지 않은 값, 매매차익 세금 뺌). 결과는 과거 데이터 기준이며 미래를 보장하지 않습니다.", "",
         "| 나누는 비율 | 생활비로 쓴 돈 (같음) | 순수 봇: 남은 돈 | 나눠서 보관: 남은 돈 | 순수 봇: 최고점 대비 최대 하락 | 나눠서 보관: 최고점 대비 최대 하락 | 순수 봇: 가장 나쁜 해 | 나눠서 보관: 가장 나쁜 해 |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        p, s = r["pure"], r["split"]
        L.append(f"| {r['name']} | {man(r['live'])} | {man(p['final'])} | {man(s['final'])} | {p['mdd'] * 100:+.0f}% | {s['mdd'] * 100:+.0f}% | "
                 f"{p['worst_year'] * 100:+.0f}% | {s['worst_year'] * 100:+.0f}% |")
    r = rows[1]
    L += ["", f"## 연도별 ({r['name']}, 생활비로 쓴 돈을 더해서 계산)", "", "| 연도 | 순수 봇 | 나눠서 보관 |", "|---|---|---|"]
    for y in r["pure"]["years"]:
        L.append(f"| {y}{' (1~10월)' if y == 2026 else ''} | {r['pure']['years'][y] * 100:+.0f}% | {r['split']['years'][y] * 100:+.0f}% |")
    L.append(f"| 플러스인 해 | {r['pure']['years_up']}/{len(r['pure']['years'])} | {r['split']['years_up']}/{len(r['split']['years'])} |")
    (RES / "compare_pure.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
