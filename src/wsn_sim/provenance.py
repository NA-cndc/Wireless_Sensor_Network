import hashlib
import json
from pathlib import Path


def json_digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def source_fingerprint(root: Path, *, extra_paths=()) -> dict:
    paths = [*root.glob("*.py")]
    for folder in ("src", "scripts"):
        paths.extend((root / folder).rglob("*.py"))
    paths.extend(root / name for name in (
        "pyproject.toml", "requirements.txt", "requirements-dev.txt", "configs/plan.json",
        *extra_paths,
    ))
    files = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths) if path.is_file()
    }
    return {"sha256": json_digest(files), "files": files}
