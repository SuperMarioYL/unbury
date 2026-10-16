"""Version lockstep across every surface the version appears on.

The version lives in four places that must agree: the VERSION file, the
package metadata (pyproject.toml, read through importlib.metadata), the
runtime constant, and the product site's content/implementation versions.
This suite fails the build when a release bumps one surface and misses
another. Everything is an in-process file/metadata read — no binaries.
"""

from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path

import unbury

ROOT = Path(__file__).parent.parent


def _site_meta() -> dict:
    site = json.loads((ROOT / "web" / "site.json").read_text(encoding="utf-8"))
    return site["meta"]


def test_version_surfaces_are_in_lockstep() -> None:
    file_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    package_version = importlib.metadata.version("unbury")

    assert file_version == package_version == unbury.__version__
    assert _site_meta()["content_version"] == f"v{package_version}"
    assert _site_meta()["implementation_version"] == package_version


def test_changelog_documents_the_current_version() -> None:
    package_version = importlib.metadata.version("unbury")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert f"## [{package_version}]" in changelog
