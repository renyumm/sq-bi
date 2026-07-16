from __future__ import annotations

from pathlib import Path


def load_skill_bundle(skill_dir: Path) -> str:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        raise FileNotFoundError(f"Skill file not found: {skill_file}")

    parts = [skill_file.read_text(encoding="utf-8")]
    references_dir = skill_dir / "references"
    if references_dir.exists():
        for path in sorted(references_dir.glob("*.md")):
            parts.append(f"\n\n# Reference: {path.name}\n\n")
            parts.append(path.read_text(encoding="utf-8"))
    return "".join(parts)


def load_demo_business_bundle(repo_root: Path) -> str:
    paths = [
        repo_root / "demo" / "06_智慧问数" / "tms_askdata_skill_draft.md",
        repo_root / "demo" / "06_智慧问数" / "sql_guardrails.md",
        repo_root / "demo" / "docs" / "自由分析目标与实现说明.md",
    ]
    parts: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        parts.append(f"\n\n# Demo Business Skill Context: {path.relative_to(repo_root)}\n\n")
        parts.append(path.read_text(encoding="utf-8-sig"))
    return "".join(parts)
