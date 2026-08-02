import httpx


def test_readiness_retries_transient_emby_read_failures(live_watchparty) -> None:
    with httpx.Client(base_url=live_watchparty.fake.url) as controls:
        controls.post(
            "/__test__/behavior",
            json={"transient_failures": {"/emby/System/Info/Public": 2}},
        ).raise_for_status()

    response = httpx.get(f"{live_watchparty.url}/api/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
    attempts = [r for r in recorded if r["path"] == "/emby/System/Info/Public"]
    assert len(attempts) == 3


def test_admin_authentication_write_is_not_retried(live_watchparty) -> None:
    with httpx.Client(base_url=live_watchparty.fake.url) as controls:
        controls.post(
            "/__test__/behavior",
            json={
                "transient_failures": {
                    "/emby/Users/AuthenticateByName": 2,
                }
            },
        ).raise_for_status()

    response = httpx.post(
        f"{live_watchparty.url}/api/admin/login",
        json={"username": "Alice", "password": "wrong"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    recorded = httpx.get(f"{live_watchparty.fake.url}/__test__/requests").json()["requests"]
    attempts = [r for r in recorded if r["path"] == "/emby/Users/AuthenticateByName"]
    assert len(attempts) == 1
