# Inbox AI Frontend Bundle

This folder contains a minimal build setup that bundles the Material Web components used by the dashboard. The output is written to `../dist/material.js`, which the FastAPI template loads at runtime.

## One-time setup

```powershell
cd src\inbox_ai\web\static\frontend
npm install
```

## Rebuilding the bundle

Whenever you change the dashboard markup or update Material components, rebuild the bundle:

```powershell
npm run build
```

The `npm run build` script uses `esbuild` to bundle only the components the dashboard needs. Commit the updated `../dist/material.js` so the Python app can serve the assets without requiring Node in production.

## Cleaning up

The legacy `src/inbox_ai/web/static/node_modules` directory is no longer required. You can delete it once the bundle has been generated.
