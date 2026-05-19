# Example Next.js App

This is a minimal Next.js app that mounts a local copy of the portable
architecture explorer package.

## Run Locally

```bash
cd /home/matthewdoyle/projects/onboarding_agent/docs/explain/react-architecture-explorer/example-nextjs
npm install
npm run dev
```

Open:

```text
http://localhost:3000
```

## Relationship To The Portable Package

The reusable source of truth lives in:

- `../package/src`

This example uses a local copied snapshot under:

- `components/architecture-explorer`

Refresh that snapshot after package changes:

```bash
cd /home/matthewdoyle/projects/onboarding_agent/docs/explain/react-architecture-explorer
./scripts/sync-package-into-example.sh
```
