from __future__ import annotations

import io
import tarfile
from pathlib import Path

from fastapi.testclient import TestClient

from sq_bi_runtime.api import create_app
from sq_bi_runtime.pack_dist import extract_pack, pack_to_tar


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    config = tmp_path / "config.yaml"
    config.write_text(
        f"base_url: http://localhost/v1\nkey: test\nmodel: test\nstorage_path: {tmp_path / 'storage'}\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(config), raise_server_exceptions=False)
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert login.status_code == 200
    return client, {"X-Session-Id": login.json()["data"]["session_id"]}


def _archive(tmp_path: Path) -> Path:
    pack = tmp_path / "source-pack"
    pack.mkdir()
    (pack / "semantic.yaml").write_text(
        "metrics:\n  - metric_code: demo.total\n    name: 总量\nskills: []\nreports: []\n",
        encoding="utf-8",
    )
    (pack / "pack.yaml").write_text(
        """pack_id: imported_demo
namespace: imported_demo
name: 导入测试领域包
version: 1.0.0
description: 文件导入测试
author: test
tags: [测试]
standard_fields:
  - field_id: imported_demo.id
    business_name: 标识
    data_type: text
    required: true
assets:
  - path: semantic.yaml
    asset_type: semantic
""",
        encoding="utf-8",
    )
    archive = tmp_path / "imported_demo.sqbipack"
    pack_to_tar(pack, archive)
    return archive


def test_preview_then_import_pack_without_activation(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    archive = _archive(tmp_path)
    with archive.open("rb") as source:
        preview = client.post(
            "/api/v1/admin/packs/import/preview",
            headers=headers,
            files={"file": (archive.name, source, "application/gzip")},
        )
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["can_import"] is True
    assert preview.json()["data"]["metric_count"] == 1

    with archive.open("rb") as source:
        imported = client.post(
            "/api/v1/admin/packs/import",
            headers=headers,
            files={"file": (archive.name, source, "application/gzip")},
        )
    assert imported.status_code == 200, imported.text

    packs = client.get("/api/v1/admin/packs", headers=headers).json()["data"]
    installed = next(item for item in packs if item["pack_id"] == "imported_demo")
    assert installed["distribution_source"] == "imported"
    assert installed["deployments"] == []


def test_extract_pack_rejects_path_traversal(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        info = tarfile.TarInfo("../outside.txt")
        content = b"unsafe"
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    payload.seek(0)
    try:
        extract_pack(payload, tmp_path / "extract")
    except ValueError as exc:
        assert "不安全路径" in str(exc)
    else:
        raise AssertionError("path traversal archive should be rejected")
