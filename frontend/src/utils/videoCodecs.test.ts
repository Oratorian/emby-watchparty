import { afterEach, describe, expect, it, vi } from 'vitest'
import { detectVideoCodecs, resetVideoCodecCache } from './videoCodecs'

/**
 * Real capability matrices, measured in real browsers (issue #61).
 *
 * The point of these fixtures is that browser identity predicts nothing.
 * Chrome appears twice with opposite answers, because Chrome has no software
 * HEVC decoder and defers to the platform: a machine without hardware HEVC
 * reports exactly what a browser with no HEVC support at all reports. So no
 * user-agent rule could produce these results, and only a runtime probe can.
 */
const BROWSERS = {
  // Firefox 153.0.3 (64-bit), Windows. No HEVC decoder present; the browser
  // says so plainly ("Keine Decoder fuer angefragte Formate") and its own
  // fallback drops to avc1.
  firefox153: { hevc: false },
  // Chrome on a machine with hardware HEVC decode. Plays hev1.1.6.L120.90 at
  // roughly 15 Mbps.
  chromeWithHevc: { hevc: true },
  // Chrome 150 on a machine WITHOUT hardware HEVC decode. Same browser as
  // above, opposite answer.
  chromeWithoutHevc: { hevc: false },
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
    useBrowser(BROWSERS.chromeWithHevc)
    expect(detectVideoCodecs()).toEqual(['h264', 'hevc'])
  })

  it('does not claim hevc on a Firefox with no HEVC decoder', () => {
    useBrowser(BROWSERS.firefox153)
    // The failure this guards against is not a crash. Claiming hevc here
    // makes the server keep an HEVC source, and this one viewer gets a black
    // video in a party where everyone else is fine.
    expect(detectVideoCodecs()).toEqual(['h264'])
  })

  it('does not claim hevc on a Chrome without hardware HEVC decode', () => {
    // Same browser family as the passing case above. This is why the decision
    // has to be per viewer rather than per browser.
    useBrowser(BROWSERS.chromeWithoutHevc)
    expect(detectVideoCodecs()).toEqual(['h264'])
  })

  it('falls back to the element probe when MediaSource is unavailable', () => {
    // Native HLS (iOS, Safari) never goes through MediaSource.
    useBrowser(BROWSERS.chromeWithHevc, { mediaSource: false })
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
