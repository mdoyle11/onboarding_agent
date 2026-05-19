# Portable Package

This folder is the copy boundary for the future website repo.

The package consumes a generated artifact from:

- `../data/architectureGraphs.source.json`

## Copy Target

Copy `package/src/` into the destination site, for example:

```text
src/components/architecture-explorer/
  ArchitectureExplorer.tsx
  ArchitectureExplorer.module.css
  architectureGraphs.json
  graphData.ts
  index.ts
  types.ts
```

## Runtime Dependencies

Install these in the destination site:

```bash
npm install mermaid
```

The host app also needs React and a bundler/framework that supports CSS modules.
Next.js works as-is.

## Exports

`src/index.ts` exports:

- `ArchitectureExplorer`
- `architectureGraphData`
- `architectureGraphs`
- graph/type definitions

## Expected Usage

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

## Notes

- The current graph data is maintained in `../data/architectureGraphs.source.json`
  and exported into `architectureGraphs.json`.
- The website-facing boundary is `architectureGraphs.json`.
