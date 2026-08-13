import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

const backendTarget = process.env.VITE_BACKEND_TARGET || 'http://127.0.0.1:5000'

export default defineConfig({
  // Relative base so all asset URLs in the built index.html are
  // resolved against the document's URL at runtime. That lets the
  // backend serve the SPA from any APP_PREFIX (e.g. /watchparty)
  // without rebuilding -- the prefix is decided per-deployment, the
  // image stays generic. Pair with the `window.APP_PREFIX` runtime
  // global the backend injects into index.html so Vue Router,
  // api/client, and the socket.io client know the prefix too.
  base: './',
  plugins: [
    vue(),
    vueDevTools(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
    // Split hls.js into its own chunk. It's ~250KB and only needed
    // once a stream actually starts -- isolating it lets the home page
    // and join flow load without paying that cost.
    rollupOptions: {
      output: {
        manualChunks: {
          'hls': ['hls.js'],
        },
      },
    },
    // Bump warning ceiling so we stop seeing the 500KB warning for
    // PartyView, which is unavoidably large even after async-loading
    // (socket.io-client + pinia store + video orchestration).
    chunkSizeWarningLimit: 700,
  },
  server: {
    // Bind on all interfaces (not just loopback) so the dev server is
    // reachable from other machines on the LAN -- e.g. testing the
    // party flow from a phone or a second PC at http://192.168.178.20:5173.
    // Use `true`/0.0.0.0 to listen everywhere; pin to a single IP here
    // if you'd rather not expose it on every interface.
    host: false,
    proxy: {
      '/api': backendTarget,
      '/hls': backendTarget,
      '/docs': backendTarget,
      '/redoc': backendTarget,
      '/openapi.json': backendTarget,
      '/socket.io': {
        target: backendTarget,
        ws: true,
      },
    },
  },
})
