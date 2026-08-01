import { defineConfig, devices } from '@playwright/test'

const python = process.platform === 'win32' ? '.\\.venv\\Scripts\\python.exe' : 'python'

export default defineConfig({
  testDir: './e2e',
  use: {
    baseURL: 'http://127.0.0.1:4173',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      testIgnore: /ios\.spec\.ts/,
    },
    {
      name: 'ios-webkit',
      use: { ...devices['iPhone 13'] },
      testMatch: /ios\.spec\.ts/,
    },
  ],
  webServer: [
    {
      command: `${python} scripts/run_e2e_app.py`,
      cwd: '..',
      url: 'http://127.0.0.1:5011/api/health',
      reuseExistingServer: !process.env.CI,
      env: {
        APP_ENV: 'development',
        EMBY_SERVER_URL: 'http://127.0.0.1:59999',
        EMBY_API_KEY: 'e2e-key',
        SESSION_SECRET: 'playwright-session-secret-at-least-32-characters',
        CORS_ALLOWED_ORIGINS: 'http://127.0.0.1:4173',
        E2E_BACKEND_PORT: '5011',
      },
    },
    {
      command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173',
      url: 'http://127.0.0.1:4173',
      reuseExistingServer: !process.env.CI,
      env: { VITE_BACKEND_TARGET: 'http://127.0.0.1:5011' },
    },
  ],
})
