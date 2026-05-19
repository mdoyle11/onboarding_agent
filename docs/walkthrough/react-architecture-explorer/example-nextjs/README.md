# Example Next.js App

Minimal Next.js host for the architecture explorer. Run this to view the interactive graph locally.

## Run locally

```bash
cd docs/walkthrough/react-architecture-explorer/example-nextjs
npm install
npm run dev
```

Open `http://localhost:3000`.

## Where the component comes from

This app mounts a local snapshot of the explorer package, copied from `../package/src/` into `components/architecture-explorer/` so Next can resolve it via the app's tsconfig paths.

Refresh that snapshot after editing the package:

```bash
cd docs/walkthrough/react-architecture-explorer
./scripts/sync-package-into-example.sh
```
