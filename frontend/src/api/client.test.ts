import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api, apiFetch, type AdminConfig } from './client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiFetch', () => {
  it('loads normalized v2 libraries and projects them for the existing UI', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [{
        id: 'library-1',
        name: 'Movies',
        kind: 'collection_folder',
        collection_kind: 'movies',
        overview: '',
        runtime_seconds: null,
        production_year: null,
        parent_id: null,
        series_id: null,
        series_name: null,
        season_id: null,
        season_name: null,
        index_number: null,
        parent_index_number: null,
        is_folder: true,
        is_playable: false,
        is_browsable: true,
        has_primary_image: true,
        backdrop_count: 0,
        primary_image_aspect_ratio: 1.5,
        user_state: {
          playback_position_seconds: 0,
          played_percentage: null,
          played: false,
          favorite: true,
        },
        media_source_count: 0,
      }],
      total: 1,
      start: 0,
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.libraries()).resolves.toMatchObject({
      Items: [{
        Id: 'library-1',
        Name: 'Movies',
        Type: 'CollectionFolder',
        CollectionType: 'movies',
        IsFolder: true,
        ImageTags: { Primary: 'available' },
        UserData: { IsFavorite: true },
      }],
      TotalRecordCount: 1,
      StartIndex: 0,
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/v2/libraries', expect.any(Object))
  })

  it('uses provider-neutral v2 auth routes', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(
      JSON.stringify({ success: true, message: 'ok', media_server_type: 'jellyfin' }),
      { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await api.login('alice', 'secret')
    await api.authStatus()
    await api.logout()

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v2/auth/login',
      '/api/v2/auth/status',
      '/api/v2/auth/logout',
    ])
  })

  it('loads selected-provider capabilities from v2', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      media_server_type: 'jellyfin',
      display_name: 'Jellyfin',
      capabilities: { filter_controls: false },
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.mediaServerInfo()).resolves.toEqual({
      media_server_type: 'jellyfin',
      display_name: 'Jellyfin',
      capabilities: { filter_controls: false },
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/v2/media-server', expect.any(Object))
  })

  it('passes an AbortSignal through typed search requests', async () => {
    const controller = new AbortController()
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ items: [], total: 0, start: 0 }),
      { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    const result = await api.search('matrix', controller.signal)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v2/items/search?q=matrix',
      expect.objectContaining({ signal: controller.signal }),
    )
    expect(result).toEqual({
      Items: [], TotalRecordCount: 0, StartIndex: 0,
    })
  })

  it('projects normalized v2 item details for existing components', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: 'movie-1', name: 'Arrival', kind: 'movie', collection_kind: null,
      overview: 'First contact', runtime_seconds: 120, production_year: 2016,
      tagline: 'Why are they here?',
      parent_id: null, series_id: null, series_name: null, season_id: null,
      season_name: null, index_number: null, parent_index_number: null,
      is_folder: false, is_playable: true, is_browsable: false,
      has_primary_image: false, backdrop_count: 0, primary_image_aspect_ratio: null,
      user_state: { playback_position_seconds: 4, played_percentage: 5, played: false, favorite: false },
      media_source_count: 1, genres: ['Drama'], tags: ['Aliens'],
      people: [{ id: 'person-1', name: 'Amy Adams', kind: 'actor' }],
      studios: ['Paramount'], official_rating: 'PG-13', community_rating: 8.1,
      critic_rating: 94,
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.itemDetails('movie-1')).resolves.toMatchObject({
      Id: 'movie-1', Type: 'Movie', Genres: ['Drama'],
      Tagline: 'Why are they here?',
      TagItems: [{ Name: 'Aliens' }],
      People: [{ Id: 'person-1', Name: 'Amy Adams', Type: 'actor' }],
      Studios: [{ Name: 'Paramount' }], OfficialRating: 'PG-13',
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/v2/items/movie-1', expect.any(Object))
  })

  it('loads normalized series seasons from v2', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ items: [], total: 0, start: 0 }), { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.seriesSeasons('series-1')).resolves.toEqual({ items: [] })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v2/items/series-1/seasons', expect.any(Object),
    )
  })

  it('loads season-scoped normalized episodes from v2', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ items: [], total: 0, start: 0 }), { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.seriesEpisodes('series-1', 'season-2')).resolves.toEqual({ items: [] })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v2/items/series-1/episodes?season_id=season-2', expect.any(Object),
    )
  })

  it('updates favorite state through v2', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ success: true, favorite: true }), { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await api.setFavorite('movie-1', true)
    expect(fetchMock).toHaveBeenCalledWith('/api/v2/items/movie-1/favorite', expect.objectContaining({
      method: 'PUT', body: JSON.stringify({ favorite: true }),
    }))
  })

  it('updates played state through v2', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ success: true, played: true }), { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await api.setPlayed('movie-1', true)
    expect(fetchMock).toHaveBeenCalledWith('/api/v2/items/movie-1/played', expect.objectContaining({
      method: 'PUT', body: JSON.stringify({ played: true }),
    }))
  })

  it('loads normalized playlists from v2', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ items: [], total: 0, start: 0 }), { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.playlists()).resolves.toEqual({ items: [] })
    expect(fetchMock).toHaveBeenCalledWith('/api/v2/playlists', expect.any(Object))
  })

  it('creates playlists through v2', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ id: 'playlist-1', name: 'Friday' }), { status: 201 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await api.createPlaylist('Friday')
    expect(fetchMock).toHaveBeenCalledWith('/api/v2/playlists', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ name: 'Friday' }),
    }))
  })

  it('adds playlist items through v2', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ success: true }), { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await api.addPlaylistItem('playlist-1', 'movie-1')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v2/playlists/playlist-1/items',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ item_id: 'movie-1' }) }),
    )
  })

  it('loads normalized stream metadata from v2', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      audio: [{ index: 1, language: 'eng', display_language: 'English', codec: 'aac', channels: 2,
        is_default: true, title: 'Stereo' }],
      subtitles: [{ index: 2, language: 'spa', display_language: 'Spanish', codec: 'srt',
        is_default: false, is_forced: false, is_external: true, is_text: true,
        is_image: false, title: 'Spanish' }],
      media_source_id: 'source-1',
      versions: [{ id: 'source-1', name: 'Main', container: 'mkv', runtime_seconds: 90 }],
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.itemStreams('movie-1', 'source-1')).resolves.toMatchObject({
      audio: [{ displayLanguage: 'English', isDefault: true }],
      subtitles: [{ isExternal: true, isTextSubtitleStream: true, isPGS: false }],
      versions: [{ id: 'source-1', run_time_ticks: 900_000_000 }],
    })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v2/items/movie-1/streams?media_source_id=source-1', expect.any(Object),
    )
  })

  it('loads normalized intro segments from v2', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      has_intro: true, start_seconds: 10, end_seconds: 80, duration_seconds: 70,
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.intro('movie-1')).resolves.toEqual({
      hasIntro: true, start: 10, end: 80, duration: 70,
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/v2/items/movie-1/intro', expect.any(Object))
  })

  it('posts typed library filters without encoding them into a URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ items: [], total: 0, start: 0 }),
      { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await api.queryItems({
      scope: { parent_id: 'library-1', include_item_types: [], media_types: [], recursive: false },
      page: { start_index: 0, limit: 50 },
      sort: { field: 'SortName', direction: 'Ascending' },
      filters: { playstate: 'unplayed', genres: ['Drama'] },
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/v2/items/query', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({
        scope: { parent_id: 'library-1', include_kinds: [], media_kinds: [], recursive: false },
        page: { start: 0, limit: 50 },
        sort: { field: 'name', direction: 'ascending' },
        filters: { playstate: 'unplayed', genres: ['Drama'] },
      }),
    }))
  })

  it('loads ordinary library browsing through v2 query', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ items: [], total: 0, start: 20 }), { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await api.items({ parentId: 'library-1', type: 'Movie', startIndex: 20, limit: 50 })
    expect(fetchMock).toHaveBeenCalledWith('/api/v2/items/query', expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('"parent_id":"library-1"'),
    }))
  })

  it('loads unfiltered and filtered prefixes through v2', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(
      JSON.stringify({ prefixes: ['A', '#'] }), { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.itemPrefixes('library-1')).resolves.toEqual({ Prefixes: ['A', '#'] })
    await expect(api.queryPrefixes({
      scope: { parent_id: 'library-1', include_item_types: [], media_types: [], recursive: false },
      page: { start_index: 0, limit: 50 },
      sort: { field: 'SortName', direction: 'Ascending' },
      filters: { favorite: true },
    })).resolves.toEqual({ Prefixes: ['A', '#'] })
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v2/items/prefixes', '/api/v2/items/prefixes',
    ])
  })

  it('loads provider-supported filter controls through v2', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ controls: [] }), { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.filterOptions({
      parentId: 'library-1', includeItemTypes: 'Movie', mediaTypes: 'Video',
    })).resolves.toEqual({ controls: [] })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v2/items/filter-options?parent_id=library-1&include_kinds=movie&media_kinds=video',
      expect.any(Object),
    )
  })

  it('loads grouped normalized search through v2', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      query: 'Arrival', groups: [{ id: 'movies', label: 'Movies', items: [] }],
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.groupedSearch('Arrival')).resolves.toEqual({
      query: 'Arrival', groups: [{ id: 'movies', label: 'Movies', items: [] }],
    })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v2/items/search/groups?q=Arrival', expect.any(Object),
    )
  })

  it('loads normalized item sections through v2', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      section: 'related', items: [],
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.itemSection('movie-1', 'related')).resolves.toEqual({
      section: 'related', items: [],
    })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v2/items/movie-1/sections/related', expect.any(Object),
    )
  })

  it('rejects non-success JSON responses with a typed error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'Party has no host' }),
      {
        status: 423,
        headers: { 'Content-Type': 'application/json' },
      },
    )))

    await expect(apiFetch('/api/libraries')).rejects.toEqual(
      new ApiError(423, 'Party has no host', { detail: 'Party has no host' }),
    )
  })

  it('preserves structured rate-limit details and Retry-After', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({
        detail: 'Too many party join attempts. Try again in 42 seconds.',
        code: 'rate_limited',
        retry_after: 42,
      }),
      {
        status: 429,
        headers: { 'Content-Type': 'application/json', 'Retry-After': '42' },
      },
    )))

    await expect(api.joinParty('ABC123', 'client-1', 'Alice')).rejects.toMatchObject({
      status: 429,
      message: 'Too many party join attempts. Try again in 42 seconds.',
      code: 'rate_limited',
      retryAfter: 42,
    })
  })

  it('preserves readable multipart upload errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      'Upload too large',
      { status: 413, statusText: 'Content Too Large' },
    )))

    await expect(api.avatarUpload(new File(['x'], 'avatar.png'))).rejects.toEqual(
      new ApiError(413, 'Upload too large', 'Upload too large'),
    )
  })

  it('keeps HLS validation out of runtime admin updates', async () => {
    const config: AdminConfig = {
      BINGE_WATCH_COUNTDOWN_SECONDS: 10,
      BINGE_WATCH_ENABLED: true,
      CONSOLE_LOG_LEVEL: 'INFO',
      ENABLED_QUALITY_OPTIONS: { auto: [] },
      ENABLE_RATE_LIMITING: true,
      FORCE_TRANSCODE: false,
      HLS_TOKEN_EXPIRY: 300,
      LATE_JOIN_VOTE_COOLDOWN_SECONDS: 30,
      LATE_JOIN_VOTE_ENABLED: true,
      LATE_JOIN_VOTE_TIMEOUT_SECONDS: 30,
      LOG_FILE: 'watchparty.log',
      LOG_FORMAT: 'text',
      LOG_LEVEL: 'INFO',
      LOG_MAX_SIZE: 10,
      LOG_TO_FILE: false,
      MAX_USERS_PER_PARTY: 20,
      RATE_LIMIT_API_CALLS: '100/minute',
      RATE_LIMIT_AVATAR_RECOVERY: '5/minute',
      RATE_LIMIT_CHAT: '30/minute',
      RATE_LIMIT_LOGIN: '5/minute',
      RATE_LIMIT_PARTY_CREATION: '5/minute',
      RATE_LIMIT_SOCKET_CONNECTIONS: '20/minute',
      REQUIRE_LOGIN: false,
      STATIC_SESSION_ENABLED: false,
      STATIC_SESSION_ID: '',
    }
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ success: true, changed: [], rejected: [], restart_required: [] }),
      { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await api.adminUpdateConfig(config)

    const request = fetchMock.mock.calls[0]![1] as RequestInit
    const payload = JSON.parse(request.body as string) as Record<string, unknown>
    expect(payload).toEqual(config)
    expect(payload).not.toHaveProperty('ENABLE_HLS_TOKEN_VALIDATION')
  })

  it('builds bounded indexed artwork proxy URLs', () => {
    expect(api.imageUrl('movie-1', 'Backdrop', {
      index: 2, maxWidth: 1600, maxHeight: 900, quality: 85,
    })).toBe('/api/v2/items/movie-1/images/backdrop?index=2&max_width=1600&max_height=900&quality=85')
  })

  it('builds provider-neutral v2 subtitle URLs', () => {
    expect(api.subtitleUrl('movie-1', 'source-1', 3)).toBe(
      '/api/v2/items/movie-1/subtitles/source-1/3',
    )
  })
})

