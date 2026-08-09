from scripts.generate_openapi_types import main


def test_generated_openapi_types_have_no_drift(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["generate_openapi_types.py", "--check"])
    assert main() == 0
