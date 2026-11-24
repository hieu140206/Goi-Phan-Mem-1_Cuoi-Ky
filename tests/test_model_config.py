"""config.toml là nơi duy nhất chứa hằng số của phần phân tích: đọc đúng, báo lỗi rõ, và mã dùng đúng các giá trị đó."""
import inspect

import pytest

from analytics import baseline, lrs
from finance import absorption, liquidity
from model_config import load_config, section


def test_every_section_the_code_needs_exists():
    for name in ("scoring", "market", "baseline", "lrs", "absorption", "gate", "screener"):
        assert isinstance(section(name), dict) and section(name)


def test_weights_are_proper_fractions():
    for sec in ("scoring", "lrs"):
        w = section(sec)["weights"]
        assert set(w) == {"spread", "depth", "imbalance"}
        assert sum(w.values()) == pytest.approx(1.0)


def test_missing_file_and_missing_section_fail_loudly(tmp_path):
    with pytest.raises(FileNotFoundError, match="config.toml"):
        load_config(str(tmp_path / "khong_co.toml"))
    with pytest.raises(KeyError, match="nope"):
        section("nope")


def _default(fn, name):
    return inspect.signature(fn).parameters[name].default


def test_function_defaults_come_from_config():
    b = section("baseline")
    assert _default(baseline.detect_anomalies_tod, "min_sessions") == b["min_baseline_sessions"]
    assert _default(baseline.detect_anomalies_tod, "max_sessions") == b["max_sessions"]
    assert _default(baseline.detect_anomalies_tod, "persist") == b["persist"]
    assert _default(baseline.detect_anomalies_tod, "threshold") == b["z_threshold"]
    assert lrs.MIN_OBS_PAST == section("lrs")["min_obs_past"]
    assert _default(lrs.lrs_thresholds_past, "q_watch") == section("lrs")["q_watch"]
    assert liquidity.DEFAULT_WEIGHTS == section("scoring")["weights"]
    assert _default(absorption.add_absorption, "min_sessions") == b["min_baseline_sessions"]
