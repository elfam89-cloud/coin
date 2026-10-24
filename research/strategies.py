"""후보 전략들. 각 함수는 '언제 사고(진입) / 언제 파는지(신호 청산)'를 5분봉 위치로 돌려준다.

모든 신호는 봉이 마감된 뒤 계산되고, 실제 매수는 그 다음 봉 시가에 한다 (engine.py 참고).
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from indicators import TF_LEN, align_htf, bollinger, load_5m, resample, rsi, sma


class Market:
    """코인 하나의 5분봉 + 여러 봉 단위(15분/1시간/일봉) 캐시."""

    def __init__(self, name: str, df5: pd.DataFrame | None = None):
        self.name = name
        self.df5 = load_5m(name) if df5 is None else df5
        self.ts = self.df5.index
        self.o = self.df5["open"].to_numpy(float)
        self.h = self.df5["high"].to_numpy(float)
        self.l = self.df5["low"].to_numpy(float)
        self.c = self.df5["close"].to_numpy(float)
        self.n = len(self.c)
        self._tf = {}

    def tf(self, tf: str) -> pd.DataFrame:
        if tf not in self._tf:
            self._tf[tf] = resample(self.df5, tf)
        return self._tf[tf]

    def to_base(self, flags: pd.Series, tf: str) -> np.ndarray:
        """봉 단위 신호(True/False) → '그 봉이 마감된 직후' 5분봉 위치."""
        f = flags.fillna(False).astype(bool)
        labels = f.index[f.to_numpy()]
        pos = self.ts.searchsorted(labels + TF_LEN[tf])
        return pos[pos < self.n].astype(np.int64)

    def idx(self, when) -> int:
        return int(self.ts.searchsorted(pd.Timestamp(when)))


@dataclass
class Signals:
    entries: np.ndarray
    exit_sig: np.ndarray | None = None
    levels: np.ndarray | None = None
    deadlines: np.ndarray | None = None
    meta: dict = field(default_factory=dict)


# 1) 이전 세션의 눌림목 체크리스트 (5개 조건 점수제)
def pullback(m: Market, btc: Market, tf: str, min_score: int) -> Signals:
    d, b = m.tf(tf), btc.tf(tf)
    c = d["close"]
    ma20, ma60 = sma(c, 20), sma(c, 60)
    c1 = c > ma60                                                    # 큰 추세 상승
    c2 = (d["low"] <= ma20 * 1.005).astype(float).rolling(3).max() == 1  # 최근 3봉 중 20선 근처까지 눌림
    c3 = (c > d["open"]) & (c > ma20)                                # 양봉 + 20선 위 마감
    c4 = d["volume"] >= 1.5 * d["volume"].rolling(20).mean().shift(1)  # 거래량 1.5배
    bc = b["close"]
    c5 = (bc > sma(bc, 20)).reindex(d.index).fillna(False)           # BTC 하락장 아님
    score = sum(x.fillna(False).astype(int) for x in (c1, c2, c3, c4, c5))
    return Signals(m.to_base(score >= min_score, tf))


# 2) 볼린저밴드 하단 이탈 + RSI 과매도 → 중앙선 복귀 시 매도 (역추세)
def bb_revert(m: Market, tf: str, trend: bool) -> Signals:
    d = m.tf(tf)
    c = d["close"]
    lo, mid, _ = bollinger(c, 20, 2.0)
    entry = (c < lo) & (rsi(c, 14) < 30)
    if trend:  # 1시간봉 200개 이동평균 위(큰 흐름 상승)일 때만
        h1 = m.tf("1h")["close"]
        ok = align_htf(h1 > sma(h1, 200), "1h", d.index, tf)
        entry &= ok.fillna(0).astype(bool)
    return Signals(m.to_base(entry, tf), exit_sig=m.to_base(c >= mid, tf))


# 3) RSI(2) 단기 과매도 (상승 추세 안에서만) → 5봉 평균 위로 회복 시 매도
def rsi2(m: Market, tf: str, thr: float) -> Signals:
    d = m.tf(tf)
    c = d["close"]
    entry = (c > sma(c, 200)) & (rsi(c, 2) < thr)
    return Signals(m.to_base(entry, tf), exit_sig=m.to_base(c > sma(c, 5), tf))


# 4) 변동성 돌파 (래리 윌리엄스): 오늘 시가 + k × 어제 변동폭을 넘으면 매수 → 다음날 09:00 매도
def vol_breakout(m: Market, k: float, ma_filter: bool) -> Signals:
    d = m.tf("1D")
    rng = (d["high"] - d["low"]).shift(1)
    target = (d["open"] + k * rng).to_numpy()
    ok = rng.notna().to_numpy().copy()
    if ma_filter:  # 당일 시가가 어제까지의 5일 평균보다 높을 때만
        ok &= (d["open"] > d["close"].rolling(5).mean().shift(1)).to_numpy()
    starts = m.ts.searchsorted(d.index)
    ends = m.ts.searchsorted(d.index + pd.Timedelta("1D"))
    ent, lev, dl = [], [], []
    for i in np.flatnonzero(ok):
        s, e = starts[i], ends[i]
        if e >= m.n:
            continue
        hit = m.h[s:e] >= target[i]
        if hit.any():
            ent.append(s + int(hit.argmax()))
            lev.append(target[i])
            dl.append(e)
    return Signals(np.array(ent, dtype=np.int64), levels=np.array(lev), deadlines=np.array(dl, dtype=np.int64))


# 5) 단기 고점 돌파 + 거래량 급증 (추세 추종)
def breakout(m: Market, tf: str) -> Signals:
    d = m.tf(tf)
    c, v = d["close"], d["volume"]
    entry = (c > d["high"].rolling(20).max().shift(1)) & (v > 2 * v.rolling(20).mean().shift(1)) & (c > sma(c, 100))
    return Signals(m.to_base(entry, tf))


# 기준선) 무작위 진입 — "아무 때나 샀다면?"
def random_entries(m: Market, tf: str, count: int, lo: int, hi: int, seed: int) -> Signals:
    d = m.tf(tf)
    pos = m.ts.searchsorted(d.index + TF_LEN[tf])
    pos = pos[(pos >= lo) & (pos < hi)]
    rng = np.random.default_rng(seed)
    pick = np.sort(rng.choice(pos, size=min(count, len(pos)), replace=False))
    return Signals(pick.astype(np.int64))
