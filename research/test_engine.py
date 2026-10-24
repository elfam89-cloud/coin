"""엔진이 손으로 계산한 값과 똑같이 동작하는지 확인하는 테스트.
실행: python research/test_engine.py
"""
import numpy as np
import pandas as pd

from engine import COSTS, END, SIGNAL, SL, TIME, TP, Cost, Exit, equity, max_drawdown, simulate, trade_stats
from indicators import align_htf, rsi


def arr(*v):
    return np.array(v, dtype=float)


def test_tp_hit():
    o = arr(100, 100, 101, 102, 103)
    h = arr(100.5, 101, 102, 104, 104)
    l = arr(99.5, 99.8, 100.5, 101, 102)
    c = arr(100, 101, 102, 103, 103)
    e, x, pe, px, t = simulate(o, h, l, c, [1], Exit(sl=0.02, tp=0.03))
    assert (e[0], x[0], pe[0], px[0], t[0]) == (1, 3, 100, 103, TP)


def test_sl_gap_down_fills_at_open():
    o = arr(100, 100, 97, 97)
    h = arr(100, 100.5, 97.5, 98)
    l = arr(100, 99.5, 96, 96)
    c = arr(100, 100, 97, 97)
    _, x, _, px, t = simulate(o, h, l, c, [1], Exit(sl=0.02, tp=0.05))
    assert (x[0], px[0], t[0]) == (2, 97, SL)   # 손절가 98이 아니라 더 나쁜 97에 체결


def test_same_bar_tie():
    o = arr(100, 100, 100)
    h = arr(100, 100.2, 104)
    l = arr(100, 99.9, 97)
    c = arr(100, 100, 100)
    _, _, _, px, t = simulate(o, h, l, c, [1], Exit(sl=0.02, tp=0.03))
    assert (px[0], t[0]) == (98, SL)            # 보수적: 손절 먼저
    _, _, _, px, t = simulate(o, h, l, c, [1], Exit(sl=0.02, tp=0.03, tie="tp"))
    assert (px[0], t[0]) == (103, TP)


def test_signal_exit_and_ignore_past_signal():
    o = arr(100, 100, 100.5, 101, 101.5, 102)
    h = o + 0.2
    l = o - 0.2
    c = o
    _, x, _, px, t = simulate(o, h, l, c, [1], Exit(sl=0.05), exit_sig=np.array([1, 4]))
    assert (x[0], px[0], t[0]) == (4, 101.5, SIGNAL)  # 진입 봉(1)의 신호는 무시


def test_time_stop_and_no_overlap():
    o = arr(100, 100, 100, 100, 100, 100, 100, 100)
    h, l, c = o + 0.1, o - 0.1, o
    e, x, _, _, t = simulate(o, h, l, c, [1, 2, 5], Exit(sl=0.05, tp=0.05, max_hold=2))
    assert list(e) == [1, 5] and list(x) == [3, 7] and list(t) == [TIME, TIME]


def test_stop_entry_breakout():
    o = arr(100, 101, 101, 103)
    h = arr(100, 101.2, 102, 104)
    l = arr(100, 100.8, 100.0, 102.5)
    c = arr(100, 101, 101.8, 103.5)
    # 101.5 돌파 시 매수 → 진입 봉(2)의 저가 100.0은 손절 판단에서 제외, 다음 봉부터 판단
    e, x, pe, px, t = simulate(o, h, l, c, [2], Exit(sl=0.01, tp=0.02), levels=[101.5])
    assert pe[0] == 101.5 and t[0] == TP and x[0] == 3 and abs(px[0] - 103.53) < 1e-9


def test_end_of_data():
    o = arr(100, 100, 100)
    h, l, c = o + 0.1, o - 0.1, o
    _, x, _, px, t = simulate(o, h, l, c, [1], Exit(sl=0.05, tp=0.05))
    assert (x[0], t[0]) == (2, END)


def test_cost_and_equity():
    cost = Cost(fee=0.0005, slip=0.0005)
    r = cost.net(100, 103)
    assert abs(r - (103 * 0.9995 * 0.9995 / (100 * 1.0005 * 1.0005) - 1)) < 1e-12
    o = arr(100, 100, 101, 102, 103, 103)
    h = arr(100, 101, 102, 104, 104, 103)
    l = arr(100, 99.8, 100.5, 101, 102, 103)
    c = arr(100, 101, 102, 103, 103, 103)
    e, x, pe, px, t = simulate(o, h, l, c, [1], Exit(sl=0.02, tp=0.03))
    eq = equity(c, e, x, pe, px, cost, 0, len(c))
    assert abs(eq[-1] - (1 + r)) < 1e-12 and eq[0] == 1.0
    assert max_drawdown(np.array([1, 1.2, 0.9, 1.3])) == 0.9 / 1.2 - 1


def test_stats():
    s = trade_stats([0.02, -0.01, 0.03, -0.01])
    assert s["n"] == 4 and s["win_rate"] == 0.5 and abs(s["expectancy"] - 0.0075) < 1e-12
    assert abs(s["profit_factor"] - 2.5) < 1e-12


def test_no_lookahead_htf():
    idx1h = pd.date_range("2025-01-01 00:00", periods=3, freq="1h")
    v = pd.Series([10.0, 20.0, 30.0], index=idx1h)
    idx15 = pd.date_range("2025-01-01 00:00", periods=8, freq="15min")
    a = align_htf(v, "1h", idx15, "15min")
    # 00:45 봉은 01:00에 마감 → 그때 막 마감된 00:00 1시간봉 값(10)을 사용 가능
    assert np.isnan(a.iloc[0]) and np.isnan(a.iloc[2]) and a.iloc[3] == 10 and a.iloc[7] == 20


def test_rsi():
    up = pd.Series(np.arange(1, 40, dtype=float))
    assert rsi(up, 14).iloc[-1] == 100
    zig = pd.Series([1.0, 2.0] * 30)
    assert 45 < rsi(zig, 14).iloc[-1] < 55


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f()
        print("통과:", f.__name__)
    print(f"전체 {len(fns)}개 테스트 통과")
