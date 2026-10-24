# coin — 코인 단타 자동매매봇 프로젝트

업비트 원화마켓에서 **단타 자동매매**를 하는 봇을 만들기 위한 저장소입니다.
**1단계(타당성 조사 = 과거 데이터로 전략 검증)를 마쳤습니다.** 통과한 규칙은 0개라 실전은 보류하고,
유망 후보 2개를 앞으로의 데이터로 지켜보는 2단계를 준비 중입니다.

## 먼저 읽을 것
| 파일 | 내용 |
|---|---|
| [`PLAN.md`](PLAN.md) | 기획서: 목표, 결정 사항, 단계별 계획, 안전장치, 비용, 일정 |
| [결과 리포트 (그래프)](https://claude.ai/artifact/HDsZzYEWAgcnhSBUzf9oLc) | 1단계 결과를 그래프로 보는 페이지 |
| [`results/summary.md`](results/summary.md) | 1단계 실험 결과 요약표 |

## 폴더 구조
```
PLAN.md                 기획서
research/               1단계: 과거 데이터로 전략 검증하는 코드
  fetch_data.py         업비트 과거 차트(5분봉) 내려받기 (API 키 필요 없음)
  indicators.py         이동평균·볼린저밴드·RSI 계산
  engine.py             가상 매매 계산기 (수수료·슬리피지 포함, 보수적 가정)
  strategies.py         후보 전략 5종 + 무작위 기준선
  run_study.py          전체 실험 실행 → results/ 에 저장
  export_report.py      리포트용 데이터 파일 만들기 → results/report/
  test_engine.py        계산기가 맞게 동작하는지 확인하는 테스트
results/                실험 결과 (요약표, 원자료 JSON)
  report/               리포트 페이지(index.html)와 그래프용 데이터
data/                   내려받은 차트 데이터 (용량이 커서 GitHub에는 올리지 않음)
```

## 직접 다시 돌려보려면 (선택)
```bash
pip install pandas numpy requests
python research/fetch_data.py --markets KRW-BTC,KRW-ETH,KRW-XRP,KRW-SOL,KRW-DOGE,KRW-ADA,KRW-LINK,KRW-NEAR --start 2023-09-01
python research/test_engine.py
python research/run_study.py
python research/export_report.py
```

> ⚠️ 이 저장소의 결과는 과거 데이터로 계산한 것이며, 미래 수익을 보장하지 않습니다.
