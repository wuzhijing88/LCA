#!/usr/bin/env python
"""Generate a compact CycloneDX-compatible SBOM from the pinned manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT_ROOT / "build_assets" / "third_party" / "manifest.json"


def build_sbom(manifest: dict) -> dict:
    components = []
    for item in manifest.get("components", []):
        hashes = []
        if item.get("sha256"):
            hashes.append({"alg": "SHA-256", "content": item["sha256"]})
        components.append(
            {
                "type": "file",
                "name": item.get("name"),
                "version": item.get("version"),
                "licenses": [{"license": {"id": item.get("license")}}],
                "externalReferences": [
                    {"type": "distribution", "url": item.get("source_url")}
                ],
                "hashes": hashes,
            }
        )
    for dependency in manifest.get("python_dependencies", []):
        properties = [
            {"name": "lca:direct", "value": "true" if dependency.get("direct", True) else "false"},
            {"name": "lca:bundled", "value": "true" if dependency.get("bundled", True) else "false"},
        ]
        required_by = dependency.get("required_by") or []
        if required_by:
            properties.append({"name": "lca:required_by", "value": ",".join(str(x) for x in required_by)})
        components.append(
            {
                "type": "library",
                "name": dependency.get("name"),
                "version": dependency.get("version"),
                "purl": f"pkg:pypi/{dependency.get('name')}@{dependency.get('version')}",
                "scope": "required" if dependency.get("bundled", True) else "excluded",
                "properties": properties,
            }
        )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "LCA"}},
        "components": components,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_sbom(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"sbom={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
