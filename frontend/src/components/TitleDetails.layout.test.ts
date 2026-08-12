import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import TitleDetails from './TitleDetails.vue'

/**
 * The structural half of the detail-view redesign.
 *
 * Everything here is invisible to the existing tests, which select buttons and
 * popovers globally and so constrain nothing about where they live or what
 * state they advertise. That matters because the redesign was driven by
 * placement problems, not by behaviour: the controls used to sit below the
 * overview, so their position moved with the length of the synopsis and a long
 * one pushed them off the fold entirely.
 */

const MOVIE = {
  Id: 'movie-1',
  Name: 'A Movie',
  Type: 'Movie',
  Overview: 'Some overview',
}

function mountTitle(
  details: Record<string, unknown> = MOVIE,
  item: Record<string, unknown> = MOVIE,
) {
  vi.spyOn(api, 'itemDetails').mockResolvedValue(details as never)
  return mount(TitleDetails, {
    props: { item: item as never, isHost: false },
  })
}

describe('the detail top bar', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: 'auto', label: 'Auto' }], default_id: 'auto',
    } as never)
    vi.spyOn(api, 'itemSection').mockResolvedValue({ section: 'related', items: [] } as never)
  })

  it('keeps Back and the section buttons on one bar', async () => {
    const wrapper = mountTitle()
    await flushPromises()

    // Containment, not mere existence. Moving the toolbar back below the hero
    // leaves every existing assertion passing while restoring the drift the
    // redesign removed.
    const topbar = wrapper.get('.detail-topbar')
    expect(topbar.find('.back-to-library').exists()).toBe(true)
    expect(topbar.find('.detail-toolbar .section-buttons').exists()).toBe(true)
  })

  it('puts the season and episode pickers on that same bar for a series', async () => {
    vi.spyOn(api, 'seriesSeasons').mockResolvedValue({
      items: [{ Id: 'season-1', Name: 'Season 1', Type: 'Season' }],
    } as never)
    vi.spyOn(api, 'seriesEpisodes').mockResolvedValue({
      items: [{ Id: 'ep-1', Name: 'Pilot', Type: 'Episode', IndexNumber: 1 }],
    } as never)
    const series = { Id: 'series-1', Name: 'A Series', Type: 'Series' }
    const wrapper = mountTitle(series, series)
    await flushPromises()

    expect(wrapper.get('.detail-topbar').find('.series-pickers').exists()).toBe(true)
  })
})

describe('the section popover state', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: 'auto', label: 'Auto' }], default_id: 'auto',
    } as never)
  })

  it('marks which section is open, for the eye and for a screen reader', async () => {
    vi.spyOn(api, 'itemSection').mockResolvedValue({ section: 'related', items: [] } as never)
    const wrapper = mountTitle()
    await flushPromises()

    const related = () => wrapper.get('button[data-section="related"]')
    const extras = () => wrapper.get('button[data-section="extras"]')

    expect(related().classes()).not.toContain('active')
    expect(related().attributes('aria-expanded')).toBe('false')

    await related().trigger('click')
    await flushPromises()

    // `.active` is the only visual mark on the pressed button, and
    // aria-expanded is the only thing that tells a screen reader a panel
    // opened at all.
    expect(related().classes()).toContain('active')
    expect(related().attributes('aria-expanded')).toBe('true')
    expect(extras().attributes('aria-expanded')).toBe('false')

    // And the button names the panel it controls.
    const panelId = related().attributes('aria-controls')
    expect(panelId).toBeTruthy()
    expect(wrapper.get('.section-popover').attributes('id')).toBe(panelId)

    await extras().trigger('click')
    await flushPromises()
    expect(related().classes()).not.toContain('active')
    expect(extras().classes()).toContain('active')
  })

  it('reports a failed section rather than calling it empty', async () => {
    vi.spyOn(api, 'itemSection').mockRejectedValue(new Error('Related unavailable.'))
    const wrapper = mountTitle()
    await flushPromises()

    await wrapper.get('button[data-section="related"]').trigger('click')
    await flushPromises()

    // "None available." for a fetch that failed is worse than wrong: it is a
    // definite answer to a question nobody managed to ask.
    expect(wrapper.get('.section-popover [role="alert"]').text()).toContain('Related unavailable.')
    expect(wrapper.text()).not.toContain('None available.')
  })

  it('retries a failed section when it is reopened', async () => {
    const itemSection = vi.spyOn(api, 'itemSection')
      .mockRejectedValueOnce(new Error('Related unavailable.'))
      .mockResolvedValue({
        section: 'related',
        items: [{ Id: 'movie-2', Name: 'Rocky II', Type: 'Movie' }],
      } as never)
    const wrapper = mountTitle()
    await flushPromises()

    await wrapper.get('button[data-section="related"]').trigger('click')
    await flushPromises()
    await wrapper.get('button[data-section="related"]').trigger('click')
    await flushPromises()

    // loadSection early-returns on a populated section. Caching the failure as
    // an empty list would make the failure permanent for the life of the view.
    await wrapper.get('button[data-section="related"]').trigger('click')
    await flushPromises()

    expect(itemSection).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('Rocky II')
    expect(wrapper.find('.section-popover [role="alert"]').exists()).toBe(false)
  })
})

describe('the hero backdrop', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: 'auto', label: 'Auto' }], default_id: 'auto',
    } as never)
    vi.spyOn(api, 'itemSection').mockResolvedValue({ section: 'related', items: [] } as never)
  })

  it('marks a title that has artwork so the readability scrim applies', async () => {
    const wrapper = mountTitle({ ...MOVIE, BackdropImageTags: ['bd-1'] })
    await flushPromises()

    // `has-backdrop` gates the whole ::before gradient and the text-shadow
    // rules. Without it the hero renders light text straight onto whatever
    // the artwork happens to be, which is the readability complaint the scrim
    // was added for -- and it fails on exactly the titles that have artwork.
    const hero = wrapper.get('.detail-hero')
    expect(hero.classes()).toContain('has-backdrop')
    expect(hero.attributes('style')).toContain('background-image')
  })

  it('does not claim a backdrop a title does not have', async () => {
    const wrapper = mountTitle()
    await flushPromises()

    const hero = wrapper.get('.detail-hero')
    expect(hero.classes()).not.toContain('has-backdrop')
    expect(hero.attributes('style') ?? '').not.toContain('background-image')
  })
})
