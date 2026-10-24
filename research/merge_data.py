"""여러 기간으로 나눠 받은 5분봉 파일을 하나로 이어 붙인다 (data/merged/).

실행: python research/merge_data.py KRW-BTC KRW-ETH KRW-XRP KRW-ADA
"""
import gzip
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data"
SOURCES = [ROOT / "y2018", ROOT / "old", ROOT]   # 오래된 것부터


def main(markets):
    out_dir = ROOT / "merged"
    out_dir.mkdir(exist_ok=True)
    for mk in markets:
        rows, header = {}, None
        for src in SOURCES:
            f = src / f"{mk}_5m.csv.gz"
            if not f.exists():
                continue
            with gzip.open(f, "rt") as fh:
                header = fh.readline()
                for line in fh:
                    rows[line.split(",", 1)[0]] = line   # 같은 시각은 나중 파일 기준
        keys = sorted(rows)
        with gzip.open(out_dir / f"{mk}_5m.csv.gz", "wt") as fh:
            fh.write(header)
            fh.writelines(rows[k] for k in keys)
        print(f"{mk}: {len(keys):,}개 봉 ({keys[0]} ~ {keys[-1]})")


if __name__ == "__main__":
    main(sys.argv[1:])
