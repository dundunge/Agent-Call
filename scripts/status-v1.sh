#!/bin/zsh
set -euo pipefail
TASK_ROOT="${0:A:h:h}"
TASK_HASH="$(print -rn "$TASK_ROOT" | shasum -a 256 | cut -c1-10)"
TASK_LABEL="local.aiteam.v1.$TASK_HASH"
TASK_PORT="${AITEAM_PORT:-8766}"
if launchctl print "gui/$(id -u)/$TASK_LABEL" >/dev/null 2>&1; then
  print "Loaded service: $TASK_LABEL"
  curl -fsS "http://127.0.0.1:$TASK_PORT/health"
  print
else
  print 'AI Team is stopped.'
  exit 1
fi
