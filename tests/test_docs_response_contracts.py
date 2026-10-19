"""Exercise the response shapes that Swagger UI and ReDoc describe."""

import logging
import warnings
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from backend.app import build_api_app
from backend.src import dependencies
from backend.src.schemas import HTTPErrorResponse, ProxyErrorResponse, ReadinessResponse
from scripts.generate_openapi_types import render
from tests.support.credentials import TEST_SESSION_SECRET


@pytest.mark.parametrize("prefix", ["", "/watchparty"])
def test_both_documentation_uis_use_the_served_openapi_document(prefix):
    app = build_api_app(prefix=prefix)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        spec = app.openapi()
    client = TestClient(app)

    assert client.get("/openapi.json").json() == spec
    assert "url: '/openapi.json'" in client.get("/docs").text
    assert 'spec-url="/openapi.json"' in client.get("/redoc").text
    assert f"{prefix}/api/ready" in spec["paths"]
    operation_ids = [
        operation["operationId"]
        for methods in spec["paths"].values()
        for operation in methods.values()
    ]
    assert len(operation_ids) == len(set(operation_ids))
    documented_tags = {tag["name"] for tag in spec["tags"]}
    assert all(
        set(operation.get("tags", [])) <= documented_tags
        for methods in spec["paths"].values()
        for operation in methods.values()
    )


def test_every_documented_response_media_type_has_a_schema():
    spec = build_api_app().openapi()
    missing = [
        f"{method} {path}: {status} {media_type}"
        for path, methods in spec["paths"].items()
        for method, operation in methods.items()
        for status, response in operation["responses"].items()
        for media_type, body in response.get("content", {}).items()
        if not body.get("schema")
    ]
    assert not missing, missing


def test_output_defaults_are_required_without_changing_input_optionality():
    schemas = build_api_app().openapi()["components"]["schemas"]
    for name in ["JoinPartyResponse", "AudioStreamV2", "MediaItemV2", "AvatarCreatedResponse"]:
        assert set(schemas[name]["properties"]) == set(schemas[name]["required"]), name
    assert "avatar_uuid" not in schemas["JoinPartyRequest"]["required"]
    assert "start" not in schemas["CatalogPageV2"].get("required", [])

    # FastAPI emits `input` and `ctx` only when the validation error has them.
    generated = render()
    error_type = next(
        line for line in generated.splitlines() if line.startswith("export type ValidationError =")
    )
    assert '"ctx"?:' in error_type
    assert '"input"?:' in error_type
    assert '"code": "rate_limited"' in generated


def test_readiness_503_body_matches_its_documented_model():
    app = build_api_app()
    app.dependency_overrides[dependencies.get_config] = lambda: SimpleNamespace(
        MEDIA_SERVER_URL="", MEDIA_SERVER_API_KEY="", MEDIA_SERVER_TYPE="jellyfin"
    )
    app.dependency_overrides[dependencies.get_media_server] = lambda: None
    app.dependency_overrides[dependencies.get_avatar_store] = lambda: SimpleNamespace(
        readiness_check=lambda: False
    )
    response = TestClient(app).get("/api/ready")

    assert response.status_code == 503
    assert ReadinessResponse.model_validate(response.json()).model_dump() == response.json()
    documented = app.openapi()["paths"]["/api/ready"]["get"]["responses"]["503"]
    assert documented["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ReadinessResponse"
    }


def test_hls_documents_both_session_and_token_error_shapes():
    app = build_api_app()
    app.add_middleware(SessionMiddleware, secret_key=TEST_SESSION_SECRET)
    for dependency in [
        dependencies.get_config,
        dependencies.get_emby_client,
        dependencies.get_emby_gateway,
        dependencies.get_token_manager,
        dependencies.get_party_manager,
        dependencies.get_media_server,
        dependencies.get_hls_registry,
    ]:
        app.dependency_overrides[dependency] = lambda: None
    app.dependency_overrides[dependencies.get_logger] = lambda: logging.getLogger("schema-test")
    client = TestClient(app)
    missing_session = client.get("/hls/movie/master.m3u8")
    assert missing_session.status_code == 401
    assert (
        HTTPErrorResponse.model_validate(missing_session.json()).model_dump()
        == missing_session.json()
    )

    app.dependency_overrides[dependencies.require_host_token] = lambda: SimpleNamespace(
        party_id="PARTY"
    )
    app.dependency_overrides[dependencies.get_config] = lambda: SimpleNamespace(
        ENABLE_HLS_TOKEN_VALIDATION=True
    )
    missing_token = client.get("/hls/movie/master.m3u8")
    assert missing_token.status_code == 401
    assert (
        ProxyErrorResponse.model_validate(missing_token.json()).model_dump() == missing_token.json()
    )

    documented = app.openapi()["paths"]["/hls/{item_id}/master.m3u8"]["get"]["responses"]["401"]
    assert {
        item["$ref"] for item in documented["content"]["application/json"]["schema"]["anyOf"]
    } == {"#/components/schemas/HTTPErrorResponse", "#/components/schemas/ProxyErrorResponse"}


def test_hls_range_and_head_responses_describe_bytes_and_empty_bodies():
    paths = build_api_app().openapi()["paths"]
    for path, methods in paths.items():
        if path.startswith("/hls/"):
            for operation in methods.values():
                assert any(
                    parameter["name"] == "token" and parameter["in"] == "query"
                    for parameter in operation["parameters"]
                )
    for path in ["/hls/{stream_id}/resources/{resource_id}", "/hls/{item_id}/{subpath}"]:
        responses = paths[path]["get"]["responses"]
        assert any(
            parameter["name"] == "Range" and parameter["in"] == "header"
            for parameter in paths[path]["get"]["parameters"]
        )
        assert responses["206"]["content"]["video/MP2T"]["schema"] == {
            "type": "string",
            "format": "binary",
        }
        assert "Content-Range" in responses["416"]["headers"]
        assert "content" not in responses["416"]
    for path in ["/hls/{item_id}/master.m3u8", "/hls/{stream_id}/resources/{resource_id}"]:
        assert all(
            "content" not in response for response in paths[path]["head"]["responses"].values()
        )
