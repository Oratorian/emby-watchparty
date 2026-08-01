/**
 * Copy a string to the system clipboard with a non-secure-context fallback.
 *
 * `navigator.clipboard` is only exposed on secure origins (https or
 * localhost). When the app is reached via a plain LAN IP like
 * http://10.0.0.6:5000 the Clipboard API is undefined, which crashes any
 * caller that assumes it exists. This helper tries the modern API first
 * and falls back to a hidden textarea + execCommand('copy') so copy
 * buttons keep working on intranet deployments.
 *
 * Resolves to `true` on success, `false` if both paths fail.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      /* fall through to the legacy path */
    }
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  // Keep the textarea off-screen but selectable. Setting display:none
  // would also block selection in some browsers, so we use opacity 0
  // plus a tiny absolute position.
  textarea.style.position = 'fixed'
  textarea.style.top = '0'
  textarea.style.left = '0'
  textarea.style.width = '1px'
  textarea.style.height = '1px'
  textarea.style.opacity = '0'
  textarea.setAttribute('readonly', '')
  document.body.appendChild(textarea)

  let ok: boolean
  try {
    textarea.select()
    textarea.setSelectionRange(0, text.length)
    ok = document.execCommand('copy')
  } catch {
    ok = false
  } finally {
    document.body.removeChild(textarea)
  }
  return ok
}
