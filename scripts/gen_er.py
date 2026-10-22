"""Генерация docs/er.md (mermaid erDiagram) из метаданных SQLAlchemy.

Запуск из каталога `api`:

    uv run python ../scripts/gen_er.py app.core.db:Base ../docs/er.md

Модели должны быть импортированы модулем, где объявлен `Base`, иначе их
таблицы не попадут в `Base.metadata`.
"""

import importlib
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import Column, MetaData, UniqueConstraint

HEADER = """# ER-диаграмма

<!-- Генерируется `make er` (scripts/gen_er.py). Не редактировать вручную. -->

Описание таблиц и инвариантов — design.md §3.7, «Модель данных».
"""


def _type_name(column: Column[Any]) -> str:
    raw = str(column.type).lower()
    return re.sub(r"[^a-z0-9]+", "_", raw).strip("_") or "unknown"


def render(metadata: MetaData) -> str:
    tables = sorted(metadata.tables.values(), key=lambda t: t.name)
    if not tables:
        return HEADER + "\nТаблиц пока нет.\n"
    lines = ["```mermaid", "erDiagram"]
    relations: list[str] = []
    for table in tables:
        lines.append(f"    {table.name} {{")
        unique = {
            c.name
            for con in table.constraints
            if isinstance(con, UniqueConstraint) and len(con.columns) == 1
            for c in con.columns
        }
        for column in table.columns:
            keys = [
                k
                for k, on in (
                    ("PK", column.primary_key),
                    ("FK", bool(column.foreign_keys)),
                    ("UK", column.name in unique or column.unique),
                )
                if on
            ]
            suffix = f" {','.join(keys)}" if keys else ""
            lines.append(f"        {_type_name(column)} {column.name}{suffix}")
            for fk in sorted(column.foreign_keys, key=lambda f: f.target_fullname):
                parent = fk.column.table.name
                cardinality = "|o" if column.nullable else "||"
                relations.append(f'    {table.name} }}o--{cardinality} {parent} : "{column.name}"')
        lines.append("    }")
    lines.extend(sorted(relations))
    lines.append("```")
    return HEADER + "\n" + "\n".join(lines) + "\n"


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: gen_er.py <module:Base> <output.md>")
    target, output = sys.argv[1], Path(sys.argv[2])
    sys.path.insert(0, str(Path.cwd()))
    module_name, _, attr = target.partition(":")
    base = getattr(importlib.import_module(module_name), attr)
    output.write_text(render(base.metadata), encoding="utf-8")
    print(f"{output}: {len(base.metadata.tables)} tables")


if __name__ == "__main__":
    main()
