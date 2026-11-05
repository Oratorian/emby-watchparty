# Emby Watch Party frontend

The Vue 3 and TypeScript client for Emby Watch Party. Vite builds the application, Pinia manages client state, Vue Router handles navigation, Socket.IO carries party events, and hls.js handles playback where native HLS is not used.

The frontend runs alongside the Python backend. See the [main README](../README.md) for deployment and media-server configuration, and [CONTRIBUTING.md](../CONTRIBUTING.md) for the complete development setup.

## Requirements

- Node.js 22.12 or newer, plus npm. CI uses Node 24.
- Python 3.12 and the repository-root `.venv` for the backend, generated contracts and browser tests.
- An Emby or Jellyfin server for manual playback testing. The default browser suite uses a fake Emby server.

Run the npm commands below from `frontend/`, unless another working directory is shown.

## Local development

Create and activate the repository-root `.venv` with Python 3.12, then run these commands from the repository root:

```sh
python -m pip install --require-hashes -r requirements-dev.txt
python -m backend.app
```

Configure the backend before starting it. For this development workflow use `APP_ENV=development`, an empty `APP_PREFIX`, and `SESSION_COOKIE_SECURE=false` for local HTTP. Set `MEDIA_SERVER_TYPE`, `MEDIA_SERVER_URL` and `MEDIA_SERVER_API_KEY` for your media server. The generated `.env.example` is a production template, so copying it without adjusting those settings does not create a ready development environment.

In a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open the URL printed by Vite, normally `http://localhost:5173`. The current configuration keeps Vite on the local host; LAN access requires an explicit host override such as `npm run dev -- --host 0.0.0.0`.

### Backend proxy and URL prefix

[`vite.config.ts`](vite.config.ts) proxies `/api`, `/hls`, `/docs`, `/redoc`, `/openapi.json` and `/socket.io` to `http://127.0.0.1:5000`. Socket.IO also enables WebSocket proxying. Keep the backend running while using the dev server.

To target another backend address, set `VITE_BACKEND_TARGET` in the shell that launches Vite:

```sh
VITE_BACKEND_TARGET=http://127.0.0.1:5011 npm run dev
```

PowerShell equivalent:

```powershell
$env:VITE_BACKEND_TARGET = 'http://127.0.0.1:5011'
npm run dev
```

The standard development proxy expects backend routes at the root. To verify an `APP_PREFIX` deployment, build the frontend and serve it through the backend with that prefix configured. The backend injects `window.APP_PREFIX` into the served HTML; the router, API client and Socket.IO client read it through [`src/utils/appPrefix.ts`](src/utils/appPrefix.ts). Vite's development HTML does not receive that injection.

## Production build

```sh
npm run build
```

This runs `vue-tsc` and the Vite production build. Output goes to `../backend/static/`, replacing the previous generated frontend output. The backend serves that directory; no separate Node server is needed in production. Vite uses a relative asset base so the same build can be served under the backend's configured `APP_PREFIX`.

`npm run build-only` skips the type check. `npm run preview` previews the compiled output locally; use the backend-served build to verify runtime prefix injection and deployment behaviour.

## Checks and browser tests

| Command | Purpose |
| --- | --- |
| `npm run lint` | ESLint checks |
| `npm run type-check` | Vue and TypeScript checks with `vue-tsc` |
| `npm run test:unit` | Vitest unit and component tests in jsdom |
| `npm run test:coverage` | The same tests with text and LCOV coverage output |
| `npm run test:e2e` | Playwright suite, excluding tests tagged `@jellyfin-real` |
| `npm run test:playback-gate` | Playwright tests tagged `@playback-gate` |

Install the browser before running its project:

```sh
npx playwright install chromium
npm run test:e2e -- --project=chromium
```

[`playwright.config.ts`](playwright.config.ts) normally starts a fake Emby server on port 5012, the test backend on 5011, and Vite on 4173. Windows uses `.venv\Scripts\python.exe` from the repository root; on other platforms, activate the root virtual environment so `python` resolves to the installed backend dependencies.

The configured projects are `chromium`, `firefox`, `webkit` and `ios-webkit`. Their coverage differs: Chromium owns the full fake-Emby playback journey, Firefox adds host/admin recovery coverage, and desktop WebKit runs the cross-engine smoke suite. CI runs native HLS checks with `ios-webkit` on macOS.

`E2E_BASE_URL` targets an already-running application and disables all three managed servers. Supply the test fixtures separately when using it. Real Jellyfin tests require the setup in [`scripts/run_jellyfin_ci.py`](../scripts/run_jellyfin_ci.py), as used by the [CI workflow](../.github/workflows/ci.yml).

## Generated API and socket contracts

The backend's OpenAPI schemas and [`socket_protocol.py`](../backend/src/socket_protocol.py) are authoritative. Do not hand-edit `src/types/api.generated.ts` or `src/types/socket.generated.ts`.

From the repository root, with the Python environment active:

```sh
python scripts/generate_openapi_types.py
python scripts/generate_socket_types.py
```

The socket generator also updates `backend/socket-events.schema.json`. Use `--check` on either command to detect stale committed output without rewriting it. Commit regenerated contracts alongside their backend changes. The [Socket.IO reference](../docs/SOCKET_API.md) describes event payloads and flows; the running backend exposes Swagger UI at `/docs` and ReDoc at `/redoc`.

## UI translations

The interface includes English and German through vue-i18n. Admins can install community language ZIPs without rebuilding; each viewer can choose a language and save it in their browser. English is the fallback. See [the localization guide](../docs/localization.md) for importing packs, creating translations, placeholders, plurals and backend labels.

## Source layout

| Path | Responsibility |
| --- | --- |
| `src/api/` | REST client and API error handling |
| `src/stores/` | Authentication, party, playback and socket state |
| `src/composables/` | Reusable party and playback behaviour |
| `src/components/`, `src/views/` | UI components and routed screens |
| `src/router/`, `src/utils/` | Navigation and shared helpers, including runtime prefix handling |
| `src/types/` | Generated contracts and typed Socket.IO interfaces |
| `e2e/` | Playwright journeys |

Unit and component tests live beside the source as `*.test.ts` files. Use an editor with Vue and TypeScript support; the project's type-check command uses `vue-tsc` for `.vue` files.
