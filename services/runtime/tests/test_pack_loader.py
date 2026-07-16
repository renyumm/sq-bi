from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sq_bi_runtime.pack_loader import (
    PackRegistry,
    install_pack,
    load_manifest,
)


@pytest.fixture
def tms_pack_dir(tmp_path: Path) -> Path:
    """Create a minimal TMS domain pack fixture."""
    pack_dir = tmp_path / "tms"
    pack_dir.mkdir(parents=True)
    semantic_file = pack_dir / "semantic.yaml"
    semantic_file.write_text("tables: []\nfields: []\n")
    manifest = {
        "pack_id": "tms",
        "namespace": "tms",
        "name": "TMS Domain Pack",
        "version": "1.0.0",
        "description": "TMS manufacturing analytics",
        "dependencies": [],
        "assets": [
            {"path": "semantic.yaml", "asset_type": "semantic", "description": "Semantic catalog"},
        ],
        "tags": ["manufacturing", "tms"],
        "enabled": True,
    }
    (pack_dir / "pack.yaml").write_text(yaml.dump(manifest))
    return pack_dir


def test_load_manifest_success(tms_pack_dir: Path) -> None:
    manifest = load_manifest(tms_pack_dir)
    assert manifest.pack_id == "tms"
    assert manifest.namespace == "tms"
    assert len(manifest.assets) == 1


def test_load_manifest_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not found"):
        load_manifest(tmp_path / "nonexistent")


def test_load_manifest_missing_asset(tmp_path: Path) -> None:
    pack_dir = tmp_path / "badpack"
    pack_dir.mkdir()
    manifest = {
        "pack_id": "bad",
        "namespace": "bad",
        "name": "Bad Pack",
        "version": "1.0.0",
        "assets": [{"path": "missing.yaml", "asset_type": "semantic"}],
    }
    (pack_dir / "pack.yaml").write_text(yaml.dump(manifest))
    with pytest.raises(ValueError, match="not found at"):
        load_manifest(pack_dir)


def test_registry_install_and_list(tms_pack_dir: Path) -> None:
    registry = PackRegistry()
    manifest = load_manifest(tms_pack_dir)
    result = registry.install(manifest, tms_pack_dir)
    assert result.success is True
    assert len(registry.list_packs()) == 1


def test_registry_enable_disable(tms_pack_dir: Path) -> None:
    registry = PackRegistry()
    manifest = load_manifest(tms_pack_dir)
    registry.install(manifest, tms_pack_dir)
    assert registry.is_enabled("tms") is True
    registry.disable("tms")
    assert registry.is_enabled("tms") is False
    registry.enable("tms")
    assert registry.is_enabled("tms") is True


def test_registry_get_assets_by_type(tms_pack_dir: Path) -> None:
    registry = PackRegistry()
    manifest = load_manifest(tms_pack_dir)
    registry.install(manifest, tms_pack_dir)
    assets = registry.get_assets_by_type("semantic")
    assert len(assets) == 1
    ns, asset = assets[0]
    assert ns == "tms"
    assert asset.asset_type == "semantic"


def test_two_packs_coexist(tmp_path: Path) -> None:
    # Pack 1: tms
    tms_dir = tmp_path / "tms"
    tms_dir.mkdir()
    (tms_dir / "tms.yaml").write_text("")
    tms_manifest = {
        "pack_id": "tms",
        "namespace": "tms",
        "name": "TMS",
        "assets": [{"path": "tms.yaml", "asset_type": "semantic"}],
    }
    (tms_dir / "pack.yaml").write_text(yaml.dump(tms_manifest))

    # Pack 2: wms
    wms_dir = tmp_path / "wms"
    wms_dir.mkdir()
    (wms_dir / "wms.yaml").write_text("")
    wms_manifest = {
        "pack_id": "wms",
        "namespace": "wms",
        "name": "WMS",
        "assets": [{"path": "wms.yaml", "asset_type": "semantic"}],
    }
    (wms_dir / "pack.yaml").write_text(yaml.dump(wms_manifest))

    registry = PackRegistry()
    registry.install(load_manifest(tms_dir), tms_dir)
    registry.install(load_manifest(wms_dir), wms_dir)
    assert len(registry.list_packs()) == 2
    assets = registry.get_assets_by_type("semantic")
    assert len(assets) == 2  # both packs contribute


def test_disabled_pack_removes_assets(tmp_path: Path) -> None:
    pack_dir = tmp_path / "apack"
    pack_dir.mkdir()
    (pack_dir / "data.yaml").write_text("")
    manifest_data = {
        "pack_id": "apack",
        "namespace": "apack",
        "name": "A Pack",
        "assets": [{"path": "data.yaml", "asset_type": "semantic"}],
    }
    (pack_dir / "pack.yaml").write_text(yaml.dump(manifest_data))

    registry = PackRegistry()
    registry.install(load_manifest(pack_dir), pack_dir)
    assert len(registry.get_assets_by_type("semantic")) == 1
    registry.disable("apack")
    assert len(registry.get_assets_by_type("semantic")) == 0


def test_install_pack_integration(tms_pack_dir: Path) -> None:
    result = install_pack(tms_pack_dir)
    assert result.success is True
    assert result.pack_id == "tms"


def test_pack_registry_semantic_paths_resolved(tmp_path: Path) -> None:
    """get_semantic_catalog_paths() returns actual resolved paths."""
    from sq_bi_runtime.pack_loader import PackRegistry, load_manifest
    from sq_bi_contracts.domain_pack import DomainPackManifest, PackAsset

    pack_dir = tmp_path / "tms_pack"
    pack_dir.mkdir()
    semantic_file = pack_dir / "tms_semantic.yaml"
    semantic_file.write_text("data_sources: []\ntables: []\n")
    manifest_file = pack_dir / "pack.yaml"
    manifest_file.write_text(
        "pack_id: tms\n"
        "namespace: tms\n"
        "name: TMS Pack\n"
        "version: '1.0'\n"
        "assets:\n"
        "  - asset_type: semantic\n"
        "    path: tms_semantic.yaml\n"
    )
    registry = PackRegistry()
    manifest = load_manifest(pack_dir)
    registry.install(manifest, pack_dir)
    paths = registry.get_semantic_catalog_paths()
    assert len(paths) == 1
    assert paths[0].exists()
