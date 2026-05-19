# React / Next.js Architecture Explorer

Interactive walkthrough of the onboarding agent's module graph. Renders the same architecture information as `docs/walkthrough/ARCHITECTURE.md`, but as a clickable graph that you can drill into.

## Layout

- `package/`
  The reusable React component (`ArchitectureExplorer.tsx`) plus its baked-in graph data and styles. This is the actual explorer.

- `example-nextjs/`
  A minimal Next.js host app that mounts `ArchitectureExplorer` and serves it locally. Use this to view the explorer.

- `data/architectureGraphs.source.json`
  The maintained source of truth for the graph data. `scripts/export-architecture-graphs-json.mjs` regenerates the package's `architectureGraphs.json` from this file.

- `scripts/`
  - `export-architecture-graphs-json.mjs` — rebuild `package/src/architectureGraphs.json` from `data/architectureGraphs.source.json`
  - `sync-package-into-example.sh` — copy `package/src/` into `example-nextjs/components/architecture-explorer/` so the example app picks up local changes

## Run the explorer locally

```bash
cd example-nextjs
npm install
npm run dev
# open http://localhost:3000
```

## Updating the graph

1. Edit `data/architectureGraphs.source.json`.
2. Run `node scripts/export-architecture-graphs-json.mjs` to regenerate the package's JSON.
3. Run `scripts/sync-package-into-example.sh` to push the change into `example-nextjs/`.
4. Refresh the dev server to verify.

## Package contents

Everything the explorer needs is under `package/src/`:

- `ArchitectureExplorer.tsx` — the React component
- `ArchitectureExplorer.module.css` — scoped styles
- `types.ts` — graph data types
- `graphData.ts` — graph loader
- `architectureGraphs.json` — exported graph data (generated)
- `index.ts` — public exports

The package is self-contained except for its peer dependencies on React and Mermaid.
