import httpx


def test_fake_emby_auth_library_hls_and_recording(fake_emby_server) -> None:
    with httpx.Client(base_url=fake_emby_server.url) as client:
        auth = client.post(
            "/emby/Users/AuthenticateByName",
            json={"Username": "Alice", "Pw": "password"},
        )
        libraries = client.get("/emby/Users/user-1/Views")
        playlist = client.get("/emby/Videos/movie-1/main.m3u8")
        intros = client.get("/emby/Items/Intros", params={"api_key": "test-key"})
        item = client.get("/emby/Items/movie-1")
        subtitle = client.get("/emby/Videos/movie-1/source-1/Subtitles/3/Stream.vtt")
        recorded = client.get("/__test__/requests")

    assert auth.status_code == 200
    assert auth.json()["AccessToken"] == "fake-access-token"
    assert libraries.json()["Items"][0]["CollectionType"] == "movies"
    assert playlist.text.endswith("\r\n")
    assert "segment0.ts" in playlist.text
    assert intros.status_code == 200
    assert isinstance(intros.json(), list)
    streams = item.json()["MediaSources"][0]["MediaStreams"]
    assert [stream["Index"] for stream in streams if stream["Type"] == "Audio"] == [1, 2]
    # The flags, not just the indices. A second audio stream is only useful as
    # a fixture if which one is default is actually pinned; without this,
    # inverting default-track selection keeps the suite green.
    assert [stream["IsDefault"] for stream in streams if stream["Type"] == "Audio"] == [
        True,
        False,
    ]
    assert [stream["Index"] for stream in streams if stream["Type"] == "Subtitle"] == [3]
    assert subtitle.text.startswith("WEBVTT\n")
    request_rows = recorded.json()["requests"]
    assert any(row["path"].endswith("AuthenticateByName") for row in request_rows)
    assert "password" not in recorded.text


def test_fake_subtitle_stream_rejects_parameters_real_emby_would_reject(
    fake_emby_server,
) -> None:
    """The fake must not answer WEBVTT to anything.

    While it discarded item, source and index, a proxy that dropped or mangled
    any of them still looked correct against this harness.
    """
    with httpx.Client(base_url=fake_emby_server.url) as client:
        good = client.get("/emby/Videos/movie-1/source-1/Subtitles/3/Stream.vtt")
        wrong_item = client.get("/emby/Videos/movie-99/source-1/Subtitles/3/Stream.vtt")
        wrong_source = client.get("/emby/Videos/movie-1/source-99/Subtitles/3/Stream.vtt")
        # Index 1 is an Audio stream, so it is a real index but not a subtitle.
        wrong_index = client.get("/emby/Videos/movie-1/source-1/Subtitles/1/Stream.vtt")

    assert good.status_code == 200
    assert good.text.startswith("WEBVTT\n")
    assert wrong_item.status_code == 404
    assert wrong_source.status_code == 404
    assert wrong_index.status_code == 404
