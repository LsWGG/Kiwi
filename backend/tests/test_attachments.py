"""附件上传：不设 20MB 上限，流式落盘。"""

from __future__ import annotations


async def test_attachment_over_twenty_megabytes_is_accepted(client, kb) -> None:
    payload = b"x" * (21 * 1024 * 1024 + 7)
    files = {"file": ("large.bin", payload, "application/octet-stream")}
    resp = await client.post(
        f"/api/attachments?kb_id={kb['id']}&any_type=true", files=files
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["size"] == len(payload)
    assert data["filename"] == "large.bin"

    deleted = await client.delete(
        f"/api/attachments/{data['id']}?kb_id={kb['id']}"
    )
    assert deleted.status_code == 204
