#!/usr/bin/env python3
"""Start a command and leave a pollable status trail.

  python3 watch.py run --id JOB --timeout SEC -- cmd args...
  python3 watch.py status --id JOB
  python3 watch.py tail --id JOB --lines 40
  python3 watch.py stop --id JOB

`run` returns immediately. `status` is the poll.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(".watchman")


def job_dir(job_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in job_id).strip("-")
    if not safe:
        raise SystemExit("job id is empty")
    return ROOT / safe


def write_meta(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n")


def read_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def cmd_run(args: argparse.Namespace) -> int:
    directory = job_dir(args.id)
    directory.mkdir(parents=True, exist_ok=True)
    meta_path = directory / "meta.json"
    log_path = directory / "output.log"
    exit_path = directory / "exit_code"
    existing = read_meta(meta_path)
    if existing.get("state") == "running" and alive(int(existing.get("pid") or 0)):
        print(json.dumps({"state": "already-running", "id": args.id, "pid": existing["pid"]}))
        return 2

    if exit_path.exists():
        exit_path.unlink()
    log_path.write_text("")

    quoted = " ".join(shlex.quote(part) for part in args.cmd)
    # Line-buffer when possible so a live job does not look stalled.
    if os.path.exists("/usr/bin/stdbuf"):
        quoted = "stdbuf -oL -eL " + quoted
    # Supervisor shell records the exit code, then exits. Timeout kills the group.
    script = "\n".join(
        [
            "set +e",
            f"cd {shlex.quote(str(Path.cwd()))}",
            f"{quoted} > {shlex.quote(str(log_path))} 2>&1",
            "code=$?",
            f"echo $code > {shlex.quote(str(exit_path))}",
            "exit $code",
        ]
    )
    proc = subprocess.Popen(
        ["bash", "-lc", script],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    meta = {
        "id": args.id,
        "pid": proc.pid,
        "cmd": args.cmd,
        "started": time.time(),
        "timeout": args.timeout,
        "state": "running",
        "exit_code": None,
        "log": str(log_path),
    }
    write_meta(meta_path, meta)
    print(json.dumps({"state": "running", "id": args.id, "pid": proc.pid, "log": str(log_path), "timeout": args.timeout}))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    directory = job_dir(args.id)
    meta_path = directory / "meta.json"
    if not meta_path.exists():
        print(json.dumps({"state": "missing", "id": args.id}))
        return 1
    meta = read_meta(meta_path)
    exit_path = directory / "exit_code"
    log_path = directory / "output.log"
    pid = int(meta.get("pid") or 0)
    started = float(meta.get("started") or time.time())
    timeout = float(meta.get("timeout") or 0)

    if exit_path.exists():
        raw = exit_path.read_text().strip() or "1"
        code = int(raw)
        meta["state"] = "done" if code == 0 else "failed"
        meta["exit_code"] = code
        meta["ended"] = meta.get("ended") or time.time()
    elif timeout and (time.time() - started) > timeout and alive(pid):
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass
        meta["state"] = "failed"
        meta["exit_code"] = 124
        meta["error"] = "timeout"
        meta["ended"] = time.time()
    elif alive(pid):
        meta["state"] = "running"
    else:
        meta["state"] = "failed"
        meta["exit_code"] = meta.get("exit_code")
        meta["error"] = meta.get("error") or "process exited without a recorded code"

    write_meta(meta_path, meta)
    out = {
        "state": meta.get("state"),
        "id": args.id,
        "pid": pid,
        "exit_code": meta.get("exit_code"),
        "elapsed_sec": round(time.time() - started, 1),
        "log_bytes": log_path.stat().st_size if log_path.exists() else 0,
        "error": meta.get("error"),
    }
    print(json.dumps(out))
    return 0 if meta.get("state") in {"running", "done"} else 1


def cmd_tail(args: argparse.Namespace) -> int:
    log_path = job_dir(args.id) / "output.log"
    if not log_path.exists():
        print(f"no log for {args.id}", file=sys.stderr)
        return 1
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(lines[-args.lines :]))
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    directory = job_dir(args.id)
    meta_path = directory / "meta.json"
    meta = read_meta(meta_path)
    pid = int(meta.get("pid") or 0)
    if alive(pid):
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        time.sleep(0.4)
        if alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
    meta["state"] = "failed"
    meta["exit_code"] = 130
    meta["error"] = "stopped"
    meta["ended"] = time.time()
    write_meta(meta_path, meta)
    print(json.dumps({"state": "failed", "id": args.id, "exit_code": 130, "error": "stopped"}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch a command without blocking the agent")
    sub = parser.add_subparsers(dest="action", required=True)

    run = sub.add_parser("run")
    run.add_argument("--id", required=True)
    run.add_argument("--timeout", type=float, default=600)
    run.add_argument("cmd", nargs=argparse.REMAINDER)
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status")
    status.add_argument("--id", required=True)
    status.set_defaults(func=cmd_status)

    tail = sub.add_parser("tail")
    tail.add_argument("--id", required=True)
    tail.add_argument("--lines", type=int, default=40)
    tail.set_defaults(func=cmd_tail)

    stop = sub.add_parser("stop")
    stop.add_argument("--id", required=True)
    stop.set_defaults(func=cmd_stop)

    args = parser.parse_args()
    if args.action == "run":
        cmd = args.cmd
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]
        if not cmd:
            parser.error("run requires a command after --")
        args.cmd = cmd
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
