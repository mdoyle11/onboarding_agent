# Teams Sideload Package — Example

Commit-safe template for the Teams sideload package. The real package lives in `teamsappPackage/`, which is gitignored because it embeds real bot IDs, domains, and icon artwork.

## Create the real package locally

1. Copy this directory to `teamsappPackage/`:
   ```bash
   cp -r teamsappPackage.example teamsappPackage
   ```
2. Replace the placeholder values in `teamsappPackage/manifest.json` (the `package_teams_app.sh` script will overwrite `id`, `bots[].botId`, and `validDomains` on each build, so you mainly need to set names, descriptions, and icon assets).
3. Replace the placeholder `color.png` and `outline.png` with real icons.
4. Build the upload zip:
   ```bash
   scripts/package_teams_app.sh <bot-host> <bot-app-id> [teams-app-id]
   ```

See [`teamsappPackage/README.md`](../teamsappPackage/README.md) for upload steps in Teams.

## Notes

- `validDomains` must be a host only — no scheme, no path. Example: `onboarding-agent.eastus.azurecontainerapps.io`.
- The Azure Bot messaging endpoint is set by Terraform when the app layer applies; you do not need to update it in the portal.
- Do not commit `teamsappPackage/` — it is intentionally gitignored.
