#!/bin/zsh
set -euo pipefail
TASK_ROOT="${0:A:h:h}"
TASK_PORT="${AITEAM_PORT:-8766}"
TASK_PYTHON="${AITEAM_PYTHON:-$TASK_ROOT/v1/.venv/bin/python}"
TASK_HASH="$(print -rn "$TASK_ROOT" | shasum -a 256 | cut -c1-10)"
TASK_LABEL="local.aiteam.v1.$TASK_HASH"
TASK_DOMAIN="gui/$(id -u)"
if [[ ! -x "$TASK_PYTHON" ]]; then TASK_PYTHON="$(command -v python3)"; fi
if ! "$TASK_PYTHON" -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null; then
  print -u2 'Python 3.11+ is required. Run: uv sync --project v1 --python 3.12'
  exit 1
fi
TASK_RUNTIME="$("$TASK_PYTHON" -c 'from pathlib import Path; import sys; print(Path.home()/"Library/Caches/AI-Team"/sys.argv[1])' "$TASK_HASH")"
TASK_PLIST="$TASK_RUNTIME/launch-agent.plist"
if launchctl print "$TASK_DOMAIN/$TASK_LABEL" >/dev/null 2>&1; then
  if curl -fsS "http://127.0.0.1:$TASK_PORT/health" >/dev/null 2>&1; then
    print "AI Team is running: http://127.0.0.1:$TASK_PORT/"
    exit 0
  fi
  launchctl bootout "$TASK_DOMAIN/$TASK_LABEL"
fi
"$TASK_PYTHON" - "$TASK_ROOT" "$TASK_PYTHON" "$TASK_PORT" "$TASK_LABEL" "$TASK_RUNTIME" <<'PY'
import pathlib, plistlib, shutil, sys
root, python, port, label, runtime = sys.argv[1:]
runtime = pathlib.Path(runtime)
runtime.mkdir(parents=True, exist_ok=True)
runtime.chmod(0o700)
source = pathlib.Path(root)/'v1/agent_team_v1'
shutil.copytree(source, runtime/'src/agent_team_v1', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
value = {
    'Label': label,
    'ProgramArguments': [str(pathlib.Path(python).resolve()), '-m', 'agent_team_v1', '--db', str(runtime/'state.sqlite3'), 'serve', '--host', '127.0.0.1', '--port', port],
    'WorkingDirectory': str(runtime),
    'EnvironmentVariables': {'PYTHONPATH': str(runtime/'src')},
    'RunAtLoad': True,
    'StandardOutPath': str(runtime/'server.log'),
    'StandardErrorPath': str(runtime/'server-error.log'),
}
(runtime/'launch-agent.plist').write_bytes(plistlib.dumps(value))
PY
launchctl bootstrap "$TASK_DOMAIN" "$TASK_PLIST"
for TASK_CHECK in {1..50}; do
  if curl -fsS "http://127.0.0.1:$TASK_PORT/health" >/dev/null 2>&1; then
    print "AI Team is running: http://127.0.0.1:$TASK_PORT/"
    print "User runtime: $TASK_RUNTIME"
    exit 0
  fi
  sleep 0.1
done
print -u2 "Service is not healthy. See $TASK_RUNTIME/server-error.log"
exit 1
