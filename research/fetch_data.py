"""업비트 과거 캔들(봉) 데이터 다운로드.

사용 예:
    python research/fetch_data.py --markets KRW-BTC,KRW-ETH --unit 5 --start 2023-09-01

- 업비트 공개 시세 API를 사용하므로 가입/API 키가 필요 없습니다.
- 결과는 data/KRW-BTC_5m.csv.gz 형태로 저장됩니다 (data/ 폴더는 git에 올리지 않음).
- 시간(ts)은 한국시간(KST) 기준 봉 시작 시각입니다.
"""
import argparse
import gzip
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API = "https://api.upbit.com/v1/candles/minutes/{unit}"
DATA_DIR = Path(os.environ.get("COIN_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
KST = timezone(timedelta(hours=9))


class RateLimiter:
    """여러 스레드가 함께 쓰는 초당 요청 수 제한 (업비트 시세 API는 IP당 초당 10회)."""

    def __init__(self, per_sec: float):
        self.interval = 1.0 / per_sec
        self.lock = threading.Lock()
        self.next_time = time.monotonic()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            if now < self.next_time:
                time.sleep(self.next_time - now)
            self.next_time = max(now, self.next_time) + self.interval


STATS = {"ok": 0, "429": 0, "418": 0, "other": 0}


def fetch_page(session, limiter, market, unit, to_utc):
    params = {"market": market, "count": 200, "to": to_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}
    for attempt in range(10):
        limiter.wait()
        try:
            r = session.get(API.format(unit=unit), params=params, timeout=20)
        except requests.RequestException:
            STATS["other"] += 1
            time.sleep(min(30, 2 ** attempt))
            continue
        if r.status_code == 200:
            STATS["ok"] += 1
            return r.json()
        if r.status_code == 429:      # 초당 한도 초과 → 다음 초까지 잠깐 대기
            STATS["429"] += 1
            time.sleep(1.0)
            continue
        if r.status_code == 418:      # 429가 쌓여 일시 차단됨 → 충분히 쉬었다가 재시도
            STATS["418"] += 1
            print(f"  [경고] 업비트 일시 차단(418): {r.text[:120]}", flush=True)
            time.sleep(30)
            continue
        STATS["other"] += 1
        time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"{market}: 요청 실패 (to={params['to']})")


def fetch_market(market, unit, start_kst, end_kst, limiter):
    session = requests.Session()
    to_utc = end_kst.astimezone(timezone.utc)
    start_utc = start_kst.astimezone(timezone.utc)
    rows = {}
    pages = 0
    while to_utc > start_utc:
        page = fetch_page(session, limiter, market, unit, to_utc)
        if not page:
            break
        for c in page:
            rows[c["candle_date_time_kst"]] = (
                c["opening_price"], c["high_price"], c["low_price"], c["trade_price"],
                c["candle_acc_trade_volume"], c["candle_acc_trade_price"],
            )
        earliest = min(c["candle_date_time_utc"] for c in page)
        new_to = datetime.fromisoformat(earliest).replace(tzinfo=timezone.utc)
        if new_to >= to_utc:  # 더 이상 과거 데이터가 없음
            break
        to_utc = new_to
        pages += 1
        if pages % 100 == 0:
            print(f"  {market}: {pages}페이지, {to_utc.astimezone(KST):%Y-%m-%d}까지 받음 "
                  f"(누적 응답 {STATS})", flush=True)

    start_key = start_kst.strftime("%Y-%m-%dT%H:%M:%S")
    keys = sorted(k for k in rows if k >= start_key)
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / f"{market}_{unit}m.csv.gz"
    with gzip.open(out, "wt") as f:
        f.write("ts,open,high,low,close,volume,value\n")
        for k in keys:
            o, h, l, c, v, val = rows[k]
            f.write(f"{k},{o},{h},{l},{c},{v},{val}\n")
    print(f"완료 {market}: {len(keys):,}개 봉 ({keys[0]} ~ {keys[-1]}) → {out.name}", flush=True)
    return market, len(keys)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--markets", default="KRW-BTC,KRW-ETH,KRW-XRP,KRW-SOL")
    p.add_argument("--unit", type=int, default=5, help="분봉 단위 (1, 3, 5, 15, 30, 60, 240)")
    p.add_argument("--start", default="2023-09-01", help="시작일 (한국시간)")
    p.add_argument("--end", default=None, help="종료 시각 (한국시간, 기본: 지금)")
    p.add_argument("--rps", type=float, default=7.0, help="초당 요청 수 (10 미만 권장)")
    p.add_argument("--workers", type=int, default=3)
    a = p.parse_args()

    start = datetime.fromisoformat(a.start).replace(tzinfo=KST)
    if a.end:
        end = datetime.fromisoformat(a.end).replace(tzinfo=KST)
    else:  # 아직 진행 중인 봉은 제외
        now = datetime.now(KST)
        end = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % a.unit)
    markets = [m.strip() for m in a.markets.split(",") if m.strip()]
    limiter = RateLimiter(a.rps)
    print(f"다운로드: {markets} / {a.unit}분봉 / {start:%Y-%m-%d} ~ {end:%Y-%m-%d %H:%M} KST", flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(lambda m: fetch_market(m, a.unit, start, end, limiter), markets))


if __name__ == "__main__":
    main()
