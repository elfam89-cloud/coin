"""사전 등록(PREREG_2019-2023.md)한 통과 기준으로 추가 검증 결과를 채점한다.

실행: python research/prereg_check.py   (validate.py 결과 파일들이 results/에 있어야 함)
결과: results/validation_summary.md, results/report/validation.json (리포트용)
"""
import json
from pathlib import Path

RES = Path(__file__).resolve().parent.parent / "results"
START_KRW = 300_000


def load(name):
    p = RES / f"validation_{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def won(v):
    return f"{v:,.0f}원"


def pct(v, d=1):
    return "-" if v is None else f"{v * 100:+.{d}f}%"


def criteria(old):
    a = old["rules"]["A"]["upbit"]
    years = a["years"]
    hold_y = old["hold"]["years"]
    pos_years = [y for y, v in years.items() if v is not None and v > 0]
    checks = [
        ("4년 8개월 누적: 30만원보다 많아짐", a["final_krw"] > START_KRW, won(a["final_krw"])),
        ("거래당 기대값 > 0, 거래 100회 이상", (a["main"].get("expectancy") or -1) > 0 and a["main"].get("n", 0) >= 100,
         f"{pct(a['main'].get('expectancy'), 3)}, {a['main'].get('n', 0)}회"),
        ("무작위로 산 것보다 나음 (p값 < 0.05)", a.get("p_value") is not None and a["p_value"] < 0.05,
         "-" if a.get("p_value") is None else f"p = {a['p_value']:.3f}"),
        ("연도별 5구간 중 3구간 이상 플러스", len(pos_years) >= 3, f"{len(pos_years)}구간 ({', '.join(pos_years) or '없음'})"),
        ("가장 나쁜 연도 구간의 손실이 -10% 이내 (꾸준함, 수정 1)",
         min(v for v in years.values() if v is not None) >= -0.10,
         f"가장 나쁜 구간 {pct(min(v for v in years.values() if v is not None))}"),
        ("새 코인 4개에서도 거래당 기대값 > 0", (a["extra"].get("expectancy") or -1) > 0,
         f"{pct(a['extra'].get('expectancy'), 3)} ({a['extra'].get('n', 0)}회)"),
    ]
    return checks


