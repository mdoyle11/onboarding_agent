#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$ROOT_DIR/package/src"
DST_DIR="$ROOT_DIR/example-nextjs/components/architecture-explorer"

node "$ROOT_DIR/scripts/export-architecture-graphs-json.mjs"

mkdir -p "$DST_DIR"

cp "$SRC_DIR/ArchitectureExplorer.tsx" "$DST_DIR/ArchitectureExplorer.tsx"
cp "$SRC_DIR/ArchitectureExplorer.module.css" "$DST_DIR/ArchitectureExplorer.module.css"
cp "$SRC_DIR/architectureGraphs.json" "$DST_DIR/architectureGraphs.json"
cp "$SRC_DIR/graphData.ts" "$DST_DIR/graphData.ts"
cp "$SRC_DIR/index.ts" "$DST_DIR/index.ts"
cp "$SRC_DIR/types.ts" "$DST_DIR/types.ts"
rm -f "$DST_DIR/architectureGraphs.generated.ts"

echo "Synced package/src into example-nextjs/components/architecture-explorer"
