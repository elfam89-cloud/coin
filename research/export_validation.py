"""추가 검증 결과 → 리포트용 데이터 (results/report/xv_*.json).

필요한 결과 파일: validation_full_btceth.json, validation_y2018.json, validation_old.json,
validation_mid.json, validation_recent5.json, tick_stress_all4.json, report/validation_checks.json
실행: python research/export_validation.py
"""
import json
from pathlib import Path

RES = Path(__file__).resolve().parent.parent / "results"
OUT = RES / "report"
START_KRW = 300_000
RULE_NAME = {"A": "크게 오르기 시작하면 따라 사기 (변동성 돌파, 손절 -3%)", "C": "짧은 급락 때 사기 (RSI2)"}


def load(name):
    return json.loads((RES / f"validation_{name}.json").read_text())


def main():
    full = load("full_btceth")
    summary, years, curve = [], [], []
    for rule in ("A", "C"):
        for cost in ("upbit", "free"):
            u = full["rules"][rule][cost]
            ys = {y: v for y, v in u["years"].items() if v is not None}
            worst_label = min(ys, key=ys.get)
            summary.append({
                "rk": f"{rule}|{cost}", "rule": rule, "cost": cost, "name": RULE_NAME[rule],
                "final_krw": u["final_krw"], "ret": u["ret"], "profit_krw": u["final_krw"] - START_KRW,
                "trades": u["main"]["n"], "win_rate": u["main"]["win_rate"],
                "years_up": sum(v > 0 for v in ys.values()), "years_total": len(ys),
                "worst_year": ys[worst_label], "worst_year_label": worst_label,
                "months_up": u["months"]["up"], "months_total": u["months"]["total"], "worst_month": u["months"]["worst"],
                "low_krw": u["low_krw"], "mdd": u["mdd"],
            })
            for y, v in ys.items():
                years.append({"rk": f"{rule}|{cost}|{y}", "rule": rule, "cost": cost, "year": y, "ret": v})
            c = u["curve"]
            for d, k in list(zip(c["dates"], c["krw"]))[::3]:
                curve.append({"rule": rule, "cost": cost, "date": d, "krw": k})

    # 기간별 시험 (A와 C, 업비트 수수료) — 각 시험에 쓴 코인 그대로
    periods = []
    specs = [("y2018", "2018년 (대폭락장)", "처음 봄 · 사전 등록"), ("old", "2019 ~ 2023.8", "처음 봄 · 사전 등록"),
             ("mid", "2023.10 ~ 2025.9", "1단계에서 규칙을 고른 기간"), ("recent5", "2025.10 ~ 지금 (최근 1년)", "1단계 검증 기간")]
    for i, (name, label, kind) in enumerate(specs):
        v = load(name)
        coins = " · ".join(m.replace("KRW-", "") for m in v["main"])
        for rule in ("A", "C"):
            u = v["rules"][rule]["upbit"]
            periods.append({"rk": f"{rule}|{name}", "order": i, "rule": rule, "period": label, "kind": kind, "coins": coins,
                            "final_krw": u["final_krw"], "ret": u["ret"], "win_rate": u["main"].get("win_rate"),
                            "trades": u["main"].get("n", 0)})

    # 호가 단위 현실 점검 (A, 2018~2026, 4코인 각각 7만 5천원)
    ts = json.loads((RES / "tick_stress_all4.json").read_text())
    ticks = []
    for rule in ("A", "C"):
        for mk, pc in ts[rule]["per_coin"].items():
            ticks.append({"rk": f"{rule}|{mk}", "rule": rule, "coin": mk.replace("KRW-", ""),
                          "tick_pct": pc["avg_tick_slip"], "base_krw": pc["base_final"], "tick_krw": pc["tick_final"], "start_krw": 75_000})

    files = {"xv_summary": summary, "xv_years": years, "xv_curve": curve, "xv_periods": periods, "xv_ticks": ticks}
    for name, data in files.items():
        (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        print(f"{name}.json: {len(data)}행, {(OUT / f'{name}.json').stat().st_size / 1024:.0f}KB")


if __name__ == "__main__":
    main()
