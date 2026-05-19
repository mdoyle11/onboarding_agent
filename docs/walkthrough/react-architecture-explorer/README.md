# React / Next.js Architecture Explorer

This folder is organized as a portable website artifact, not as internal app
docs.

## Layout

- `package/`
  Reusable explorer package to copy into a future website repo.

- `example-nextjs/`
  Minimal Next.js app that proves the package shape works in a real frontend.

## What To Pull Into A Future Website Repo

Copy `package/src/` into the website repo, then either:

1. keep the included `architectureGraphs.json`, or
2. replace it with sanitized graph data owned by the website repo.

The example app is only a smoke-test harness. It is not the portable source of
truth.

## Current Package Boundaries

The reusable package contains:

- `package/src/ArchitectureExplorer.tsx`
- `package/src/ArchitectureExplorer.module.css`
- `package/src/types.ts`
- `package/src/architectureGraphs.json`
- `package/src/graphData.ts`
- `package/src/index.ts`

The maintained source data lives in:

- `data/architectureGraphs.source.json`

That package is self-contained except for its host app dependencies on React and
Mermaid.

## Why This Structure Exists

The final website will live in a different repository and likely on a different
machine. This layout keeps the website-facing code in one copyable directory and
keeps the local Next example isolated from it.
