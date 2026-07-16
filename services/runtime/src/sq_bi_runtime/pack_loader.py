from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sq_bi_contracts.domain_pack import (
    DomainPackManifest,
    PackAsset,
    PackDependency,
    PackLoadResult,
    PackStandardField,
)


def load_manifest(pack_dir: str | Path) -> DomainPackManifest:
    """Load and validate a domain pack manifest from *pack_dir*.

    Looks for pack.yaml or manifest.yaml in the pack directory.
    Raises ValueError on malformed or missing manifests.
    """
    path = Path(pack_dir)
    if not path.is_dir():
        raise ValueError(f"Domain pack directory not found: {pack_dir}")

    manifest_path = path / "pack.yaml"
    if not manifest_path.exists():
        manifest_path = path / "manifest.yaml"
    if not manifest_path.exists():
        raise ValueError(f"No pack.yaml or manifest.yaml found in {pack_dir}")

    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Manifest must be a YAML mapping: {manifest_path}")

    try:
        raw_sf = raw.get("standard_fields") or []
        standard_fields = [
            PackStandardField(
                field_id=str(sf["field_id"]),
                business_name=str(sf.get("business_name", "")),
                data_type=str(sf.get("data_type", "text")),
                description=str(sf["description"]) if sf.get("description") else None,
                enum_values=list(sf.get("enum_values") or []),
                required=bool(sf.get("required", False)),
            )
            for sf in raw_sf
        ]
        manifest = DomainPackManifest(
            pack_id=str(raw.get("pack_id", "")),
            namespace=str(raw.get("namespace", "")),
            name=str(raw.get("name", "")),
            version=str(raw.get("version", "1.0.0")),
            description=str(raw.get("description") or ""),
            author=str(raw.get("author") or ""),
            min_engine_version=str(raw.get("min_engine_version") or ""),
            dependencies=[
                PackDependency(**dep) for dep in (raw.get("dependencies") or [])
            ],
            assets=[
                PackAsset(**asset) for asset in (raw.get("assets") or [])
            ],
            tags=list(raw.get("tags") or []),
            enabled=bool(raw.get("enabled", True)),
            standard_fields=standard_fields,
        )
    except Exception as exc:
        raise ValueError(f"Failed to parse manifest {manifest_path}: {exc}") from exc

    if not manifest.pack_id:
        raise ValueError(f"Manifest missing required 'pack_id' field: {manifest_path}")
    if not manifest.namespace:
        raise ValueError(f"Manifest missing required 'namespace' field: {manifest_path}")

    # Verify assets exist
    for asset in manifest.assets:
        asset_path = path / asset.path
        if not asset_path.exists():
            raise ValueError(
                f"Asset '{asset.path}' declared in manifest but not found at {asset_path}"
            )

    # Official pack semantic validation
    violations = validate_official_pack_semantics(path, raw)
    if violations:
        bullet_list = "\n  - ".join(violations)
        raise ValueError(
            f"Official pack '{manifest.pack_id}' failed standard-field validation:\n"
            f"  - {bullet_list}"
        )

    return manifest


class PackRegistry:
    """In-memory registry of loaded domain packs with namespace isolation."""

    def __init__(self) -> None:
        self._packs: dict[str, tuple[DomainPackManifest, Path]] = {}
        self._disabled: set[str] = set()

    def install(self, manifest: DomainPackManifest, pack_dir: Path) -> PackLoadResult:
        errors: list[str] = []
        warnings: list[str] = []

        if not manifest.enabled:
            self._disabled.add(manifest.pack_id)
        self._packs[manifest.pack_id] = (manifest, pack_dir)
        return PackLoadResult(
            pack_id=manifest.pack_id,
            success=not bool(errors),
            errors=errors,
            warnings=warnings,
        )

    def enable(self, pack_id: str) -> bool:
        if pack_id in self._packs:
            self._disabled.discard(pack_id)
            return True
        return False

    def disable(self, pack_id: str) -> bool:
        if pack_id in self._packs:
            self._disabled.add(pack_id)
            return True
        return False

    def is_enabled(self, pack_id: str) -> bool:
        return pack_id in self._packs and pack_id not in self._disabled

    def list_packs(self) -> list[DomainPackManifest]:
        return [manifest for manifest, _ in self._packs.values()]

    def list_enabled_pack_entries(self) -> list[tuple[DomainPackManifest, Path]]:
        """Return enabled manifests with their roots for read-only asset providers."""
        return [
            (manifest, pack_dir)
            for pack_id, (manifest, pack_dir) in self._packs.items()
            if pack_id not in self._disabled and pack_dir.is_dir()
        ]

    def get_assets_by_type(self, asset_type: str) -> list[tuple[str, PackAsset]]:
        """Return (namespace, asset) for all enabled packs matching *asset_type*."""
        result: list[tuple[str, PackAsset]] = []
        for pack_id, (manifest, _) in self._packs.items():
            if pack_id in self._disabled:
                continue
            for asset in manifest.assets:
                if asset.asset_type == asset_type:
                    result.append((manifest.namespace, asset))
        return result

    def get_semantic_catalog_paths(self) -> list[Path]:
        """Return resolved file paths for all semantic YAML assets in enabled packs."""
        paths: list[Path] = []
        for pack_id, (manifest, pack_dir) in self._packs.items():
            if pack_id in self._disabled:
                continue
            for asset in manifest.assets:
                if asset.asset_type == "semantic":
                    p = pack_dir / asset.path
                    if p.exists():
                        paths.append(p)
        return paths


def validate_official_pack_semantics(pack_dir: Path, manifest_raw: dict) -> list[str]:
    """Validate that an official pack's semantic YAML has no bare physical-SQL metrics.

    Returns a list of violation messages (empty = valid).
    Metrics must have either `logical_formula` or `escape_hatch: true`.
    Only runs when the manifest declares `official: true`.
    """
    if not manifest_raw.get("official"):
        return []

    violations: list[str] = []
    for asset_raw in manifest_raw.get("assets") or []:
        if asset_raw.get("asset_type") != "semantic":
            continue
        semantic_path = pack_dir / str(asset_raw.get("path", ""))
        if not semantic_path.exists():
            continue
        try:
            semantic = yaml.safe_load(semantic_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        for metric in semantic.get("metrics") or []:
            code = metric.get("metric_code", "<unknown>")
            has_logical = bool(metric.get("logical_formula"))
            has_escape = bool(metric.get("escape_hatch"))
            if not has_logical and not has_escape:
                violations.append(
                    f"metric '{code}' has physical SQL formula but no logical_formula "
                    f"and no escape_hatch declaration"
                )
    return violations


_registry = PackRegistry()


def get_registry() -> PackRegistry:
    return _registry


def install_pack(pack_dir: str | Path) -> PackLoadResult:
    """Load, validate, and register a domain pack."""
    path = Path(pack_dir)
    manifest = load_manifest(path)
    return _registry.install(manifest, path)
