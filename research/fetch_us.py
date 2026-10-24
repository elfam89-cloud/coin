"""미국 주식 일봉(배당 포함)과 1시간봉 받기 — Yahoo Finance 차트 API.

실행: python research/fetch_us.py
저장: data/us/{티커}_1d.json, data/us/{티커}_1h.json  (data/는 git에 올리지 않음)
"""
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

TICKERS = ["O", "MAIN", "STAG", "AGNC", "JEPI", "JEPQ", "QYLD", "SCHD"]
OUT = Path(__file__).resolve().parent.parent / "data" / "us"
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}"


def get(session, ticker, interval, p1, p2, tries=4):
    params = {"period1": p1, "period2": p2, "interval": interval, "events": "div|split"}
    for i in range(tries):
        try:
            r = session.get(URL.format(t=ticker), params=params, timeout=30)
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            if i == tries - 1:
                raise
            time.sleep(2 ** (i + 1))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    now = int(datetime.now(timezone.utc).timestamp())
    p1d = int(datetime(2015, 10, 1, tzinfo=timezone.utc).timestamp())  # 200일 평균 등 준비용으로 1년 앞부터
    p1h = now - 729 * 86400                                            # 1시간봉은 최근 730일까지만 줌
    for t in TICKERS:
        for iv, p1 in (("1d", p1d), ("1h", p1h)):
            raw = get(s, t, iv, p1, now)
            (OUT / f"{t}_{iv}.json").write_bytes(raw)
            print(f"{t} {iv}: {len(raw) / 1024:.0f}KB")
            time.sleep(1)
    raw = get(s, "KRW=X", "1d", p1d, now)  # 원/달러 환율 (배당주를 원화로 계산할 때 사용)
    (OUT / "USDKRW_1d.json").write_bytes(raw)
    print(f"USDKRW 1d: {len(raw) / 1024:.0f}KB")


if __name__ == "__main__":
    main()
