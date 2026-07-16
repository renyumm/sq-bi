from __future__ import annotations

import shutil
import tarfile
from pathlib import Path, PurePosixPath
from typing import IO
from zipfile import ZipFile, is_zipfile

from .pack_loader import load_manifest


MAX_ARCHIVE_FILES = 500
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


def pack_to_tar(pack_dir: str | Path, output: str | Path | IO[bytes]) -> str:
    """Package a validated domain pack directory into a .tar.gz archive."""
    manifest = load_manifest(pack_dir)
    pack_dir = Path(pack_dir)
    with tarfile.open(output, "w:gz") as tar:
        tar.add(pack_dir, arcname=manifest.pack_id)
    return manifest.pack_id


def extract_pack(archive: str | Path | IO[bytes], target_dir: str | Path) -> Path:
    """Safely extract a tar/zip/.sqbipack archive and return its pack root."""
    target = Path(target_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if _is_zip_archive(archive):
        _extract_zip(archive, target)
    else:
        _extract_tar(archive, target)
    manifests = sorted({*target.rglob("pack.yaml"), *target.rglob("manifest.yaml")})
    if len(manifests) != 1:
        raise ValueError("领域包文件必须且只能包含一个 pack.yaml 或 manifest.yaml。")
    pack_root = manifests[0].parent
    load_manifest(pack_root)
    return pack_root


def validate_pack(pack_dir: str | Path) -> list[str]:
    issues: list[str] = []
    path = Path(pack_dir)
    if not path.is_dir():
        return [f"Not a directory: {pack_dir}"]
    try:
        manifest = load_manifest(pack_dir)
    except ValueError as exc:
        return [str(exc)]
    if not manifest.pack_id.strip():
        issues.append("pack_id is required")
    if not manifest.namespace.strip():
        issues.append("namespace is required")
    if not manifest.name.strip():
        issues.append("name is required")
    if not manifest.version.strip():
        issues.append("version is required")
    import re
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", manifest.namespace):
        issues.append(
            f"namespace '{manifest.namespace}' must start with a letter and contain only alphanumeric, underscore, or hyphen"
        )
    return issues


def install_extracted_pack(pack_root: Path, destination_root: Path) -> Path:
    """Copy a validated pack into versioned persistent storage atomically."""
    manifest = load_manifest(pack_root)
    destination = destination_root / manifest.pack_id / manifest.version
    if destination.exists():
        raise FileExistsError(f"领域包 {manifest.pack_id} v{manifest.version} 已经导入。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(destination.name + ".importing")
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(pack_root, staging)
    staging.replace(destination)
    return destination


def _is_zip_archive(archive: str | Path | IO[bytes]) -> bool:
    if hasattr(archive, "seek"):
        archive.seek(0)
    result = is_zipfile(archive)
    if hasattr(archive, "seek"):
        archive.seek(0)
    return result


def _safe_relative_path(name: str) -> Path:
    normalized = PurePosixPath(name.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"领域包包含不安全路径：{name}")
    parts = [part for part in normalized.parts if part not in ("", ".")]
    if not parts:
        raise ValueError("领域包包含空文件路径。")
    return Path(*parts)


def _extract_tar(archive: str | Path | IO[bytes], target: Path) -> None:
    if hasattr(archive, "seek"):
        archive.seek(0)
    try:
        with tarfile.open(fileobj=archive if hasattr(archive, "read") else None, name=None if hasattr(archive, "read") else str(archive), mode="r:*") as tar:
            members = tar.getmembers()
            if len(members) > MAX_ARCHIVE_FILES:
                raise ValueError("领域包文件数量超过限制。")
            total = sum(member.size for member in members if member.isfile())
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("领域包解压后大小超过限制。")
            for member in members:
                if member.issym() or member.islnk() or member.isdev():
                    raise ValueError("领域包不能包含链接或设备文件。")
                destination = target / _safe_relative_path(member.name)
                destination.resolve().relative_to(target)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise ValueError(f"无法读取领域包文件：{member.name}")
                with source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except tarfile.TarError as exc:
        raise ValueError("不支持的领域包压缩格式。") from exc


def _extract_zip(archive: str | Path | IO[bytes], target: Path) -> None:
    if hasattr(archive, "seek"):
        archive.seek(0)
    with ZipFile(archive) as zipped:
        members = zipped.infolist()
        if len(members) > MAX_ARCHIVE_FILES:
            raise ValueError("领域包文件数量超过限制。")
        if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("领域包解压后大小超过限制。")
        for member in members:
            unix_mode = member.external_attr >> 16
            if unix_mode and (unix_mode & 0o170000) == 0o120000:
                raise ValueError("领域包不能包含符号链接。")
            destination = target / _safe_relative_path(member.filename)
            destination.resolve().relative_to(target)
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(member) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
