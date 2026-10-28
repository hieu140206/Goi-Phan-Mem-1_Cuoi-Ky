"""Tạo dữ liệu MÔ PHỎNG vào data_sample/. Chạy: python scripts/generate_sample_data.py"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from data.simulator import simulate  # noqa: E402

out_dir = ROOT / "data_sample"
out_dir.mkdir(exist_ok=True)
quotes, truth = simulate()
quotes.to_csv(out_dir / "sample_quotes.csv", index=False)
truth.to_csv(out_dir / "sample_anomalies.csv", index=False)
print(f"Đã ghi {len(quotes):,} dòng mô phỏng và {len(truth)} sự kiện bất thường cài sẵn vào {out_dir}")