describe('item kind projection', () => {
  // v2 reports snake_case `kind`; the components switch on the Emby `Type`.
  // An unmapped kind lands on 'Other', which is in none of LibraryBrowser's
  // type sets, so the row becomes unclickable, unopenable and filtered out of
  // mixed listings, with no error anywhere to say so.
  const kindToType: Record<string, string> = {
    audio: 'Audio',
    box_set: 'BoxSet',
    collection_folder: 'CollectionFolder',
    episode: 'Episode',
    folder: 'Folder',
    movie: 'Movie',
    music_album: 'MusicAlbum',
    music_artist: 'MusicArtist',
    music_video: 'MusicVideo',
    person: 'Person',
    playlist: 'Playlist',
    season: 'Season',
    series: 'Series',
    trailer: 'Trailer',
    user_view: 'UserView',
    video: 'Video',
  }

  function itemOfKind(kind: string) {
    return {
      id: `item-${kind}`,
      name: kind,
      kind,
      collection_kind: null,
      overview: '',
      runtime_seconds: null,
      production_year: null,
      parent_id: null,
      series_id: null,
      series_name: null,
      season_id: null,
      season_name: null,
      index_number: null,
      parent_index_number: null,
      is_folder: false,
      is_playable: false,
      is_browsable: false,
      has_primary_image: false,
      backdrop_count: 0,
      primary_image_aspect_ratio: null,
      user_state: {
        playback_position_seconds: 0,
        played_percentage: null,
        played: false,
        favorite: false,
      },
      media_source_count: 0,
    }
  }

  it('maps every kind the backend can emit to its Emby Type', async () => {
    const kinds = Object.keys(kindToType)
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: kinds.map(itemOfKind),
      total: kinds.length,
      start: 0,
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const page = await api.libraries()

    expect(
      Object.fromEntries(page.Items.map((item) => [item.Name, item.Type])),
    ).toEqual(kindToType)
  })

  it('never leaves a known kind as Other', async () => {
    // 'Other' is the tell. Before this map was completed, a Collections
    // library rendered every row as Other: cards printing the literal word,
    // ignoring every click.
    const kinds = Object.keys(kindToType)
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: kinds.map(itemOfKind),
      total: kinds.length,
      start: 0,
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const page = await api.libraries()

    expect(page.Items.filter((item) => item.Type === 'Other')).toEqual([])
  })

  it('still falls back to Other for a kind nobody has taught it', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [itemOfKind('holographic_broadcast')],
      total: 1,
      start: 0,
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const page = await api.libraries()

    expect(page.Items[0]?.Type).toBe('Other')
  })
})

