import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { usePartyStore } from '@/stores/party'
import VideoControls from '@/components/VideoControls.vue'
import VideoPlayer from '@/components/VideoPlayer.vue'
import PartyView from './PartyView.vue'

/**
 * The three playback handlers this branch changed, none of which any test
 * reached: `video_ended` appears in no test file at all.
 *
 * They all turn on `myStreamReloading`, the flag raised while a viewer's own
 * transcode is being rebuilt. Swapping quality, version, audio or subtitles
 * tears down the <video> element, and the browser fires a synthetic `ended`
 * and then `play` against the old element before the new manifest attaches.
 * Those are not user actions and must not be broadcast -- but the guards are
 * not symmetric, and getting them wrong fails in opposite directions.
 */

const routerPush = vi.fn()

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: 'B39AZ' }, query: {} }),
  useRouter: () => ({ push: routerPush, replace: vi.fn() }),
  RouterLink: { template: '<a><slot /></a>' },
}))

// One socket for the whole module. The existing PartyView mocks build a fresh
// { emit: vi.fn() } on every useSocketStore() call, so the object the
// component emits through is never the one a test can inspect.
const socket = {
  emit: vi.fn(),
  connect: vi.fn(),
  disconnect: vi.fn(),
  on: vi.fn(),
  off: vi.fn(),
  connected: true,
}
vi.mock('@/stores/socket', () => ({ useSocketStore: () => socket }))

// Owned by the test so the reloading window can be opened and closed on
// demand; driving it for real would need a live HLS teardown.
const reloading = ref(false)
vi.mock('@/composables/usePartyStream', () => ({
  usePartyStream: () => ({
    reloading,
    // Both are `null` when no prompt is open; the template dereferences
    // .item.Name behind a v-if on the state itself.
    versionPickerState: ref(null),
    resumePromptState: ref(null),
    signalReady: vi.fn(),
    changeTextSubtitle: vi.fn(),
    selectVideo: vi.fn(),
    resumeSelection: vi.fn(),
    startSelectionOver: vi.fn(),
    cancelResume: vi.fn(),
    pickVersion: vi.fn(),
    cancelVersionPick: vi.fn(),
  }),
}))

const CLIENT_ID = 'client-abc'

const VIDEO = {
  item_id: 'movie-1',
  title: 'A Movie',
  overview: '',
  stream_url: 'https://emby.test/master.m3u8',
  audio_index: 3,
  subtitle_index: 7,
  media_source_id: 'source-2',
  selected_by: CLIENT_ID,
  quality: '1080p-high',
  item_type: 'Movie',
  run_time_seconds: 600,
}

let pinia: ReturnType<typeof createPinia>

async function joinedParty(video: Record<string, unknown> | null = VIDEO) {
  const party = usePartyStore()
  vi.spyOn(party, 'join').mockResolvedValue(undefined as never)
  const wrapper = mount(PartyView, {
    global: {
      plugins: [pinia],
      stubs: {
        VideoPlayer: {
          template: '<div />',
          setup(_props, ctx) {
            // onVideoPlay bails on a missing or ended element, and again while
            // the player is syncing, so the stub has to look like a live one.
            ctx.expose({ videoEl: { ended: false, paused: false }, isSyncing: false })
          },
        },
        VideoControls: true,
        LibraryBrowser: true,
        EmojiPicker: true,
        JoinVoteModal: true,
        JoinWaitingRoom: true,
        EmbyLoginModal: true,
        RouterLink: true,
        Teleport: true,
      },
    },
  })
  party.users = ['Alice']
  party.partyId = 'B39AZ'
  if (video) party.currentVideo = video as never
  await nextTick()
  await nextTick()
  return { wrapper, party }
}

function emitsOf(event: string) {
  return socket.emit.mock.calls.filter(([name]) => name === event)
}

