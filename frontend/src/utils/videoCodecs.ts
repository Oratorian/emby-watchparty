/**
 * What this browser can actually decode.
 *
 * The server used to force every stream to H.264, because it had no way to
 * know: a lowest-common-denominator choice that re-encoded an HEVC source
 * even for a client that would have played it directly (issue #61). Only the
 * browser knows, so the browser has to say.
 *
 * Support is genuinely uneven and mostly hardware-dependent. Safari decodes
 * HEVC; Chrome and Edge only with hardware decode on a supported OS and GPU;
 * Firefox only recently, and on Windows with hardware decode; most Linux
 * setups not at all. Probing beats sniffing the user agent, because two
 * copies of the same browser version differ by machine.
 *
 * This runs per viewer in a synchronised party, so a wrong answer is worse
 * than a conservative one: claiming HEVC on a client that cannot decode it
 * produces a black video for that one person while everyone else is fine.
 * Every check below is therefore a positive probe, and anything uncertain
 * falls through to H.264, which every target browser decodes.
 */

/** Codec strings the backend allowlists. H.264 is implied and always sent. */
const PROBES: Array<{ codec: string; mime: string[] }> = [
  {
    // hvc1 is the fMP4/HLS flavour Emby serves; hev1 is the same decoder
    // with out-of-band parameter sets. Probe both, since browsers differ
    // on which spelling they admit to supporting.
    codec: 'hevc',
    mime: [
      'video/mp4; codecs="hvc1.1.6.L93.B0"',
      'video/mp4; codecs="hev1.1.6.L93.B0"',
    ],
  },
]

function canDecode(mimes: string[]): boolean {
  // MediaSource governs the hls.js path, which is what most browsers use
  // here, and it is the stricter of the two: Safari will claim canPlayType
  // support for codecs its MSE implementation refuses.
  const mse = typeof MediaSource !== 'undefined' && typeof MediaSource.isTypeSupported === 'function'
    ? mimes.some((mime) => MediaSource.isTypeSupported(mime))
    : false
  if (mse) return true

  // Native HLS (iOS and Safari) never goes through MediaSource, so fall
  // back to the element probe. 'probably' only: 'maybe' means the browser
  // is guessing, and a guess is exactly what this exists to avoid.
  if (typeof document === 'undefined') return false
  const video = document.createElement('video')
  return mimes.some((mime) => video.canPlayType(mime) === 'probably')
}

/**
 * Codecs to advertise to the server, always including h264.
 *
 * Cached: the answer cannot change within a page load, and the probe
 * allocates a media element on the native-HLS path.
 */
let cached: string[] | null = null

export function detectVideoCodecs(): string[] {
  if (cached) return cached
  const supported = ['h264']
  for (const { codec, mime } of PROBES) {
    try {
      if (canDecode(mime)) supported.push(codec)
    } catch {
      // A probe that throws is not a capability. Stay on h264.
    }
  }
  cached = supported
  return cached
}

/** Test seam: forget the cached probe result. */
export function resetVideoCodecCache(): void {
  cached = null
}
