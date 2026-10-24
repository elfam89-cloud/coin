"""2018년부터 지금까지 이어 붙인 결과로 '해마다 플러스였나'를 본다.

A(변동성 돌파), C(RSI2), 그리고 참고로 A+C 반반(15만원씩, 서로 돈을 옮기지 않음).
A+C 반반은 사전 등록에 없던 조합이라 '참고'로만 표시한다.
실행: python research/yearly_check.py   (results/validation_full.json 필요)
"""
import json
from pathlib import Path

import pandas as pd

RES = Path(__file__).resolve().parent.parent / "results"
START_KRW = 300_000


def series(per):
    c = per["curve"]
    return pd.Series(c["krw"], index=pd.to_datetime(c["dates"]), dtype=float) / START_KRW


def yearly(s):
    out, prev = {}, 1.0
    for y, seg in s.groupby(s.index.year):
        out[int(y)] = float(seg.iloc[-1] / prev - 1)
        prev = seg.iloc[-1]
    return out


def monthly(s):
    m = s.resample("MS").last()
    r = m / pd.concat([pd.Series([1.0]), m.iloc[:-1]]).to_numpy() - 1
    return r.dropna()


def main(name="full_btceth"):
    full = json.loads((RES / f"validation_{name}.json").read_text())
    rows, L = [], ["# 2018년부터 해마다 플러스였나", "",
                   f"기간: {full['start']} ~ {full['end'][:10]} · 코인: {' · '.join(m.replace('KRW-', '') for m in full['main'])}",
                   f"30만원을 코인 {len(full['main'])}개에 똑같이 나눔. A+C 반반은 두 규칙에 절반씩(사전 등록에 없던 참고용 조합).",
                   "리플·에이다는 옛날 호가 단위가 커서 실제 체결 손해가 컸으므로 제외(research/tick_stress.py 참고).", ""]
    for cost in ("upbit", "free"):
        a, c = series(full["rules"]["A"][cost]), series(full["rules"]["C"][cost])
        both = (a + c) / 2
        hold = pd.Series(full["hold"]["curve"]["krw"], index=pd.to_datetime(full["hold"]["curve"]["dates"]), dtype=float) / START_KRW
        curves = {"A": a, "C": c, "AC": both, "hold": hold}
        ys = {k: yearly(v) for k, v in curves.items()}
        ms = {k: monthly(v) for k, v in curves.items()}
        title = "업비트 수수료" if cost == "upbit" else "수수료 무료 거래소"
        L += [f"## {title}", "", "| 연도 | A 변동성 돌파 | C 짧은 급락 때 사기 | A+C 반반 (참고) | 그냥 들고 있기 (참고) |", "|---|---|---|---|---|"]
        for y in sorted(ys["A"]):
            L.append(f"| {y}{' (1~10월)' if y == 2026 else ''} | " + " | ".join(f"{ys[k].get(y, float('nan')) * 100:+.1f}%" for k in ("A", "C", "AC", "hold")) + " |")
            for k in ("A", "C", "AC", "hold"):
                rows.append({"rk": f"{k}|{cost}|{y}", "rule": k, "cost": cost, "year": str(y), "ret": ys[k].get(y)})
        L.append("| **합계 (30만원 →)** | " + " | ".join(f"**{START_KRW * curves[k].iloc[-1]:,.0f}원**" for k in ("A", "C", "AC", "hold")) + " |")
        L.append("| 플러스인 해 | " + " | ".join(f"{sum(v > 0 for v in ys[k].values())}/{len(ys[k])}" for k in ("A", "C", "AC", "hold")) + " |")
        L.append("| 가장 나쁜 해 | " + " | ".join(f"{min(ys[k].values()) * 100:+.1f}%" for k in ("A", "C", "AC", "hold")) + " |")
        L.append("| 이익 본 달 | " + " | ".join(f"{(ms[k] > 0).sum()}/{len(ms[k])}" for k in ("A", "C", "AC", "hold")) + " |")
        L.append("| 가장 나쁜 달 | " + " | ".join(f"{ms[k].min() * 100:+.1f}%" for k in ("A", "C", "AC", "hold")) + " |")
        L.append("| 가장 적을 때 | " + " | ".join(f"{START_KRW * curves[k].min():,.0f}원" for k in ("A", "C", "AC", "hold")) + " |")
        L.append("")
        for k in ("A", "C", "AC", "hold"):
            rows.append({"rk": f"{k}|{cost}|total", "rule": k, "cost": cost, "year": "total",
                         "ret": float(curves[k].iloc[-1] - 1), "final_krw": round(START_KRW * curves[k].iloc[-1]),
                         "years_up": int(sum(v > 0 for v in ys[k].values())), "years_total": len(ys[k]),
                         "worst_year": float(min(ys[k].values())), "months_up": int((ms[k] > 0).sum()),
                         "months_total": int(len(ms[k])), "worst_month": float(ms[k].min()),
                         "low_krw": round(START_KRW * curves[k].min())})
        if cost == "upbit":
            curve_rows = []
            for k in ("A", "C", "AC"):
                s = curves[k]
                for d, v in list(zip(s.index, s.to_numpy()))[::5]:
                    curve_rows.append({"id": k, "date": d.strftime("%Y-%m-%d"), "krw": round(START_KRW * v)})
    (RES / "yearly_summary.md").write_text("\n".join(L) + "\n")
    out = RES / "report"
    out.mkdir(exist_ok=True)
    print("\n".join(L))


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "full_btceth")
