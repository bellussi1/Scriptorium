"""Stop a translate.py process inside the app container.

Docker's ``exec`` does not find the shell builtin ``kill`` when it is invoked
directly, and ``docker top`` reports host PIDs while ``docker exec`` needs the
container PID. This script runs *inside* the container, reads /proc, and signals
the matching process by its container PID.

Usage:
    python scripts/kill_translation.py "Book (pt-BR).epub" --signal TERM
"""
from __future__ import annotations

import argparse
import os
import signal
import sys


def find_pids(output_name: str, proc_root: str = "/proc") -> list[int]:
    pids: list[int] = []
    for name in os.listdir(proc_root):
        if not name.isdigit():
            continue
        try:
            raw = open(f"{proc_root}/{name}/cmdline", "rb").read()
        except OSError:
            continue
        command = raw.replace(b"\0", b" ").decode("utf-8", "replace")
        if "translate.py" not in command or "translation_api.py" in command:
            continue
        if output_name and output_name not in command:
            continue
        pids.append(int(name))
    return pids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_name", nargs="?", default="")
    parser.add_argument("--signal", choices=("TERM", "KILL"), default="TERM")
    parser.add_argument("--proc-root", default="/proc", help=argparse.SUPPRESS)
    args = parser.parse_args()

    pids = find_pids(args.output_name, args.proc_root)
    if not pids:
        print("no matching translate.py process")
        return 0
    sig = signal.SIGTERM if args.signal == "TERM" else signal.SIGKILL
    for pid in pids:
        try:
            os.kill(pid, sig)
            print(f"signalled {pid} with SIG{args.signal}")
        except OSError as exc:
            print(f"could not signal {pid}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
