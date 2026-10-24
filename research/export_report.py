"""results/study.json → 리포트(대시보드)용 작은 데이터 파일들 (results/report/*.json).

실행: python research/export_report.py
"""
import json
import os
from pathlib import Path

RES = Path(os.environ.get("COIN_RESULTS_DIR", Path(__file__).resolve().parent.parent / "results"))
OUT = RES / "report"

FAMILY_SHORT = {"pullback": "눌림목", "bb": "볼린저 반등", "rsi2": "RSI(2)", "volbo": "변동성 돌파", "breakout": "고점 돌파"}
TF_SHORT = {"5min": "5분", "15min": "15분", "1h": "1시간", "1D": "일봉"}

# 통과 기준 (PLAN.md 4장과 같은 값)
GATE = {"min_oos_trades": 100, "max_p": 0.05, "max_mdd": -0.20}


def verdict(row, d, cost):
    o = row[f"oos_{cost}_main"]
    x = row[f"oos_{cost}_extra"]
    checks = {
        "기대값+": (o.get("expectancy") or -1) > 0,
        "거래수": o.get("n", 0) >= GATE["min_oos_trades"],
        # p값은 전략과 무작위 진입에 같은 비용이 빠지므로 비용 가정과 무관 → 두 조건 모두 적용
        "무작위대비": d["random_oos"]["p_value"] is not None and d["random_oos"]["p_value"] < GATE["max_p"],
        "낙폭": d[f"port_oos_{cost}"]["mdd"] >= GATE["max_mdd"],
        "새코인": (x.get("expectancy") or -1) > 0,
    }
    failed = [k for k, ok in checks.items() if not ok]
    return ("통과" if not failed else "탈락"), ", ".join(failed)


