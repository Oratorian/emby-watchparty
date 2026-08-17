import { defineConfig, devices } from '@playwright/test'

const python = process.platform === 'win32' ? '.\\.venv\\Scripts\\python.exe' : 'python'
const externalBaseURL = process.env.E2E_BASE_URL

export default defineConfig({
  testDir: './e2e',
  retries: 0,
  reporter: process.env.CI
    ? [['line'], ['html', { open: 'never' }]]
    : 'list',
  use: {
    baseURL: externalBaseURL || 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      testIgnore: /ios\.spec\.ts/,
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
      // Cross-engine smoke owns lifecycle, reconnect, and accessibility.
      // Chromium owns full fake-Emby/hls.js; macOS WebKit owns native HLS.
      testMatch: /index\.spec\.ts/,
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
      testMatch: /index\.spec\.ts/,
    },
    {
      name: 'ios-webkit',
      use: { ...devices['iPhone 13'] },
      testMatch: /ios\.spec\.ts/,
    },
  ],
  webServer: externalBaseURL ? [] : [
    {
      command: `${python} scripts/run_fake_emby.py`,
      cwd: '..',
      url: 'http://127.0.0.1:5012/emby/System/Info/Public',
      reuseExistingServer: !process.env.CI,
      env: { E2E_FAKE_EMBY_PORT: '5012' },
    },
    {
      command: `${python} scripts/run_e2e_app.py`,
      cwd: '..',
      url: 'http://127.0.0.1:5011/api/health',
      reuseExistingServer: !process.env.CI,
      env: {
        APP_ENV: 'development',
        MEDIA_SERVER_TYPE: 'emby',
        MEDIA_SERVER_URL: 'http://127.0.0.1:5012',
        MEDIA_SERVER_API_KEY: 'e2e-key',
        SESSION_SECRET: 'playwright-session-secret-at-least-32-characters',
        // E2E runs over plain loopback HTTP. Override any operator `.env`
        // value so WebKit does not receive a Secure cookie it cannot send.
        SESSION_COOKIE_SECURE: 'false',
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
