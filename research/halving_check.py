"""(참고) 비트코인 반감기 전후 가격 — 규칙 시험이 아니라 역사 정리.

반감기: 채굴 보상이 절반으로 줄어드는 날 (약 4년마다). 2012년은 데이터가 없어 2016 · 2020 · 2024만 본다.
최고점은 반감기 뒤 2년 안에서, 최저점은 그 최고점 뒤부터 다음 반감기(또는 지금)까지에서 찾는다.
데이터: Yahoo Finance BTC-USD 일봉 (data/ext/BTC-USD_1d.json, 없으면 내려받음)
실행: python -I research/halving_check.py
"""
import json
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "ext" / "BTC-USD_1d.json"
OUT = ROOT / "results" / "halving_cycles.md"
HALVINGS = [pd.Timestamp("2016-07-09"), pd.Timestamp("2020-05-11"), pd.Timestamp("2024-04-20")]


def load():
    if not RAW.exists():
        RAW.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD", headers={"User-Agent": "Mozilla/5.0"},
                         params={"period1": 1410000000, "period2": int(time.time()), "interval": "1d"}, timeout=30)
        r.raise_for_status()
        RAW.write_bytes(r.content)
    j = json.loads(RAW.read_text())["chart"]["result"][0]
    idx = pd.to_datetime(j["timestamp"], unit="s", utc=True).tz_localize(None).normalize()
    px = pd.Series(j["indicators"]["quote"][0]["close"], index=idx, dtype=float).dropna()
    return px[~px.index.duplicated(keep="last")]


def main():
    px = load()
    rows = []
    for k, h in enumerate(HALVINGS):
        p0 = float(px.asof(h))
        win = px[(px.index >= h) & (px.index < h + pd.DateOffset(months=24))]
        peak_d, peak = win.idxmax(), float(win.max())
        nxt = HALVINGS[k + 1] if k + 1 < len(HALVINGS) else px.index[-1] + pd.Timedelta("1D")
        after = px[(px.index >= peak_d) & (px.index < nxt)]
        low_d, low = after.idxmin(), float(after.min())
        months = lambda d: round((d - h).days / 30.44)  # noqa: E731
        rows.append(f"| {h:%Y.%m} | ${p0:,.0f} | {peak_d:%Y.%m} ({months(peak_d)}개월 뒤) | ${peak:,.0f} | **{peak / p0:.1f}배** | "
                    f"{low_d:%Y.%m} ({months(low_d)}개월 뒤) | **{low / peak - 1:+.0%}** |")
    L = ["# (참고) 비트코인 반감기 전후 가격", "",
         f"데이터: Yahoo Finance BTC-USD 일봉 {px.index[0]:%Y-%m-%d} ~ {px.index[-1]:%Y-%m-%d}. 2012년 반감기는 데이터가 없어 뺐습니다.",
         "규칙 시험이 아니라 역사 정리입니다. 3번뿐이라 통계로 검증할 수 없고, 미래를 보장하지 않습니다.", "",
         "| 반감기 | 그때 가격 | 최고점 (반감기 뒤) | 최고점 가격 | 반감기 대비 | 그 뒤 최저점 | 최고점 대비 |", "|---|---|---|---|---|---|---|", *rows, "",
         f"지금 (최근 종가): ${px.iloc[-1]:,.0f}"]
    OUT.write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
