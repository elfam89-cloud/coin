"""'아예 팔지 않고 배당으로 나오는 돈만 생활비로 쓴다'면? (2018.1~2026.10, 100만원 시작)

1) 봇 + 배당만 쓰기: 봇이 매달 꺼내는 1%로 배당주(와 비트코인)를 사서 팔지 않고, 생활비는 배당금만
2) 봇 없이 배당주만: 2018년 1월 말에 100만원어치 배당주를 사서 팔지 않고, 생활비는 배당금만
비교용: 지금까지 계산한 '꺼낸 1%를 바로 생활비'와 '50 · 25 · 25' (results/split_plan.md)
배당주 예시: SCHD (O 리얼티인컴도 함께 공개). 비용·세금 가정은 split_check.py와 같음.
실행: COIN_DATA_DIR=data/merged python -I research/div_only_check.py  (먼저 python research/fetch_us.py)
"""
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import split_check as sc  # noqa: E402
from validate import load_unit  # noqa: E402

RES = HERE.parent / "results"


def plan(w, ticker, fx, btc, div_share, coin_share, bot_end):
    """꺼낸 돈을 배당주·비트코인으로만 보내고, 생활비는 배당금(현금으로 받음)만."""
    value, monthly, _, _, divs = sc.div_bucket(w * div_share, ticker, fx, reinvest=False)
    coin = sc.btc_bucket(w * coin_share, btc)[0] if coin_share else 0.0
    by_year = divs.groupby(divs.index.year).sum()
    return {"live": float(divs.sum()), "div_now": value, "coin_now": coin, "bot_end": bot_end, "remain": bot_end + value + coin,
            "monthly_now": monthly, "by_year": {int(k): float(v) for k, v in by_year.items()}}


def main():
    w, bot_end = sc.bot_withdrawals()
    btc = load_unit("KRW-BTC", 5, 5)["close"]
    fx, _ = sc.load_us("USDKRW")
    lump = pd.Series(0.0, index=w.index)
    lump.iloc[0] = float(sc.START_KRW)
    res = {}
    for t in ("SCHD", "O"):
        res[t] = {"bot_div100": plan(w, t, fx, btc, 1.0, 0.0, bot_end),
                  "bot_div50_coin50": plan(w, t, fx, btc, 0.5, 0.5, bot_end),
                  "no_bot": plan(lump, t, fx, btc, 1.0, 0.0, 0.0)}
    split = json.loads((RES / "split_plan.json").read_text())
    res["ref"] = {"live100": {"live": split["withdraw_total"], "remain": split["bot_end"]},
                  "split502525": {"live": split["rows"][1]["live"],
                                  "remain": split["rows"][1]["bot_end"] + split["rows"][1]["coin_now"] + split["rows"][1]["SCHD_now"]}}
    (RES / "div_only.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    write_md(res)


def write_md(res):
    man = sc.man
    s, ref = res["SCHD"], res["ref"]
    L = ["# 아예 팔지 않고 배당으로 나오는 돈만 생활비로 쓴다면? (2018.1 ~ 2026.10, 100만원 시작)", "",
         "봇은 변동성 돌파(A), 비트코인·이더리움, 업비트 비용, 매달 계좌의 1%를 꺼냄. 배당주 예시는 SCHD, 배당은 세금 15% 뗀 뒤 생활비로 씀.",
         "남은 돈 = 팔지 않은 평가액 (매매차익 세금 없음). 결과는 과거 데이터 기준이며 미래를 보장하지 않습니다.", "",
         "| 방법 | 9년 동안 생활비로 쓴 돈 | 지금 매달 나오는 배당 | 남은 돈 (봇 + 배당주 + 비트코인) |", "|---|---|---|---|",
         f"| 봇 + 꺼낸 돈 전부 배당주, 생활비는 배당만 | {man(s['bot_div100']['live'])} | {s['bot_div100']['monthly_now']:,.0f}원 | {man(s['bot_div100']['remain'])} |",
         f"| 봇 + 꺼낸 돈 배당주 50 · 비트코인 50, 생활비는 배당만 | {man(s['bot_div50_coin50']['live'])} | {s['bot_div50_coin50']['monthly_now']:,.0f}원 | {man(s['bot_div50_coin50']['remain'])} |",
         f"| 봇 없이 2018년 1월에 배당주 100만원, 생활비는 배당만 | {man(s['no_bot']['live'])} | {s['no_bot']['monthly_now']:,.0f}원 | {man(s['no_bot']['remain'])} |",
         f"| (비교) 봇이 꺼낸 1%를 바로 생활비 | {man(ref['live100']['live'])} | - | {man(ref['live100']['remain'])} |",
         f"| (비교) 생활비 50 · 배당주 25 · 비트코인 25 | {man(ref['split502525']['live'])} | - | {man(ref['split502525']['remain'])} |", "",
         "## 해마다 배당으로 쓴 돈 (월평균)", "", "| 연도 | 봇 + 전부 배당주 | 봇 없이 배당주 100만원 |", "|---|---|---|"]
    for y in s["no_bot"]["by_year"]:
        a, b = s["bot_div100"]["by_year"].get(y, 0.0), s["no_bot"]["by_year"][y]
        months = 10 if y == 2026 else 12
        L.append(f"| {y}{' (1~10월)' if y == 2026 else ''} | {a:,.0f}원 (월 {a / months:,.0f}원) | {b:,.0f}원 (월 {b / months:,.0f}원) |")
    o = res["O"]
    L += ["", f"배당주를 O(리얼티인컴)로 하면: 봇 + 전부 배당주 → 생활비 {man(o['bot_div100']['live'])}, 매달 배당 {o['bot_div100']['monthly_now']:,.0f}원, "
          f"남은 돈 {man(o['bot_div100']['remain'])} / 봇 없이 100만원 → 생활비 {man(o['no_bot']['live'])}, 매달 배당 {o['no_bot']['monthly_now']:,.0f}원, "
          f"남은 돈 {man(o['no_bot']['remain'])}", "", "100만원이 아니라 1,000만원으로 시작하면 모든 금액이 10배입니다."]
    (RES / "div_only.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
