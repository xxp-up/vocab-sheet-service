from __future__ import annotations

import sys
from pathlib import Path


def is_frozen_bundle() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_project_root() -> Path:
    if is_frozen_bundle():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_resource_root() -> Path:
    if is_frozen_bundle():
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            return Path(bundle_root).resolve()
    return get_project_root()


def project_path(*parts: str) -> Path:
    return get_project_root().joinpath(*parts)


def resource_path(*parts: str) -> Path:
    return get_resource_root().joinpath(*parts)
