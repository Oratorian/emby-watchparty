from scripts.generate_socket_types import render


def test_generated_contract_contains_typed_server_events() -> None:
    schema, typescript = render()

    assert '"server_to_client"' in schema
    assert "export interface ServerToClientPayloads" in typescript
    assert '"chat_message": {' in typescript
    assert '"message": string' in typescript
    video_block = typescript.split('"video_selected": {', 1)[1].split("  }", 1)[0]
    assert '"item_id": string' in video_block
    assert "unknown" not in video_block
    assert '"stopped_by": string' in typescript
    assert '"previous_host"?: string | null' in typescript
    assert '"retry_after"?: number | null' in typescript
    ended_block = typescript.split('"video_ended": {', 2)[2].split("  }", 1)[0]
    assert '"party_id": string' in ended_block
    assert '"timestamp": string' in ended_block
