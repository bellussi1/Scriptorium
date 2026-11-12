"""A resumed translation writes into its existing output; a new run never overwrites one."""
from __future__ import annotations

from src.utils.file_utils import resolve_output_path


def test_a_new_run_gets_a_free_name_when_the_output_exists(tmp_path):
    existing = tmp_path / "Book (pt-BR).epub"
    existing.write_bytes(b"old")

    resolved = resolve_output_path(str(existing), is_resume=False)

    assert resolved == str(tmp_path / "Book (pt-BR) (1).epub")
    assert existing.read_bytes() == b"old"


def test_a_resume_keeps_the_partial_output_it_writes_into(tmp_path):
    partial = tmp_path / "Book (pt-BR).epub"
    partial.write_bytes(b"partial")

    assert resolve_output_path(str(partial), is_resume=True) == str(partial)
    assert not (tmp_path / "Book (pt-BR) (1).epub").exists()


def test_a_resume_with_no_output_uses_the_original_path(tmp_path):
    target = tmp_path / "Book (pt-BR).epub"

    assert resolve_output_path(str(target), is_resume=True) == str(target)


def test_a_new_run_with_no_output_uses_the_original_path(tmp_path):
    target = tmp_path / "Book (pt-BR).epub"

    assert resolve_output_path(str(target), is_resume=False) == str(target)
