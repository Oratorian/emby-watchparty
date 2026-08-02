import httpx


def test_fake_emby_auth_library_hls_and_recording(fake_emby_server) -> None:
    with httpx.Client(base_url=fake_emby_server.url) as client:
        auth = client.post(
            "/emby/Users/AuthenticateByName",
            json={"Username": "Alice", "Pw": "password"},
        )
        libraries = client.get("/emby/Users/user-1/Views")
        playlist = client.get("/emby/Videos/movie-1/main.m3u8")
        recorded = client.get("/__test__/requests")

    assert auth.status_code == 200
    assert auth.json()["AccessToken"] == "fake-access-token"
    assert libraries.json()["Items"][0]["CollectionType"] == "movies"
    assert playlist.text.endswith("\r\n")
    assert "segment0.ts" in playlist.text
    request_rows = recorded.json()["requests"]
    assert any(row["path"].endswith("AuthenticateByName") for row in request_rows)
    assert "password" not in recorded.text
