import { afterEach, describe, expect, it, vi } from 'vitest'
import { detectVideoCodecs, resetVideoCodecCache } from './videoCodecs'

/**
 * Real capability matrices, measured in real browsers (issue #61).
 *
 * The point of these fixtures is that browser identity predicts nothing.
 * Chrome appears twice with opposite answers, and the difference is not the
 * hardware: it is whether hardware acceleration is switched on in the
 * browser's own settings. Chrome ships no software HEVC decoder and defers to
 * the platform, so turning acceleration off removes HEVC entirely.
 *
 * That makes this a *runtime* property, not a static one. The same person on
 * the same machine can flip it between sessions, which rules out user-agent
 * rules, a build-time table, and anything cached beyond the current page load.
 */
const BROWSERS = {
  // Firefox 153.0.3 (64-bit), Windows. No HEVC decoder present; the browser
  // says so plainly ("Keine Decoder fuer angefragte Formate") and its own
  // fallback drops to avc1.
  firefox153: { hevc: false },
  // Chrome with hardware acceleration enabled. Plays hev1.1.6.L120.90 at
  // roughly 15 Mbps.
  chromeAccelerated: { hevc: true },
  // Chrome 150 with hardware acceleration turned OFF. Same browser, and the
  // same answer a machine with no HEVC hardware at all would give. miakkia's
  // report on #61 is the other half of this: Chrome, Firefox and Opera GX all
  // direct-played HEVC, and they noted acceleration was on in each.
  chromeUnaccelerated: { hevc: false },
}

function useBrowser(profile: { hevc: boolean }, options: { mediaSource?: boolean } = {}) {
  const isHevc = (type: string) => /hvc1|hev1/.test(type)
  const answer = (type: string) => (isHevc(type) ? profile.hevc : true)

  if (options.mediaSource === false) {
    vi.stubGlobal('MediaSource', undefined)
  } else {
    vi.stubGlobal('MediaSource', { isTypeSupported: (type: string) => answer(type) })
  }

  // Every measured browser agreed across isTypeSupported, canPlayType and
  // mediaCapabilities, so the element probe mirrors the same answer. It only
  // matters on the native-HLS path, where MediaSource is absent.
  vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
    if (tag !== 'video') return document.createElement(tag)
    return { canPlayType: (type: string) => (answer(type) ? 'probably' : '') } as unknown as HTMLElement
  }) as typeof document.createElement)
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  resetVideoCodecCache()
})

describe('detectVideoCodecs', () => {
  it('claims hevc only where the browser actually decodes it', () => {
    useBrowser(BROWSERS.chromeAccelerated)
    expect(detectVideoCodecs()).toEqual(['h264', 'hevc'])
  })

  it('does not claim hevc on a Firefox with no HEVC decoder', () => {
    useBrowser(BROWSERS.firefox153)
    // The failure this guards against is not a crash. Claiming hevc here
    // makes the server keep an HEVC source, and this one viewer gets a black
    // video in a party where everyone else is fine.
    expect(detectVideoCodecs()).toEqual(['h264'])
  })

  it('does not claim hevc on a Chrome with hardware acceleration off', () => {
    // Same browser as the passing case above, on hardware that can decode
    // HEVC. Only a browser setting differs, which is why the decision has to
    // be made at runtime, per viewer, and re-made on every join.
    useBrowser(BROWSERS.chromeUnaccelerated)
    expect(detectVideoCodecs()).toEqual(['h264'])
  })

  it('falls back to the element probe when MediaSource is unavailable', () => {
    // Native HLS (iOS, Safari) never goes through MediaSource.
    useBrowser(BROWSERS.chromeAccelerated, { mediaSource: false })
    expect(detectVideoCodecs()).toEqual(['h264', 'hevc'])
  })

  it('treats a probe that throws as no capability', () => {
    vi.stubGlobal('MediaSource', {
      isTypeSupported: () => {
        throw new Error('probe exploded')
      },
    })
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      if (tag !== 'video') return document.createElement(tag)
      return { canPlayType: () => { throw new Error('probe exploded') } } as unknown as HTMLElement
    }) as typeof document.createElement)

    expect(detectVideoCodecs()).toEqual(['h264'])
  })

  it('always includes h264, which every target browser decodes', () => {
    for (const profile of Object.values(BROWSERS)) {
      resetVideoCodecCache()
      useBrowser(profile)
      expect(detectVideoCodecs()).toContain('h264')
    }
  })
})
