"""Tests for EnterprisePackBuilder's two portable creation modes."""

import pytest
from pydantic import ValidationError

from sq_bi_contracts.domain_pack import DomainPackManifest, PackStandardField
from sq_bi_contracts.enterprise_pack import (
    CreateEnterprisePackRequest,
    PackCreateMode,
    PackVersionState,
)

from sq_bi_runtime.enterprise_pack_store import EnterprisePackStore
from sq_bi_runtime.enterprise_pack_builder import EnterprisePackBuilder


@pytest.fixture
def store(tmp_path):
    return EnterprisePackStore(tmp_path / "enterprise_packs.db")


@pytest.fixture
def builder(store):
    return EnterprisePackBuilder(store)


def _req(**kwargs) -> CreateEnterprisePackRequest:
    defaults = dict(
        name="测试包",
        mode=PackCreateMode.blank,
        created_by="tester",
    )
    defaults.update(kwargs)
    return CreateEnterprisePackRequest(**defaults)


def _manifest(pack_id: str = "logistics", version: str = "1.0.0") -> DomainPackManifest:
    return DomainPackManifest(
        pack_id=pack_id,
        namespace="official",
        name="物流官方包",
        version=version,
        standard_fields=[
            PackStandardField(
                field_id="shipment_no",
                business_name="运单号",
                data_type="TEXT",
            )
        ],
    )


# ── blank mode ────────────────────────────────────────────────────────────────

def test_blank_creates_empty_draft(builder, store):
    pack = builder.build(_req(mode=PackCreateMode.blank))
    assert pack.version_state == PackVersionState.draft
    assert pack.create_mode == PackCreateMode.blank
    assert pack.base_pack_id is None
    assert "data_source_id" not in pack.model_dump()
    assert pack.draft.entities == []
    assert pack.draft.fields == []
    assert pack.draft.metrics == []


# ── extend_official mode ──────────────────────────────────────────────────────

def test_extend_official_records_base_lineage_without_copying_assets(builder, store):
    manifest = _manifest("logistics", "2.1.0")
    pack = builder.build(
        _req(mode=PackCreateMode.extend_official, base_pack_id="logistics"),
        official_manifest=manifest,
    )
    assert pack.create_mode == PackCreateMode.extend_official
    assert pack.base_pack_id == "logistics"
    assert pack.base_pack_version == "2.1.0"
    # Delta layers never copy official standard fields into the draft.
    assert pack.draft.fields == []
    assert pack.draft.metrics == []


def test_extend_official_requires_manifest(builder):
    with pytest.raises(ValueError, match="official_manifest"):
        builder.build(_req(mode=PackCreateMode.extend_official, base_pack_id="logistics"))


# ── removed modes are rejected at the contract layer ───────────────────────────

def test_clone_enterprise_mode_no_longer_exists() -> None:
    with pytest.raises(ValidationError):
        _req(mode="clone_enterprise")


def test_ai_from_profile_mode_no_longer_exists() -> None:
    with pytest.raises(ValidationError):
        _req(mode="ai_from_profile")


def test_builder_rejects_unknown_mode(builder) -> None:
    req = _req(mode=PackCreateMode.blank).model_copy(update={"mode": "bogus_mode"})
    with pytest.raises(ValueError, match="Unknown creation mode"):
        builder.build(req)
