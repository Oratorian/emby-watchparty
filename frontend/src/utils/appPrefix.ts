/**
 * APP_PREFIX runtime accessor.
 *
 * The backend injects `<script>window.APP_PREFIX = "...";</script>`
 * into index.html on every SPA serve, so this module is the one place
 * the rest of the frontend reads it from. Empty string means "serve at
 * root" (no reverse-proxy subpath); a non-empty value never carries a
 * trailing slash (Config.from_env rstrip()'s it on the backend before
 * injection). Mirrors how Flask's `APP_PREFIX` worked in 1.x: every URL
 * the browser sees is prefixed, the proxy passes the path through
 * verbatim, no per-route rewriting needed.
 */

declare global {
  interface Window {
    APP_PREFIX?: string
  }
}

/** The configured APP_PREFIX, or '' when serving at root. */
export const APP_PREFIX: string =
  (typeof window !== 'undefined' && typeof window.APP_PREFIX === 'string')
    ? window.APP_PREFIX
    : ''

/**
 * Prepend the prefix to a relative path. Idempotent: a path that
 * already starts with the prefix is returned unchanged. Use this for
 * any URL the browser will hit directly (fetch targets, <img src>,
 * <track src>, socket.io paths) so the same code works whether or not
 * APP_PREFIX is configured.
 */
export function withPrefix(path: string): string {
  if (!APP_PREFIX) return path
  if (path.startsWith(APP_PREFIX + '/') || path === APP_PREFIX) return path
  return APP_PREFIX + path
}
