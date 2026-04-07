#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <tfvars-path> [staff-rosters-json-path]"
  exit 1
fi

TFVARS_PATH="$1"
STAFF_ROSTERS_PATH="${2:-config/staff_rosters.json}"

if [[ ! -f "$TFVARS_PATH" ]]; then
  echo "tfvars file not found: $TFVARS_PATH"
  exit 1
fi

if [[ ! -f "$STAFF_ROSTERS_PATH" ]]; then
  echo "staff rosters file not found: $STAFF_ROSTERS_PATH"
  exit 1
fi

ESCAPED_JSON="$(python3 -c 'import json, pathlib, sys; data=json.loads(pathlib.Path(sys.argv[1]).read_text()); print(json.dumps(json.dumps(data)))' "$STAFF_ROSTERS_PATH")"
LINE="staff_roster_locations_json = ${ESCAPED_JSON}"

if grep -q '^staff_roster_locations_json[[:space:]]*=' "$TFVARS_PATH"; then
  python3 - "$TFVARS_PATH" "$LINE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
replacement = sys.argv[2]
lines = path.read_text().splitlines()
updated = []
replaced = False
for line in lines:
    if line.startswith("staff_roster_locations_json") and "=" in line:
        updated.append(replacement)
        replaced = True
    else:
        updated.append(line)
if not replaced:
    updated.append(replacement)
path.write_text("\n".join(updated) + "\n")
PY
else
  printf '\n%s\n' "$LINE" >> "$TFVARS_PATH"
fi

echo "Updated staff_roster_locations_json in $TFVARS_PATH from $STAFF_ROSTERS_PATH"
