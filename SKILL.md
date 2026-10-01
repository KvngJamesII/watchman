---
name: watchman
description: "WatchMan monitors long-running commands, scripts, builds, installs, tests, servers, and background jobs so they cannot stall unnoticed. Use whenever a task may take more than a few seconds, when waiting on a script to finish or fail, when a job was backgrounded, or when an agent might otherwise stop checking output, exit code, or errors."
license: MIT
compatibility: "Any agent with a shell. Optional helper is scripts/watch.py (Python 3.9+). No network required."
metadata:
  author: idl3dev
  version: "1.0.0"
---

# WatchMan — Do not stall on running work

A task is not done when it is launched. It is done when you have read a terminal state: exit code, error text, or an explicit timeout with evidence. Silence is not success. A spinner is not progress.

Use this skill for any command, script, build, install, test, download, deploy, server boot, or background job that might outlive a single wait.

## Hard rules

1. Never end a turn while user-requested work is still running, unless you report the live status and the next check. Prefer to keep polling until a terminal state.
2. Never treat "the tool returned" as "the job finished" if the tool only started a background process.
3. Every wait must name what you are waiting for, how you will detect done vs failed vs stalled, and the deadline.
4. After every poll, read new output. Do not assume the last snapshot is still current.
5. On stall, intervene. Do not wait the full timeout in silence.

## Loop

1. **Classify.** Estimate expected duration. Pick a poll cadence and a hard deadline.

| Expected | First wait | Then poll every | Hard deadline |
|---|---|---|---|
| under 15s | block until done | — | 30s |
| 15s–2min | 10s | 10s | 3min |
| 2–10min | 15s | 20s | 12min |
| unknown / long | 10s | 30s | 15min, then ask or checkpoint |

2. **Launch with a trail.** Prefer `scripts/watch.py` (path is next to this file). If you cannot run it, use the manual pattern below. Always capture stdout and stderr to a log file. Record the pid.

3. **Poll until terminal.** Each poll, in order:
   - Is the process still alive?
   - Did the exit code get written?
   - What new lines appeared since the last poll?
   - Any error signature (non-zero exit, traceback, `error:`, `failed`, `panic`, connection refused)?
   - Has output or CPU been idle longer than two poll intervals?

4. **Act on the state.**

| State | Evidence | Action |
|---|---|---|
| done | exit 0 and expected success marker | Read the tail. Report the result. Stop. |
| failed | non-zero exit or error text | Read the tail. Fix or report the cause. Do not relaunch blindly. |
| progressing | new output or CPU movement | Continue. Mention progress only if the user is waiting. |
| stalled | alive, no new output, no CPU, past two intervals | Inspect (log tail, open ports, locks, prompts). Kill if stuck on a prompt or deadlock. Rerun with more visibility or report the blocker. |
| timed out | past hard deadline | Capture tail, stop the process, report partial output and the exact command. |

5. **Close the loop.** Quote the exit code. Do not say "it should be done" without reading status.

## Helper

From the skill directory:

```bash
python3 scripts/watch.py run --id build --timeout 600 -- npm test
python3 scripts/watch.py status --id build
python3 scripts/watch.py tail --id build --lines 40
python3 scripts/watch.py stop --id build
```

`status` prints one JSON object: `state` is `running`, `done`, `failed`, or `missing`. Poll `status` on the cadence above. Do not parse the log only.

State files live in `.watchman/<id>/` in the working directory (`meta.json`, `output.log`). Add `.watchman/` to gitignore if the repo is yours.

## Manual pattern (no helper)

```bash
mkdir -p .watchman/job
# start detached, log merged, pid saved
nohup bash -lc 'your-command' > .watchman/job/output.log 2>&1 &
echo $! > .watchman/job/pid
```

Poll:

```bash
pid=$(cat .watchman/job/pid)
if kill -0 "$pid" 2>/dev/null; then echo RUNNING; else echo EXITED; fi
tail -n 30 .watchman/job/output.log
ps -o pid,etime,pcpu,command -p "$pid"
```

If the shell tool backgrounds for you, use its status/output API on the same cadence. Still read the log tail and the exit code. A background id without a poll is a stall.

## Stall signatures

Treat these as stalled even if the process is alive:

- Interactive prompt (`Proceed?`, password, `[Y/n]`, pager) with no TTY.
- Waiting on a lock, port, or child that already exited.
- Test runner or dev server that printed "ready" and will never exit. That is a ready-state, not a hang: verify the ready line, then continue or stop it on purpose.
- Same last log line across two polls and `pcpu` near 0.

## Do not

- Do not increase the timeout as the only response to silence.
- Do not start a second copy until you have stopped or confirmed the first exited.
- Do not hide a non-zero exit behind a summary of what the command was supposed to do.
