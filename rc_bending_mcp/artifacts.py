from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def resolve_output_dir(tool_name: str, output_dir: str | Path | None = None) -> Path:
    if output_dir is not None:
        path = Path(output_dir)
    else:
        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        path = BASE_DIR / "output" / "mcp" / f"{timestamp}-{tool_name}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json_artifact(path: Path, payload: object, *, label: str, kind: str = "json") -> dict[str, str]:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return build_artifact(label=label, path=path, kind=kind)


def write_bytes_artifact(path: Path, payload: bytes, *, label: str, kind: str) -> dict[str, str]:
    path.write_bytes(payload)
    return build_artifact(label=label, path=path, kind=kind)


def write_text_artifact(path: Path, payload: str, *, label: str, kind: str = "text") -> dict[str, str]:
    path.write_text(payload, encoding="utf-8")
    return build_artifact(label=label, path=path, kind=kind)


def build_artifact(*, label: str, path: Path, kind: str) -> dict[str, str]:
    return {
        "label": label,
        "path": str(path),
        "kind": kind,
    }