def main():
    old, old2, rec, rec2 = load("old"), load("old_slip2"), load("recent5"), load("recent5_slip2")
    checks = criteria(old)
    passed = all(ok for _, ok, _ in checks)
    L = ["# 추가 검증 결과 — 변동성 돌파(5일선 필터, 손절 -3%)", "",
         f"사전 등록: [`research/PREREG_2019-2023.md`](../research/PREREG_2019-2023.md) · 처음 보는 기간: {old['start']} ~ {old['end'][:10]}",
         f"주력: {' · '.join(m.replace('KRW-', '') for m in old['main'])} / 새 코인: {' · '.join(m.replace('KRW-', '') for m in old['extra'])}", "",
         f"## 판정: **{'통과' if passed else '탈락'}** ({sum(ok for _, ok, _ in checks)}/6)", "",
         "| 기준 | 결과 | 값 |", "|---|---|---|"]
    for name, ok, val in checks:
        L.append(f"| {name} | {'✅' if ok else '❌'} | {val} |")
    L += ["", "## 30만원으로 했다면 (업비트 수수료)", "",
          "| 규칙 | 처음 보는 2019~2023 | 승률 | 최근 1년 | 그냥 보유 (2019~2023) |", "|---|---|---|---|---|"]
    for key, nm in (("A", "A 변동성 돌파 k=0.6 · 5일선 · 손절 -3%"), ("B", "B 변동성 돌파 k=0.5 · 5일선 · 손절 없음 (c2)"),
                    ("C", "C 짧은 급락 때 사기 RSI2 (c1)")):
        o, r = old["rules"][key]["upbit"], rec["rules"][key]["upbit"]
        L.append(f"| {nm} | {won(o['final_krw'])} ({pct(o['ret'])}) | {o['main'].get('win_rate', 0) * 100:.1f}% | "
                 f"{won(r['final_krw'])} ({pct(r['ret'])}) | {won(old['hold']['final_krw'])} ({pct(old['hold']['ret'])}) |")
    a = old["rules"]["A"]
    L += ["", "## A의 연도별 수익률 (업비트)", "", "| 구간 | A | 그냥 보유 |", "|---|---|---|"]
    for y, v in a["upbit"]["years"].items():
        L.append(f"| {y} | {pct(v)} | {pct(old['hold']['years'][y])} |")
    grid = [k for k in old["rules"] if k.startswith("grid|")]
    pos = sum(old["rules"][k]["upbit"]["ret"] > 0 for k in grid)
    mo = a["upbit"]["months"]
    y22, h22 = a["upbit"]["years"].get("2022"), old["hold"]["years"].get("2022")
    L += ["", "## 꾸준함 (참고 지표)",
          f"- 이익 본 달: **{mo['up']}/{mo['total']}개월** ({mo['up'] / mo['total'] * 100:.0f}%), 가장 좋았던 달 {pct(mo['best'])}, 가장 나빴던 달 {pct(mo['worst'])}",
          f"- 원래 기준 5 (수정 전, 공개 약속): 2022년 규칙 {pct(y22)} vs 그냥 들고 있기 {pct(h22)} → {'충족' if (y22 is not None and y22 > h22) else '미충족'}"]
    L += ["", "## 참고",
          f"- 주변 설정(k 0.4~0.8 × 손절 5가지, 5일선 필터) 중 2019~2023에 플러스: **{pos}/{len(grid)}**",
          f"- 체결 손해 2배일 때 A: 2019~2023 {won(old2['rules']['A']['upbit']['final_krw'])} ({pct(old2['rules']['A']['upbit']['ret'])}), "
          f"최근 1년 {won(rec2['rules']['A']['upbit']['final_krw'])} ({pct(rec2['rules']['A']['upbit']['ret'])})" if old2 and rec2 else "",
          f"- A 최대 낙폭: 2019~2023 {pct(a['upbit']['mdd'])}, 가장 적을 때 {won(a['upbit']['low_krw'])}",
          f"- 수수료 무료 거래소라면 A: 2019~2023 {won(a['free']['final_krw'])} ({pct(a['free']['ret'])})", ""]
    (RES / "validation_summary.md").write_text("\n".join(x for x in L if x is not None) + "\n")
    print("\n".join(L))

    # 리포트용 데이터
    rows = []
    for period, src in (("old", old), ("recent", rec)):
        for key in ("A", "B", "C"):
            for cost in ("upbit", "free"):
                u = src["rules"][key][cost]
                rows.append({"rk": f"{key}|{period}|{cost}", "rule": key, "period": period, "cost": cost,
                             "trades": u["main"].get("n", 0), "win_rate": u["main"].get("win_rate"),
                             "ret": u["ret"], "final_krw": u["final_krw"], "low_krw": u["low_krw"], "mdd": u["mdd"],
                             "extra_exp": u["extra"].get("expectancy"), "p_value": u.get("p_value")})
        rows.append({"rk": f"hold|{period}|-", "rule": "hold", "period": period, "cost": "-", "trades": None,
                     "win_rate": None, "ret": src["hold"]["ret"], "final_krw": src["hold"]["final_krw"],
                     "low_krw": src["hold"]["low_krw"], "mdd": src["hold"]["mdd"], "extra_exp": None, "p_value": None})
    years = [{"year": y, "a": v, "hold": old["hold"]["years"][y]} for y, v in a["upbit"]["years"].items()]
    for r in rows:
        src = old if r["period"] == "old" else rec
        if r["rule"] in ("A", "B", "C"):
            m = src["rules"][r["rule"]][r["cost"]]["months"]
            r.update({"months_up": m["up"], "months_total": m["total"], "month_worst": m["worst"]})
    checks_rows = [{"i": i + 1, "name": n, "ok": ok, "result": "통과" if ok else "미달", "value": v}
                   for i, (n, ok, v) in enumerate(checks)]
    curve = [{"date": d, "id": "A", "krw": k} for d, k in list(zip(a["upbit"]["curve"]["dates"], a["upbit"]["curve"]["krw"]))[::3]]
    curve += [{"date": d, "id": "hold", "krw": k} for d, k in list(zip(old["hold"]["curve"]["dates"], old["hold"]["curve"]["krw"]))[::3]]
    out = RES / "report"
    out.mkdir(exist_ok=True)
    (out / "validation.json").write_text(json.dumps({"rows": rows}, ensure_ascii=False))
    (out / "validation_years.json").write_text(json.dumps(years, ensure_ascii=False))
    (out / "validation_checks.json").write_text(json.dumps(checks_rows, ensure_ascii=False))
    (out / "validation_curve.json").write_text(json.dumps(curve, ensure_ascii=False))


if __name__ == "__main__":
    main()
