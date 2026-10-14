#!/bin/zsh
set -euo pipefail
TASK_ROOT="${0:A:h:h}"
TASK_HASH="$(print -rn "$TASK_ROOT" | shasum -a 256 | cut -c1-10)"
TASK_LABEL="local.aiteam.v1.$TASK_HASH"
TASK_DOMAIN="gui/$(id -u)"
if launchctl print "$TASK_DOMAIN/$TASK_LABEL" >/dev/null 2>&1; then
  launchctl bootout "$TASK_DOMAIN/$TASK_LABEL"
  print 'AI Team stopped. The SQLite ledger is retained.'
else
  print 'No AI Team service is loaded for this checkout.'
fi
