"""백테스트 엔진 — 일부러 '보수적으로(불리하게)' 계산한다.

가정
1. 신호는 봉이 '마감된 뒤'에만 확인 → 다음 봉 시가에 진입 (미래 정보 사용 금지)
2. 같은 5분봉 안에서 손절가와 익절가가 둘 다 닿으면 → 손절이 먼저 된 것으로 처리
3. 가격이 손절가 아래로 갭(건너뛰기) 하락하면 → 손절가가 아니라 더 나쁜 시가로 체결
4. 모든 체결에 수수료 + 슬리피지(원하는 가격보다 불리하게 체결되는 손해)를 적용
5. 코인마다 한 번에 하나의 포지션만 (물타기/추가매수 없음)
"""
from dataclasses import dataclass

import numpy as np

TP, SL, SIGNAL, TIME, END = 1, 2, 3, 4, 5
EXIT_NAMES = {TP: "익절", SL: "손절", SIGNAL: "신호청산", TIME: "시간청산", END: "데이터끝"}


@dataclass(frozen=True)
class Exit:
    sl: float | None = None        # 0.02 = -2%에서 손절
    tp: float | None = None        # 0.03 = +3%에서 익절
    max_hold: int | None = None    # 최대 보유 (5분봉 개수)
    tie: str = "sl"                # 같은 봉에서 둘 다 닿으면: "sl"(보수적) / "tp"(낙관적)


@dataclass(frozen=True)
class Cost:
    fee: float     # 한쪽(매수 또는 매도) 수수료
    slip: float    # 한쪽 슬리피지

    def net(self, entry_px, exit_px):
        buy = entry_px * (1 + self.slip) * (1 + self.fee)
        sell = exit_px * (1 - self.slip) * (1 - self.fee)
        return sell / buy - 1


COSTS = {
    "upbit": Cost(fee=0.0005, slip=0.0005),     # 업비트 원화마켓 0.05% + 슬리피지 0.05% (한쪽)
    "free_api": Cost(fee=0.0, slip=0.0005),     # API 수수료 무료 거래소 가정 (슬리피지만)
    "zero": Cost(fee=0.0, slip=0.0),            # 비용 0 (참고용, 비현실적)
}


def _first(arr, start, end, thr, below):
    """arr[start:end]에서 처음으로 thr 이하(below) / 이상인 위치. 없으면 -1."""
    step = 4096
    i = start
    while i < end:
        j = min(end, i + step)
        seg = arr[i:j]
        m = (seg <= thr) if below else (seg >= thr)
        if m.any():
            return i + int(m.argmax())
        i = j
    return -1


