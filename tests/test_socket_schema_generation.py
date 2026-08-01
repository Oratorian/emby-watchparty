from scripts.generate_socket_types import render


def test_generated_contract_contains_typed_server_events() -> None:
    schema, typescript = render()

    assert '"server_to_client"' in schema
    assert "export interface ServerToClientPayloads" in typescript
    assert '"chat_message": {' in typescript
    assert '"message": string' in typescript
