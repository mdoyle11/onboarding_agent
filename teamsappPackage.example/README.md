Commit-safe example Teams sideload package.

This directory is intentionally a template only. The real local package lives in
`teamsappPackage/`, which is ignored because it may contain real app IDs,
domains, and generated zip artifacts.

To create a real package locally:

1. Copy this directory to `teamsappPackage/`
2. Replace the placeholder values in `manifest.json`
3. Add your real `color.png` and `outline.png`
4. Run:
   - `scripts/package_teams_app.sh <container-app-fqdn>`

Notes:

1. `validDomains` should contain only the host, not `https://` and not `/api/messages`.
2. The Azure Bot messaging endpoint must also be updated separately to:
   - `https://<container-app-fqdn>/api/messages`
