#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <bot-host>"
  echo "Example: $0 onboarding-agent.eastus.azurecontainerapps.io"
  exit 1
fi

BOT_HOST="$1"
PACKAGE_DIR="teamsappPackage"
MANIFEST_TEMPLATE="${PACKAGE_DIR}/manifest.json"
MANIFEST_RENDERED="${PACKAGE_DIR}/.manifest.rendered.json"
ZIP_PATH="${PACKAGE_DIR}/onboarding-agent-teams-app.zip"

if [[ ! -f "$MANIFEST_TEMPLATE" ]]; then
  echo "manifest not found: $MANIFEST_TEMPLATE"
  exit 1
fi

python3 - "$MANIFEST_TEMPLATE" "$MANIFEST_RENDERED" "$BOT_HOST" <<'PY'
import json
from pathlib import Path
import sys

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
bot_host = sys.argv[3]

manifest = json.loads(src.read_text())
manifest["validDomains"] = [bot_host]
dst.write_text(json.dumps(manifest, indent=2) + "\n")
PY

(
  cd "$PACKAGE_DIR"
  rm -f "$(basename "$ZIP_PATH")"
  zip -j "$(basename "$ZIP_PATH")" "$(basename "$MANIFEST_RENDERED")" color.png outline.png >/dev/null
)

python3 - "$ZIP_PATH" <<'PY'
from pathlib import Path
import sys
import zipfile

zip_path = Path(sys.argv[1])
rendered_name = ".manifest.rendered.json"

with zipfile.ZipFile(zip_path, "r") as zf:
    entries = zf.namelist()

with zipfile.ZipFile(zip_path, "a") as zf:
    data = zf.read(rendered_name)
    zf.writestr("manifest.json", data)

tmp = zip_path.with_suffix(".tmp")
with zipfile.ZipFile(zip_path, "r") as src, zipfile.ZipFile(tmp, "w") as dst:
    for item in src.infolist():
        if item.filename == rendered_name:
            continue
        dst.writestr(item, src.read(item.filename))

tmp.replace(zip_path)
PY

rm -f "$MANIFEST_RENDERED"

echo "Wrote Teams app package: $ZIP_PATH"
echo "Bot host in manifest validDomains: $BOT_HOST"
