"""보조지표 계산 (이동평균, 볼린저밴드, RSI)과 데이터 불러오기/봉 변환."""
import os
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(os.environ.get("COIN_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "value": "sum"}
TF_LEN = {"5min": pd.Timedelta("5min"), "15min": pd.Timedelta("15min"),
          "1h": pd.Timedelta("1h"), "1D": pd.Timedelta("1D")}


def load_5m(market: str) -> pd.DataFrame:
    """5분봉을 불러와 빠진 봉(거래가 없던 5분)을 직전 종가로 채운다."""
    df = pd.read_csv(DATA_DIR / f"{market}_5m.csv.gz", parse_dates=["ts"], index_col="ts")
    df = df[~df.index.duplicated()].sort_index()
    full = pd.date_range(df.index[0], df.index[-1], freq="5min")
    df = df.reindex(full)
    close = df["close"].ffill()
    for col in ("open", "high", "low"):
        df[col] = df[col].fillna(close)
    df["close"] = close
    df[["volume", "value"]] = df[["volume", "value"]].fillna(0.0)
    df.index.name = "ts"
    return df


def resample(df5: pd.DataFrame, tf: str) -> pd.DataFrame:
    """5분봉 → 15분/1시간/일봉. 일봉은 업비트와 같이 한국시간 09:00 시작. 마지막(미완성) 봉은 버린다."""
    if tf == "5min":
        return df5
    if tf == "1D":  # '24h'로 써야 offset(09:00 시작)이 적용됨
        out = df5.resample("24h", offset="9h").agg(AGG).dropna()
    else:
        out = df5.resample(tf).agg(AGG).dropna()
    last_end = df5.index[-1] + pd.Timedelta("5min")
    return out[(out.index >= df5.index[0]) & (out.index + TF_LEN[tf] <= last_end)]  # 앞뒤 미완성 봉 제거


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0):
    mid = s.rolling(n).mean()
    sd = s.rolling(n).std(ddof=0)
    return mid - k * sd, mid, mid + k * sd


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    """와일더(Wilder) 방식 RSI."""
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0)


def align_htf(htf_values: pd.Series, htf: str, tf_index: pd.DatetimeIndex, tf: str) -> pd.Series:
    """상위 봉(예: 1시간봉)에서 계산한 값을 하위 봉에 붙인다.
    각 하위 봉이 마감되는 시점에 '이미 마감된' 상위 봉 값만 쓰므로 미래 정보가 섞이지 않는다."""
    src = pd.Series(htf_values.values, index=htf_values.index + TF_LEN[htf]).sort_index()
    want = tf_index + TF_LEN[tf]
    pos = src.index.searchsorted(want, side="right") - 1
    vals = np.where(pos >= 0, src.values[np.clip(pos, 0, None)], np.nan)
    return pd.Series(vals, index=tf_index)
