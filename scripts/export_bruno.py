"""Экспорт Bruno-коллекции docs/api-collection в docs/api-collection.json (issue #7).

Детерминированный JSON для просмотра без Bruno и для ревью: папки, запросы, тела, assert.
`--check` — CI: экспорт совпадает с .bru-файлами.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1] / "docs"
COLLECTION = ROOT / "api-collection"
OUTPUT = ROOT / "api-collection.json"
_BLOCK = re.compile(r"^([a-z:\-]+) \{\n(.*?)^\}", re.M | re.S)


def _pairs(body: str) -> dict[str, str]:
    result = {}
    for line in body.splitlines():
        key, _, value = line.strip().partition(": ")
        if key:
            result[key] = value
    return result


def parse(path: Path) -> dict[str, Any]:
    blocks = {name: body for name, body in _BLOCK.findall(path.read_text(encoding="utf-8"))}
    meta = _pairs(blocks["meta"])
    method = next(m for m in ("get", "post", "patch", "put", "delete") if m in blocks)
    request: dict[str, Any] = {
        "name": meta["name"],
        "seq": int(meta["seq"]),
        "method": method.upper(),
        "url": _pairs(blocks[method])["url"],
    }
    if "auth:bearer" in blocks:
        request["auth"] = _pairs(blocks["auth:bearer"])["token"]
    if "headers" in blocks:
        request["headers"] = _pairs(blocks["headers"])
    if "body:json" in blocks:
        request["body"] = "\n".join(line[2:] for line in blocks["body:json"].splitlines())
    if "assert" in blocks:
        request["assert"] = _pairs(blocks["assert"])
    for script in ("script:pre-request", "script:post-response", "docs"):
        if script in blocks:
            request[script] = "\n".join(line[2:] for line in blocks[script].splitlines())
    return request


def export() -> str:
    folders: list[dict[str, Any]] = []
    dirs = (p for p in COLLECTION.iterdir() if p.is_dir() and p.name != "environments")
    for folder in sorted(dirs):
        meta = _pairs(_BLOCK.findall((folder / "folder.bru").read_text(encoding="utf-8"))[0][1])
        requests = [parse(p) for p in folder.glob("*.bru") if p.name != "folder.bru"]
        requests.sort(key=lambda r: int(r["seq"]))
        folders.append(
            {
                "name": folder.name,
                "seq": int(meta["seq"]),
                "requests": requests,
            }
        )
    env_files = sorted((COLLECTION / "environments").glob("*.bru"))
    environments = {p.stem: p.read_text(encoding="utf-8") for p in env_files}
    data = {
        "name": json.loads((COLLECTION / "bruno.json").read_text(encoding="utf-8"))["name"],
        "run": "make bru (scripts/bru_run.sh): reset clean → токены → bru run --env local",
        "environments": environments,
        "folders": sorted(folders, key=lambda f: int(f["seq"])),
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    value = export()
    if "--check" in sys.argv:
        if OUTPUT.read_text(encoding="utf-8") != value:
            sys.exit("docs/api-collection.json устарел: выполните make bru-export")
    else:
        OUTPUT.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    main()
