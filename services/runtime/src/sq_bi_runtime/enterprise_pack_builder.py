"""Portable enterprise pack builder.

All modes converge to one EnterprisePack draft shape via EnterprisePackStore.
The builder seeds the draft from the appropriate source; caller then calls
store.get() to retrieve the created pack.

Modes
-----
  extend_official   — pin an official DomainPackManifest as a read-only base
  blank             — empty draft, no seeding
"""

from __future__ import annotations

import logging
from uuid import uuid4

from sq_bi_contracts.enterprise_pack import (
    CreateEnterprisePackRequest,
    EnterprisePack,
    EnterprisePackDraft,
    PackCreateMode,
    PackEnterpriseField,
    PackEnterpriseMetric,
)
from sq_bi_contracts.domain_pack import DomainPackManifest
from sq_bi_contracts.metrics import MetricFormula

from .enterprise_pack_store import EnterprisePackStore

logger = logging.getLogger(__name__)


class EnterprisePackBuilder:
    """Builds an empty enterprise delta or an empty portable pack."""

    def __init__(self, store: EnterprisePackStore) -> None:
        self._store = store

    def build(
        self,
        req: CreateEnterprisePackRequest,
        *,
        official_manifest: DomainPackManifest | None = None,
    ) -> EnterprisePack:
        """Create an EnterprisePack draft according to *req.mode*.

        Args:
            req: The creation request.
            official_manifest: Required when mode == extend_official.

        Returns:
            The newly created EnterprisePack (draft state).
        """
        mode = req.mode

        if mode == PackCreateMode.blank:
            return self._build_blank(req)

        if mode == PackCreateMode.extend_official:
            if official_manifest is None:
                raise ValueError("official_manifest is required for extend_official mode.")
            return self._build_extend_official(req, official_manifest)

        raise ValueError(f"Unknown creation mode: {mode!r}")

    # ── Mode implementations ──────────────────────────────────────────────────

    def _build_blank(self, req: CreateEnterprisePackRequest) -> EnterprisePack:
        pack = self._store.create(req)
        logger.info("enterprise_pack.created.blank", extra={"pack_id": pack.pack_id})
        return pack

    def _build_extend_official(
        self,
        req: CreateEnterprisePackRequest,
        manifest: DomainPackManifest,
    ) -> EnterprisePack:
        pack = self._store.create(req)
        # Delta layers intentionally contain no copied base assets. The caller
        # resolves the pinned manifest when rendering or deploying the pack.
        seeded = self._store.update_meta(
            pack.pack_id, base_pack_version=manifest.version
        )
        logger.info(
            "enterprise_pack.created.extend_official",
            extra={"pack_id": pack.pack_id, "base_pack_id": manifest.pack_id, "base_version": manifest.version},
        )
        return seeded
