# Architecture Explorer Package

The reusable React component that renders the onboarding agent's architecture graph. Consumed by `example-nextjs/` in this folder.

## Contents

- `src/ArchitectureExplorer.tsx` — main component
- `src/ArchitectureExplorer.module.css` — scoped styles
- `src/types.ts` — graph data types
- `src/graphData.ts` — graph loader
- `src/architectureGraphs.json` — exported graph data (regenerated from `../data/architectureGraphs.source.json`)
- `src/index.ts` — public exports

## Runtime dependencies

The package depends on React and Mermaid:

```bash
npm install mermaid
```

The host app also needs React and a bundler/framework that supports CSS modules. Next.js works as-is.

## Exports

`src/index.ts` exports:

- `ArchitectureExplorer` — the React component
- `architectureGraphData`
- `architectureGraphs`
- graph and type definitions

## Usage

```tsx
"use client";

import {
  ArchitectureExplorer,
  architectureGraphs,
} from "@/components/architecture-explorer";

export default function OnboardingAgentArchitecturePage() {
  return (
    <ArchitectureExplorer
      graphs={architectureGraphs}
      initialKey="overview"
      homeKey="overview"
      heading="Onboarding Agent Architecture Explorer"
    />
  );
}
```

## Updating the graph data

The source of truth lives one level up:

- `../data/architectureGraphs.source.json`

After editing the source, regenerate `src/architectureGraphs.json` with `../scripts/export-architecture-graphs-json.mjs`.
