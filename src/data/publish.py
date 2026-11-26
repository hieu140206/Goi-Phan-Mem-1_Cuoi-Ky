"""Đẩy RIÊNG thư mục data/web lên GitHub mà không đụng mã nguồn đang có trong thư mục chạy.

Cách làm: dựng một commit ngay trên đỉnh nhánh ở máy chủ bằng một "index" tạm, chỉ thay các tệp trong data/web, rồi đẩy commit đó.
Không pull, không checkout, không rebase: mã trong thư mục ghi giữ nguyên (đóng băng), mã đang sửa dở ở nơi khác không bị đẩy kèm,
và không có lịch sử nào bị viết lại (đẩy thường, không --force).
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

PREFIX = "data/web"
AUTHOR = {"GIT_AUTHOR_NAME": "Bo ghi du lieu", "GIT_AUTHOR_EMAIL": "noreply@example.com",
          "GIT_COMMITTER_NAME": "Bo ghi du lieu", "GIT_COMMITTER_EMAIL": "noreply@example.com"}


class PublishError(RuntimeError):
    pass


def _git(repo: Path, *args: str, env: dict | None = None) -> str:
    p = subprocess.run(["git", *args], cwd=repo, env={**os.environ, **(env or {})}, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if p.returncode != 0:
        raise PublishError(f"git {' '.join(args[:2])} lỗi: {(p.stderr or p.stdout).strip()[-400:]}")
    return p.stdout.strip()


def build_data_commit(repo: Path, message: str, remote: str = "origin", branch: str = "main") -> tuple[str, list[str]] | None:
    """Tạo (chưa đẩy) commit chỉ chứa thay đổi ở data/web trên đỉnh remote/branch. Trả (mã commit, danh sách tệp đổi); None nếu không đổi gì."""
    _git(repo, "fetch", "-q", remote, branch)
    base = _git(repo, "rev-parse", f"{remote}/{branch}")
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index"), **AUTHOR}
        _git(repo, "read-tree", base, env=env)
        # Chỉ thêm và sửa trong data/web, không xóa tệp trên máy chủ; bỏ dấu giải nén của web và tệp tạm khi xuất.
        _git(repo, "add", "--no-all", "--", PREFIX, env=env)     # tệp bị .gitignore bỏ qua trong thư mục này được tự bỏ qua
        _git(repo, "rm", "--cached", "-q", "--ignore-unmatch", "--", f"{PREFIX}/.unpacked.json", f"{PREFIX}/_tmp*", env=env)
        tree = _git(repo, "write-tree", env=env)
        if tree == _git(repo, "rev-parse", f"{base}^{{tree}}"):
            return None
        commit = _git(repo, "commit-tree", tree, "-p", base, "-m", message, env=env)
    files = _git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", base, commit).splitlines()
    outside = [f for f in files if not f.startswith(PREFIX + "/")]
    if outside:
        raise PublishError(f"Commit dữ liệu có tệp ngoài {PREFIX}: {outside[:5]}. Không đẩy.")
    return commit, files


def push_commit(repo: Path, commit: str, remote: str = "origin", branch: str = "main") -> None:
    """Đẩy thường (không --force). Máy chủ đã có commit mới hơn thì lỗi, gọi lại build_data_commit rồi đẩy lần nữa."""
    _git(repo, "push", remote, f"{commit}:refs/heads/{branch}")
