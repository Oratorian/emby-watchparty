# Language-pack creator

Standalone GitHub Pages tool for translating EWP messages and exporting format-1 language ZIPs. It supports partial packs, placeholder checks, ZIP import, local draft recovery and JSON draft backups. Everything runs in the browser; no EWP credentials or server connection are required.

## Build and verify

Use the same Node version as the frontend (22.12 or newer; CI uses 24). Install its locked dependencies, then build from the repository root:

```sh
cd frontend
npm ci
cd ..
python scripts/generate_language_catalog.py
node scripts/build_language_pack_builder.mjs
node scripts/build_language_pack_builder.mjs --check
node --test language-pack-builder/format.test.mjs
```

The format tests use Python 3.12 to verify that exported ZIPs pass the actual backend validator. The build uses the existing frontend toolchain, bundles the message compiler locally, and copies only the creator assets and public English catalog into `docs/`. No application environment or runtime data is loaded. The validation workflow checks the committed Pages files for drift.

For a local preview:

```sh
python -m http.server 4188 --bind 127.0.0.1 --directory docs
```

The Playwright tests in `frontend/e2e/language-pack-builder.spec.ts` exercise ZIP export, draft restore, compressed imports and malformed-file preservation in Chromium and Firefox, under the project site's URL prefix.

## GitHub Pages

The site and source belong to `feat/ui-localization`. In repository **Settings → Pages**, select **Deploy from a branch**, choose `feat/ui-localization` and `/docs`, then save. After merging the feature into `main`, change the publishing branch to `main`.

The public URL is `https://oratorian.github.io/emby-watchparty/`. Assets use relative paths, so the site works under the repository prefix. `docs/.nojekyll` keeps the generated files static. EWP's own documentation lives in `documentations/`; the deployment generator writes there too.

After editing creator source or English messages, regenerate `backend/language-catalog.json` and the Pages files before committing.
