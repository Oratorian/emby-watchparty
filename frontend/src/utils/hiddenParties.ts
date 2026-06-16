/**
 * `parties_hidden` cookie: party codes the user was denied entry to (a
 * late-joiner vote failed). The index listing filters these out so a
 * rejected user is not repeatedly tempted to re-request a party that
 * already said no. Per-browser, comma-separated, uppercase codes.
 */

const COOKIE_NAME = 'parties_hidden'
const MAX_AGE_SECONDS = 60 * 60 * 24 // 1 day

export function getHiddenParties(): string[] {
  const match = document.cookie.match(/(?:^|;\s*)parties_hidden=([^;]*)/)
  if (!match) return []
  return decodeURIComponent(match[1])
    .split(',')
    .map((c) => c.trim().toUpperCase())
    .filter(Boolean)
}

export function hideParty(code: string | null | undefined): void {
  if (!code) return
  const normalised = code.trim().toUpperCase()
  if (!normalised) return
  const codes = new Set(getHiddenParties())
  codes.add(normalised)
  const value = encodeURIComponent(Array.from(codes).join(','))
  document.cookie = `${COOKIE_NAME}=${value}; path=/; max-age=${MAX_AGE_SECONDS}; SameSite=Lax`
}

export function isPartyHidden(code: string): boolean {
  return getHiddenParties().includes(code.trim().toUpperCase())
}