describe('browse ordering', () => {
  function queryBody(fetchMock: ReturnType<typeof vi.fn>) {
    const [, init] = fetchMock.mock.calls[0] ?? []
    return JSON.parse((init as RequestInit).body as string)
  }

  function emptyPage() {
    return new Response(JSON.stringify({ items: [], total: 0, start: 0 }), { status: 200 })
  }

  it('asks for index order when the browser is not in alphabetical mode', async () => {
    // The parents where alphabeticalMode is false are exactly Series and
    // Season, the two that need index order. Losing it listed a 10-season
    // show as "Season 1, Season 10, Season 11, Season 2".
    const fetchMock = vi.fn().mockResolvedValue(emptyPage())
    vi.stubGlobal('fetch', fetchMock)

    await api.items({ parentId: 'series-1', sortMode: 'default' })

    expect(queryBody(fetchMock).sort).toEqual({ field: 'index', direction: 'ascending' })
  })

  it('asks for name order in alphabetical mode', async () => {
    const fetchMock = vi.fn().mockResolvedValue(emptyPage())
    vi.stubGlobal('fetch', fetchMock)

    await api.items({ parentId: 'library-1', sortMode: 'alphabetical' })

    expect(queryBody(fetchMock).sort).toEqual({ field: 'name', direction: 'ascending' })
  })

  it('defaults to index order when no sortMode is given', async () => {
    const fetchMock = vi.fn().mockResolvedValue(emptyPage())
    vi.stubGlobal('fetch', fetchMock)

    await api.items({ parentId: 'series-1' })

    expect(queryBody(fetchMock).sort.field).toBe('index')
  })
})
