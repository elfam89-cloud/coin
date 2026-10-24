"""results/study.json → 리포트(대시보드)용 데이터 파일 (results/report/*.json).

초보자용 리포트에 필요한 것만 만든다: 규칙별 승률·누적수익률·30만원 기준 수익금, 계좌 곡선, 월별 손익.
실행: python research/export_report.py
"""
import json
import os
from pathlib import Path

RES = Path(os.environ.get("COIN_RESULTS_DIR", Path(__file__).resolve().parent.parent / "results"))
OUT = RES / "report"
START_KRW = 300_000  # 사용자가 계획한 실전 금액(20~30만원) 기준

# 통과 기준 (PLAN.md 4장과 같은 값)
GATE = {"min_oos_trades": 100, "max_p": 0.05, "max_mdd": -0.20}
COST_KEY = {"upbit": "upbit", "free": "free_api"}


def plain_name(d, row):
    """규칙을 초보자가 알아볼 수 있는 이름과 한 줄 설명으로."""
    fam, sl, tp = d["family"], row["sl"], row["tp"]
    exit_txt = (f"+{tp * 100:g}%에 익절, " if tp else "") + (f"-{sl * 100:g}%에 손절" if sl else "손절 없음")
    if fam == "rsi2":
        return ("짧은 급락 때 사기 (RSI2)",
                "1시간봉에서 짧은 기간에 많이 떨어지면(RSI2가 5 미만) 사고, 5시간 평균 위로 회복하면 판다. 큰 흐름이 상승일 때만.")
    if fam == "volbo":
        return ("크게 오르기 시작하면 따라 사기 (변동성 돌파)",
                "오늘 시작가 + 어제 움직인 폭의 절반을 넘는 순간 사고, 다음날 아침 9시에 판다. 5일 평균보다 높게 시작한 날만.")
    if fam == "bb":
        return ("평소보다 많이 빠지면 사기 (볼린저밴드)",
                f"15분봉이 볼린저밴드 아래로 빠지고 과매도(RSI 30 미만)면 사고, 가운데 선으로 돌아오면 판다. {exit_txt}.")
    if fam == "breakout":
        return (f"최근 최고가를 넘으면 사기 (익절 +{tp * 100:g}%)",
                f"1시간봉이 거래량 급증과 함께 최근 20시간 최고가를 넘으면 산다. {exit_txt}.")
    if fam == "pullback":
        if row["original"]:
            pts = "5개 모두" if "5점" in d["label"] else "4개 이상"
            return (f"이전 세션 원본 규칙 ({pts})",
                    f"이전 세션의 눌림목 체크리스트 5개 중 {pts} 맞으면 산다. {exit_txt}.")
        return (f"이전 세션 체크리스트 (익절 +{tp * 100:g}%)",
                f"이전 세션의 눌림목 체크리스트를 1시간봉에 적용하고 {exit_txt}.")
    return (d["label"], d["label"])


def verdict(row, d, cost):
    o, x = row[f"oos_{cost}_main"], row[f"oos_{cost}_extra"]
    p = d["random_oos"]["p_value"]
    checks = {
        "이익": (o.get("expectancy") or -1) > 0,
        "거래 수": o.get("n", 0) >= GATE["min_oos_trades"],
        "운이 아님": p is not None and p < GATE["max_p"],
        "손실 폭": d[f"port_oos_{cost}"]["mdd"] >= GATE["max_mdd"],
        "새 코인": (x.get("expectancy") or -1) > 0,
    }
    failed = [k for k, ok in checks.items() if not ok]
    return ("통과" if not failed else "탈락"), ", ".join(failed)


def weekly(dates, values):
    """3년치 그래프는 7일 간격으로 줄인다 (마지막 날은 항상 포함)."""
    pts = list(zip(dates, values))
    return [p for i, p in enumerate(pts) if i % 7 == 0 or i == len(pts) - 1]


def monthly_profit(dates, values):
    """일별 계좌 가치(시작 1.0) → 달마다 번 돈(원)."""
    out, prev, cur_m, last = [], 1.0, None, None
    for dt, v in zip(dates, values):
        m = dt[:7]
        if cur_m is not None and m != cur_m:
            out.append((cur_m, (last - prev) * START_KRW))
            prev = last
        cur_m, last = m, v
    if cur_m is not None:
        out.append((cur_m, (last - prev) * START_KRW))
    return out


