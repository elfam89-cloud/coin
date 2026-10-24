# coin — 코인 단타 자동매매봇 프로젝트

업비트 원화마켓에서 **단타 자동매매**를 하는 봇을 만들기 위한 저장소입니다.
**1단계(과거 데이터로 전략 검증)와 추가 검증(처음 보는 2018~2023년, 호가 현실 점검)을 마쳤습니다.**
비트코인·이더리움 기준으로 과거 9년 중 8~9년 플러스였던 후보 2개를, 실제 돈 없이 앞으로의 시세로 확인하는 2단계를 준비 중입니다.

## 먼저 읽을 것
| 파일 | 내용 |
|---|---|
| [`PLAN.md`](PLAN.md) | 기획서: 목표, 결정 사항, 단계별 계획, 안전장치, 비용, 일정 |
| [결과 리포트 (그래프)](https://claude.ai/artifact/HDsZzYEWAgcnhSBUzf9oLc) | 1단계 결과를 그래프로 보는 페이지 |
| [`results/yearly_summary.md`](results/yearly_summary.md) | 2018~2026 연도별 성적 (비트코인·이더리움) |
| [`results/validation_summary.md`](results/validation_summary.md) | 처음 보는 2019~2023년 채점 결과 (사전 등록 기준) |
| [`research/PREREG_2019-2023.md`](research/PREREG_2019-2023.md) | 데이터를 보기 전에 정한 채점 기준 |
| [`results/us_dividend.md`](results/us_dividend.md) | (번외) 미국 배당주 '단타 + 배당락 전날 풀매수' 아이디어 점검 |
| [`results/split_plan.md`](results/split_plan.md) | 봇이 꺼낸 돈을 생활비 · 배당주 · 비트코인으로 나누면 (9년 계산) |
| [`results/compare_pure.md`](results/compare_pure.md) | 나눠서 보관 vs 순수 봇 비교 (같은 생활비 기준) |
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
  validate.py           사전 등록한 규칙을 다른 기간·코인으로 그대로 시험
  prereg_check.py       사전 등록 기준으로 채점 → results/validation_summary.md
  tick_stress.py        실제 호가 단위를 반영한 체결 손해 시험
  yearly_check.py       연도별 성적표 → results/yearly_summary.md
  merge_data.py         여러 기간 데이터를 이어 붙이기
  export_validation.py  추가 검증 결과를 리포트용 데이터로
  fetch_us.py           (번외) 미국 주식 일봉·1시간봉·배당 내려받기 (Yahoo)
  us_dividend_check.py  (번외) 미국 배당주 아이디어 점검 → results/us_dividend.md
  split_check.py        봇이 꺼낸 돈 나누기 (생활비·배당주·비트코인) → results/split_plan.md
  compare_pure.py       나눠서 보관 vs 순수 봇 비교 → results/compare_pure.md
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
