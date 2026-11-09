"""The container-side translate.py finder used by pause-now."""
from pathlib import Path

from src.literary.kill_translation import find_pids


def _proc(root: Path, pid: int, cmdline: str) -> None:
    directory = root / str(pid)
    directory.mkdir()
    (directory / "cmdline").write_bytes(cmdline.replace(" ", "\0").encode("utf-8") + b"\0")


def test_finds_the_book_translation_by_output_name(tmp_path: Path):
    _proc(tmp_path, 123, "python translate.py -o /app/translated_files/The Mad Ship (pt-BR).epub")
    _proc(tmp_path, 456, "python translate.py -o /app/translated_files/Other Book (pt-BR).epub")
    _proc(tmp_path, 789, "python translation_api.py")

    assert find_pids("The Mad Ship (pt-BR).epub", str(tmp_path)) == [123]


def test_without_a_name_returns_every_translate_process(tmp_path: Path):
    _proc(tmp_path, 123, "python translate.py -o /app/translated_files/A.epub")
    _proc(tmp_path, 456, "python translate.py -o /app/translated_files/B.epub")
    _proc(tmp_path, 789, "python translation_api.py")

    assert sorted(find_pids("", str(tmp_path))) == [123, 456]


def test_ignores_non_pid_entries_and_unreadable_processes(tmp_path: Path):
    (tmp_path / "self").mkdir()
    (tmp_path / "not-a-pid").mkdir()
    _proc(tmp_path, 123, "python translate.py -o /app/translated_files/A.epub")

    assert find_pids("A.epub", str(tmp_path)) == [123]