def main():
    res = json.loads((RES / "study.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    rows = {r["key"]: r for r in res["table"]}
    detail = res["detail"]
    bh = res["buy_hold"]

    examples = [k for k, d in detail.items() if any(w.startswith("예시") for w in d["why"])]
    cands = [k for k in detail if k not in examples]
    # 번호는 최근 1년(업비트 비용) 계좌 수익률이 좋은 순
    cands.sort(key=lambda k: -detail[k]["port_oos_upbit"]["return"])
    ids = {k: f"c{i + 1}" for i, k in enumerate(cands)}
    ids.update({k: f"ex{i + 1}" for i, k in enumerate(examples)})

    board, curve, monthly = [], [], []
    for k in cands + examples:
        r, d = rows[k], detail[k]
        name, desc = plain_name(d, r)
        for cost, ck in COST_KEY.items():
            v_txt, v_fail = verdict(r, d, ck)
            for period in ("recent", "all"):
                st = r[f"oos_{ck}_main"] if period == "recent" else d[f"all_{ck}_main"]
                port = d[f"port_{'oos' if period == 'recent' else 'all'}_{ck}"]
                ret = port["return"]
                board.append({
                    "rk": f"{ids[k]}|{period}|{cost}", "id": ids[k], "kind": "example" if k in examples else "rule",
                    "name": name, "desc": desc, "period": period, "cost": cost,
                    "trades": st.get("n", 0), "win_rate": st.get("win_rate"),
                    "avg_win": st.get("avg_win"), "avg_loss": st.get("avg_loss"),
                    "hold_h": round((st.get("avg_hold_min") or 0) / 60, 1),
                    "ret": ret, "final_krw": round(START_KRW * (1 + ret)), "profit_krw": round(START_KRW * ret),
                    "low_krw": round(START_KRW * port["min"]),
                    "verdict": v_txt, "fail": v_fail,
                })
            for dt, v in zip(d["curve_oos_dates"], d[f"curve_oos_{ck}"]):
                curve.append({"period": "recent", "cost": cost, "id": ids[k], "date": dt, "krw": round(START_KRW * v)})
            for dt, v in weekly(d["curve_dates"], d[f"curve_{ck}"]):
                curve.append({"period": "all", "cost": cost, "id": ids[k], "date": dt, "krw": round(START_KRW * v)})
            for m, krw in monthly_profit(d["curve_oos_dates"], d[f"curve_oos_{ck}"]):
                monthly.append({"cost": cost, "id": ids[k], "month": m, "profit_krw": round(krw)})

    # 비교용: 그냥 들고 있기 (비용과 무관)
    all_dates = detail[cands[0]]["curve_dates"]
    for cost in COST_KEY:
        for period, p in (("recent", "oos"), ("all", "all")):
            ret = bh[p]["return"]
            board.append({
                "rk": f"hold|{period}|{cost}", "id": "hold", "kind": "hold",
                "name": "그냥 들고 있기 (비교용)", "desc": "처음에 4코인을 7만 5천원씩 사서 아무것도 하지 않은 경우.",
                "period": period, "cost": cost, "trades": None, "win_rate": None, "avg_win": None, "avg_loss": None,
                "hold_h": None, "ret": ret, "final_krw": round(START_KRW * (1 + ret)), "profit_krw": round(START_KRW * ret),
                "low_krw": round(START_KRW * bh[p]["min"]), "verdict": "-", "fail": "",
            })
        for dt, v in zip(bh["curve_oos_dates"], bh["curve_oos"]):
            curve.append({"period": "recent", "cost": cost, "id": "hold", "date": dt, "krw": round(START_KRW * v)})
        for dt, v in weekly(all_dates, bh["curve"]):
            curve.append({"period": "all", "cost": cost, "id": "hold", "date": dt, "krw": round(START_KRW * v)})
        for m, krw in monthly_profit(bh["curve_oos_dates"], bh["curve_oos"]):
            monthly.append({"cost": cost, "id": "hold", "month": m, "profit_krw": round(krw)})

    best = max((b for b in board if b["kind"] == "rule" and b["period"] == "recent" and b["cost"] == "upbit"),
               key=lambda b: b["ret"])
    hold_recent = next(b for b in board if b["rk"] == "hold|recent|upbit")
    summary = [{
        "start_krw": START_KRW,
        "recent_start": res["periods"]["oos"][0], "all_start": res["periods"]["is"][0], "data_end": res["data_end"][:10],
        "n_rules_tested": res["n_configs"], "n_trades": res["n_trades_simulated"], "n_candidates": len(cands),
        "n_pass_upbit": sum(1 for b in board if b["kind"] == "rule" and b["cost"] == "upbit"
                            and b["period"] == "recent" and b["verdict"] == "통과"),
        "best_id": best["id"], "best_name": best["name"], "best_final_krw": best["final_krw"], "best_ret": best["ret"],
        "hold_final_krw": hold_recent["final_krw"], "hold_ret": hold_recent["ret"],
        "fee": res["costs"]["upbit"]["fee"], "slip": res["costs"]["upbit"]["slip"],
    }]

    files = {"summary": summary, "scoreboard": board, "curve": curve, "monthly": monthly}
    for old in OUT.glob("*.json"):
        if old.stem not in files:
            old.unlink()
    for name, data in files.items():
        (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        print(f"{name}.json: {len(data)}행, {(OUT / f'{name}.json').stat().st_size / 1024:.0f}KB")


if __name__ == "__main__":
    main()
