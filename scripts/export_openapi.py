"""Экспорт OpenAPI FastAPI-приложения с детерминированным порядком ключей.

Запуск из каталога сервиса, чтобы импортировался его пакет `app`:

    cd api && uv run python ../scripts/export_openapi.py app.main:app ../docs/openapi.json
"""

import importlib
import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: export_openapi.py <module:attr> <output.json>")
    target, output = sys.argv[1], Path(sys.argv[2])
    sys.path.insert(0, str(Path.cwd()))
    module_name, _, attr = target.partition(":")
    app = getattr(importlib.import_module(module_name), attr)
    spec = app.openapi()
    text = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output.write_text(text, encoding="utf-8")
    print(f"{output}: {len(spec.get('paths', {}))} paths")


if __name__ == "__main__":
    main()