describe('the end-of-video signal', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.restoreAllMocks()
    socket.emit.mockClear()
    reloading.value = false
    localStorage.setItem('emby-watchparty-username', 'Alice')
    localStorage.setItem('emby-watchparty-client-id', CLIENT_ID)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  })

  it('is sent once by the selector when the video really ends', async () => {
    const { wrapper } = await joinedParty()

    wrapper.findComponent(VideoPlayer).vm.$emit('ended')
    await flushPromises()

    expect(emitsOf('video_ended')).toHaveLength(1)
    wrapper.unmount()
  })

  it('is not sent for the synthetic ended fired while a stream reloads', async () => {
    const { wrapper } = await joinedParty()
    reloading.value = true
    await nextTick()

    wrapper.findComponent(VideoPlayer).vm.$emit('ended')
    await flushPromises()

    // The most destructive of the three guards: from the selector this stops
    // every viewer's transcode and clears the party's video, so one person
    // changing quality would end the film for the room.
    expect(emitsOf('video_ended')).toHaveLength(0)
    wrapper.unmount()
  })

  it('is only ever sent by the selector', async () => {
    const { wrapper } = await joinedParty({ ...VIDEO, selected_by: 'somebody-else' })

    wrapper.findComponent(VideoPlayer).vm.$emit('ended')
    await flushPromises()

    // Otherwise the backend gets one ended per viewer instead of one per
    // playthrough.
    expect(emitsOf('video_ended')).toHaveLength(0)
    wrapper.unmount()
  })
})

describe('pressing play while your own stream is settling', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.restoreAllMocks()
    socket.emit.mockClear()
    reloading.value = false
    localStorage.setItem('emby-watchparty-username', 'Alice')
    localStorage.setItem('emby-watchparty-client-id', CLIENT_ID)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  })

  it('is swallowed when the room is already playing', async () => {
    const { wrapper, party } = await joinedParty()
    party.playbackState = { playing: true, time: 0, last_update: '' }
    reloading.value = true
    await nextTick()

    wrapper.findComponent(VideoPlayer).vm.$emit('play')
    await flushPromises()

    // HLS.js auto-plays the new manifest, which is not a person pressing play.
    expect(emitsOf('play')).toHaveLength(0)
    wrapper.unmount()
  })

  it('is broadcast when the room is paused, because then it is a real press', async () => {
    const { wrapper, party } = await joinedParty()
    party.playbackState = { playing: false, time: 0, last_update: '' }
    reloading.value = true
    await nextTick()

    wrapper.findComponent(VideoPlayer).vm.$emit('play')
    await flushPromises()

    // The guard used to swallow this too. A paused room plus a playing media
    // element is a real local action, and dropping it desynchronised the tab
    // that pressed play with nothing on screen to explain it.
    expect(emitsOf('play')).toHaveLength(1)
    wrapper.unmount()
  })
})

describe('what the control strip is told about the current stream', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.restoreAllMocks()
    socket.emit.mockClear()
    reloading.value = false
    localStorage.setItem('emby-watchparty-username', 'Alice')
    localStorage.setItem('emby-watchparty-client-id', CLIENT_ID)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  })

  it('passes the live track selection down rather than letting it reseed', async () => {
    const { wrapper } = await joinedParty()

    // Without these the strip falls back to reseeding from IsDefault and
    // re-emits a stale index -- the exact regression
    // VideoControls.partySelection.test.ts documents from the other side,
    // where VideoControls is mounted alone and cannot see this binding.
    const controls = wrapper.findComponent(VideoControls)
    expect(controls.props('audioIndex')).toBe(3)
    expect(controls.props('subtitleIndex')).toBe(7)
    expect(controls.props('mediaSourceId')).toBe('source-2')
    wrapper.unmount()
  })

  it('carries the chosen version through to the server', async () => {
    const { wrapper } = await joinedParty()

    wrapper.findComponent(VideoControls).vm.$emit('change-streams', {
      audioIndex: 5,
      subtitleIndex: -1,
      quality: '720p-medium',
      mediaSourceId: 'source-9',
    })
    await flushPromises()

    // Dropped, the backend re-resolves the default source and the switch to
    // another version silently does nothing.
    expect(emitsOf('change_streams')[0]![1]).toMatchObject({
      party_id: 'B39AZ',
      audio_index: 5,
      subtitle_index: -1,
      quality: '720p-medium',
      media_source_id: 'source-9',
    })
    wrapper.unmount()
  })
})