def simulate(o, h, l, c, entries, ex: Exit, exit_sig=None, levels=None, deadlines=None, overlap=False):
    """
    o, h, l, c : 5분봉 시가/고가/저가/종가 (numpy 배열)
    entries    : 진입할 5분봉 위치 (오름차순)
    exit_sig   : 신호 청산 위치 (그 봉 시가에 매도, 오름차순) 또는 None
    levels     : 돌파 진입가 (봉 중간에 이 가격을 넘으면 매수). None이면 시가 진입
    deadlines  : 진입별 강제 청산 위치 (그 봉 시가에 매도) 또는 None
    overlap    : True면 포지션이 겹쳐도 모든 진입을 각각 계산 (무작위 기준선용)
    반환: (진입위치, 청산위치, 진입가, 청산가, 청산종류) 배열들
    """
    n = len(o)
    out_e, out_x, out_pe, out_px, out_t = [], [], [], [], []
    last_exit = -1
    for k, e in enumerate(entries):
        e = int(e)
        if e >= n or (e <= last_exit and not overlap):
            continue
        if levels is not None:  # 돌파 매수: 진입 봉에서는 손절/익절 판단을 하지 않음
            pe = max(float(levels[k]), o[e])
            start = e + 1
        else:
            pe = o[e]
            start = e
        stop = n
        if ex.max_hold is not None:
            stop = min(stop, e + ex.max_hold)
        if deadlines is not None:
            stop = min(stop, int(deadlines[k]))
        sig_j = n
        if exit_sig is not None and len(exit_sig):
            p = np.searchsorted(exit_sig, e + 1)
            if p < len(exit_sig):
                sig_j = int(exit_sig[p])
        scan_end = min(stop, sig_j)

        sl_px = pe * (1 - ex.sl) if ex.sl is not None else None
        tp_px = pe * (1 + ex.tp) if ex.tp is not None else None
        sl_j = _first(l, start, scan_end, sl_px, True) if sl_px is not None else -1
        tp_j = _first(h, start, scan_end, tp_px, False) if tp_px is not None else -1

        if sl_j >= 0 or tp_j >= 0:
            if sl_j >= 0 and (tp_j < 0 or sl_j < tp_j):
                j, kind = sl_j, SL
            elif tp_j >= 0 and (sl_j < 0 or tp_j < sl_j):
                j, kind = tp_j, TP
            else:  # 같은 봉에서 둘 다 닿음
                j = sl_j
                if j > e and o[j] <= sl_px:      # 시가부터 손절가 아래 → 손절 확정
                    kind = SL
                elif j > e and o[j] >= tp_px:    # 시가부터 익절가 위 → 익절 확정
                    kind = TP
                else:
                    kind = SL if ex.tie == "sl" else TP
            if kind == SL:
                px = min(o[j], sl_px) if j > e else sl_px
            else:
                px = max(o[j], tp_px) if j > e else tp_px
        elif scan_end < n:
            j = scan_end
            px = o[j]
            kind = SIGNAL if (sig_j <= stop) else TIME
        else:
            j, px, kind = n - 1, c[n - 1], END
        out_e.append(e)
        out_x.append(j)
        out_pe.append(pe)
        out_px.append(px)
        out_t.append(kind)
        last_exit = j
    return (np.array(out_e, dtype=np.int64), np.array(out_x, dtype=np.int64),
            np.array(out_pe, dtype=float), np.array(out_px, dtype=float),
            np.array(out_t, dtype=np.int8))


def equity(c, e, x, pe, px, cost: Cost, lo, hi):
    """[lo, hi) 구간의 계좌 가치 곡선 (시작 1.0). 보유 중에는 종가 기준 평가액(시가평가)."""
    eq = np.empty(hi - lo)
    acct = 1.0
    cur = lo
    for ei, xi, a, b in zip(e, x, pe, px):
        if ei < lo or ei >= hi:
            continue
        eq[cur - lo:ei - lo] = acct
        end = min(xi, hi)
        buy = a * (1 + cost.slip) * (1 + cost.fee)
        eq[ei - lo:end - lo] = acct * c[ei:end] * (1 - cost.slip) * (1 - cost.fee) / buy
        acct *= cost.net(a, b) + 1
        cur = end
        if xi >= hi:
            break
    eq[cur - lo:] = acct
    return eq


def max_drawdown(eq):
    peak = np.maximum.accumulate(eq)
    return float((eq / peak - 1).min())


def trade_stats(r, hold_bars=None):
    """거래별 순수익률(r) → 승률, 기대값 등."""
    r = np.asarray(r, dtype=float)
    n = len(r)
    if n == 0:
        return {"n": 0}
    wins, losses = r[r > 0], r[r <= 0]
    gross_win, gross_loss = wins.sum(), -losses.sum()
    se = r.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    out = {
        "n": n,
        "win_rate": float(len(wins) / n),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "expectancy": float(r.mean()),
        "ci_lo": float(r.mean() - 1.96 * se) if n > 1 else np.nan,
        "ci_hi": float(r.mean() + 1.96 * se) if n > 1 else np.nan,
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else np.inf,
        "compound": float(np.prod(1 + r) - 1),
    }
    out["payoff"] = out["avg_win"] / -out["avg_loss"] if out["avg_loss"] < 0 else np.inf
    if hold_bars is not None:
        out["avg_hold_min"] = float(np.mean(hold_bars) * 5)
    return out
