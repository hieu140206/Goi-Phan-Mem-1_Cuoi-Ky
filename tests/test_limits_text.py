"""Mục B7: phần "Giới hạn cần nói thật" có đủ các ý bắt buộc và số phiên được đếm động."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "app"))
from limits import limits_markdown  # noqa: E402


def test_mentions_every_required_limit():
    t = limits_markdown(16, 5, 10, 5)
    for must in ("giả định, chưa hiệu chỉnh", "đo chi phí, không đo độ", "SHB", "spread chào", "spread hiệu dụng", "đặt rồi hủy",
                 "áp lực *hiển thị*", "bỏ lỡ mọi biến động nhanh hơn một phút", "Chưa đánh giá", "không dự báo giá"):
        assert must in t, must


def test_session_counts_are_taken_from_the_arguments_not_hard_coded():
    a = limits_markdown(16, 5, 10, 5)
    b = limits_markdown(31, 5, 10, 0)
    assert "16 phiên NEO" in a and "31 phiên NEO" in b
    assert "Hiện có 5 trong 16 phiên ở trạng thái Chưa đủ dữ liệu" in a
    assert "Hiện có" not in b.split("Hạ mức")[0]                    # không có phiên nào thiếu: không nhắc
    assert "ít nhất 5 phiên trước và dùng tối đa 10" in a


def test_thin_evidence_warning_only_for_few_sessions():
    assert "bằng chứng về độ tin cậy của cảnh báo còn mỏng" in limits_markdown(16, 5, 10)
    assert "bằng chứng về độ tin cậy của cảnh báo còn mỏng" not in limits_markdown(40, 5, 10)