describe('video selection lifecycle', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.restoreAllMocks()
    vi.useRealTimers()
    socket.emit.mockClear()
    reloading.value = false
    localStorage.setItem('emby-watchparty-username', 'Alice')
    localStorage.setItem('emby-watchparty-client-id', CLIENT_ID)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  })

  function pending(selectedBy = CLIENT_ID) {
    return {
      selection_id: 'selection-1', item_id: 'episode-1', title: 'The Test Episode',
      selected_by: selectedBy, selected_by_username: 'Alice', overview: '',
      status: 'preparing', production_year: 2024, run_time_seconds: 2700,
      item_type: 'Episode', series_name: 'Test Series', season_number: 2,
      episode_number: 4, started_at: new Date().toISOString(), error: null,
    }
  }

  it('shows artwork and metadata instead of no-video copy while preparing', async () => {
    const { wrapper, party } = await joinedParty(null)
    party.pendingVideoSelection = pending() as never
    await nextTick()

    expect(wrapper.find('.video-selection-screen').exists()).toBe(true)
    expect(wrapper.text()).toContain('Preparing video…')
    expect(wrapper.text()).toContain('The Test Episode')
    expect(wrapper.text()).toContain('Test Series')
    expect(wrapper.text()).toContain('S2 E4')
    expect(wrapper.text()).toContain('2024')
    expect(wrapper.text()).toContain('45 min')
    expect(wrapper.text()).not.toContain('No video selected')
    wrapper.unmount()
  })

  it('adds the slow warning after ten seconds', async () => {
    vi.useFakeTimers()
    const { wrapper, party } = await joinedParty(null)
    party.pendingVideoSelection = pending() as never
    await nextTick()
    expect(wrapper.text()).not.toContain('Taking longer than expected')

    vi.advanceTimersByTime(10_000)
    await nextTick()
    expect(wrapper.text()).toContain('Taking longer than expected')
    wrapper.unmount()
    vi.useRealTimers()
  })

  it('lets the selector cancel preparation', async () => {
    const { wrapper, party } = await joinedParty(null)
    party.pendingVideoSelection = pending() as never
    await nextTick()
    await wrapper.get('[data-action="cancel-preparing-selection"]').trigger('click')
    expect(emitsOf('cancel_video_selection')[0]![1]).toEqual({
      party_id: 'B39AZ', selection_id: 'selection-1',
    })
    wrapper.unmount()
  })

  it('gives the selector retry and back actions after failure', async () => {
    const { wrapper, party } = await joinedParty(null)
    party.pendingVideoSelection = { ...pending(), status: 'failed', error: 'Could not prepare video.' } as never
    await nextTick()
    await wrapper.get('[data-action="retry-selection"]').trigger('click')
    await wrapper.get('[data-action="cancel-selection"]').trigger('click')
    expect(emitsOf('retry_video_selection')[0]![1]).toMatchObject({ selection_id: 'selection-1' })
    expect(emitsOf('cancel_video_selection')[0]![1]).toMatchObject({ selection_id: 'selection-1' })
    wrapper.unmount()
  })

  it('shows viewers a waiting message without selector actions', async () => {
    const { wrapper, party } = await joinedParty(null)
    party.pendingVideoSelection = { ...pending('another-client'), status: 'failed' } as never
    await nextTick()
    expect(wrapper.text()).toContain('Waiting for Alice')
    expect(wrapper.find('[data-action="retry-selection"]').exists()).toBe(false)
    expect(wrapper.find('[data-action="cancel-selection"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
