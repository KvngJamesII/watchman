# WatchMan

Agents start a command and walk off. The job is still running, or it already died. Nobody looked.

WatchMan is the skill that keeps them on it. Pid, exit code, new log lines. Until the work finishes, fails, or goes quiet.

## Install

The folder name has to be `watchman`. Clone it straight into the skills directory.

```bash
git clone https://github.com/KvngJamesII/watchman.git ~/.claude/skills/watchman
```

Cursor: `~/.cursor/skills/watchman`
Codex: `~/.codex/skills/watchman`
One project only: `.agents/skills/watchman`

Open a new session after install. The skill only loads once the agent indexes `SKILL.md`.

## What it makes the agent do

Launch is not done. Done is an exit code, an error in the log, or a timeout with the tail attached.

| You see | It means |
|---|---|
| `running`, log still growing | leave it, check again |
| exit 0 | read the tail, report it |
| non-zero, traceback, `failed` | read the tail. do not relaunch blind |
| alive, same last line, cpu idle, two polls | stalled. inspect, then kill or name the blocker |
| a server printed `ready` and will never exit | that is ready, not a hang |

Silence is not success. Stretching the timeout is not a fix.

## Helper

`scripts/watch.py` starts the command and returns. Polling is a separate call, so the agent cannot hide inside a blocking wait.

```bash
python3 scripts/watch.py run --id build --timeout 600 -- npm test
python3 scripts/watch.py status --id build
python3 scripts/watch.py tail --id build
python3 scripts/watch.py stop --id build
```

`status` prints one JSON object. `state` is `running`, `done`, `failed`, or `missing`.

Logs sit in `.watchman/<id>/` in the working directory. That path is gitignored.

```bash
python3 scripts/watch.py run --id demo --timeout 10 -- python3 -c "import time; print('start'); time.sleep(1); print('done')"
python3 scripts/watch.py status --id demo
```

Python 3.9+. No network.

## License

MIT.