def main():
    res = json.loads((RES / "study.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    rows = {r["key"]: r for r in res["table"]}
    detail = res["detail"]

    # 후보 순서: 검증 기간 기대값(업비트) 높은 순
    keys = sorted(detail, key=lambda k: -(rows[k]["oos_upbit_main"].get("expectancy") or -9))
    ids = {k: f"c{i + 1}" for i, k in enumerate(keys)}

    cand = []
    for k in keys:
        r, d = rows[k], detail[k]
        a, b = r["is_upbit_main"], r["oos_upbit_main"]
        v_up, why_up = verdict(r, d, "upbit")
        v_fr, why_fr = verdict(r, d, "free_api")
        cand.append({
            "id": ids[k], "label": d["label"], "family": d["family"], "why": ", ".join(d["why"]),
            "short": f"{ids[k]} · {FAMILY_SHORT[d['family']]} {TF_SHORT[r['tf']]}" + (" (원본)" if r["original"] else ""),
            "is_n": a.get("n", 0), "is_wr": a.get("win_rate"), "is_exp": a.get("expectancy"),
            "is_exp_free": r["is_free_api_main"].get("expectancy"),
            "oos_n": b.get("n", 0), "oos_wr": b.get("win_rate"), "oos_exp": b.get("expectancy"),
            "oos_ci_lo": b.get("ci_lo"), "oos_ci_hi": b.get("ci_hi"),
            "oos_exp_free": r["oos_free_api_main"].get("expectancy"),
            "oos_wr_free": r["oos_free_api_main"].get("win_rate"),
            "oos_exp_zero": d["oos_zero_main"].get("expectancy"),
            "oos_pf": b.get("profit_factor"), "oos_payoff": b.get("payoff"),
            "oos_hold_h": (b.get("avg_hold_min") or 0) / 60, "oos_tpd": b.get("trades_per_day"),
            "rand_oos_exp": d["random_oos"]["expectancy"], "rand_oos_wr": d["random_oos"]["win_rate"],
            "p_oos": d["random_oos"]["p_value"], "p_is": d["random_is"]["p_value"],
            "oos_ret": d["port_oos_upbit"]["return"], "oos_mdd": d["port_oos_upbit"]["mdd"],
            "oos_ret_free": d["port_oos_free_api"]["return"], "oos_mdd_free": d["port_oos_free_api"]["mdd"],
            "is_ret": d["port_is_upbit"]["return"],
            "extra_oos_n": r["oos_upbit_extra"].get("n", 0), "extra_oos_exp": r["oos_upbit_extra"].get("expectancy"),
            "extra_oos_exp_free": r["oos_free_api_extra"].get("expectancy"),
            "verdict_upbit": v_up, "fail_upbit": why_up, "verdict_free": v_fr, "fail_free": why_fr,
            "oos_worst": d["oos_worst_trade"], "oos_loss_streak": d["oos_max_loss_streak"],
        })

    random_grid = [{"sl": g["sl"], "tp": g["tp"], "label": f"손절 -{g['sl'] * 100:g}% / 익절 +{g['tp'] * 100:g}%",
                    "wr": g["upbit"]["win_rate"], "exp_upbit": g["upbit"]["expectancy"],
                    "exp_free": g["free_api"]["expectancy"], "exp_zero": g["zero"]["expectancy"]}
                   for g in res["random_grid"]]

    curves = []
    dates = None
    for k in keys:
        d = detail[k]
        dates = d["curve_dates"]
        for dt, v in zip(d["curve_dates"], d["curve_upbit"]):
            curves.append({"date": dt, "series": ids[k], "value": v})
    for dt, v in zip(dates, res["buy_hold"]["curve"]):
        curves.append({"date": dt, "series": "hold", "value": v})

    walk = []
    for cost, w in res["walk_forward"].items():
        for s in w["steps"]:
            walk.append({"cost": cost, "start": s["start"], "end": s["end"], "pick": s["pick"] or "-",
                         "traded": s["traded"], "n": s.get("n", 0), "wr": s.get("win_rate"),
                         "ret": s["return"], "hold_ret": s["hold_return"], "train_exp": s["train_expectancy"]})

    wr = [{"cost": c, "total": w["configs_total"], "wr60": w["is_wr60"], "wr60_prof": w["is_wr60_profitable"],
           "wr60_prof_oos": w["is_wr60_profitable_and_oos_profitable"]} for c, w in res["winrate_check"].items()]

    bh = res["buy_hold"]
    hold = [{"period": p, "ret": bh[p]["return"], "mdd": bh[p]["mdd"]} for p in ("is", "oos", "all")]
    hold_coin = [{"period": p, "coin": mk.replace("KRW-", ""), "ret": v}
                 for p in ("is", "oos") for mk, v in bh[p]["per_coin"].items()]

    monthly = [{"id": ids[k], "month": m, "ret": v} for k in keys for m, v in detail[k]["oos_monthly_upbit"].items()]
    per_coin = [{"id": ids[k], "coin": mk.replace("KRW-", ""), "n": s.get("n", 0), "wr": s.get("win_rate"),
                 "exp": s.get("expectancy")} for k in keys for mk, s in detail[k]["oos_per_coin"].items()]

    # 히트맵은 한 그룹만: 손절·익절 격자를 가진 후보 중 학습 기간 기대값이 가장 높았던 규칙의 격자
    grid_keys = [k for k in keys if detail[k]["family"] in ("pullback", "breakout") and not rows[k]["original"]]
    pick = max(grid_keys, key=lambda k: rows[k]["is_upbit_main"].get("expectancy") or -9) if grid_keys else None
    pick_group = None
    if pick:
        c = rows[pick]
        pick_group = pick.split("|sl=")[0]
    heat = []
    for hk, h in res["heat"].items():
        if hk != pick_group:
            continue
        for c in h["cells"]:
            heat.append({"group": hk, "label": h["label"], "sl": c["sl"], "tp": c["tp"],
                         "is_exp": c["is"], "oos_exp": c["oos"], "is_wr": c["is_wr"], "oos_wr": c["oos_wr"]})

    overview = [{
        "n_configs": res["n_configs"], "n_trades": res["n_trades_simulated"],
        "n_coins": len(res["markets_main"]) + len(res["markets_extra"]),
        "coins_main": " · ".join(m.replace("KRW-", "") for m in res["markets_main"]),
        "coins_extra": " · ".join(m.replace("KRW-", "") for m in res["markets_extra"]),
        "is_start": res["periods"]["is"][0], "is_end": res["periods"]["is"][1],
        "oos_start": res["periods"]["oos"][0], "data_end": res["data_end"][:16],
        "fee_upbit": res["costs"]["upbit"]["fee"], "slip": res["costs"]["upbit"]["slip"],
        "n_candidates": len(cand),
        "n_pass_upbit": sum(c["verdict_upbit"] == "통과" for c in cand),
        "n_pass_free": sum(c["verdict_free"] == "통과" for c in cand),
        "wf_total_upbit": res["walk_forward"]["upbit"]["total_return"],
        "wf_total_free": res["walk_forward"]["free_api"]["total_return"],
        "wf_hold_total": res["walk_forward"]["upbit"]["hold_total_return"],
        "wf_start": res["walk_forward"]["upbit"]["steps"][0]["start"],
        "generated": res["generated"],
    }]

    files = {"overview": overview, "candidates": cand, "random_grid": random_grid, "curves": curves,
             "walk_forward": walk, "winrate_check": wr, "buy_hold": hold, "buy_hold_coin": hold_coin,
             "monthly": monthly, "per_coin": per_coin, "heat": heat}
    for name, data in files.items():
        (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        print(f"{name}.json: {len(data)}행, {(OUT / f'{name}.json').stat().st_size / 1024:.0f}KB")


if __name__ == "__main__":
    main()
