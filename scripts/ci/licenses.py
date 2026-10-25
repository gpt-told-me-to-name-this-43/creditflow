"""Лицензии runtime-зависимостей (#5): проверка GPL/AGPL и THIRD_PARTY_NOTICES.md.

Вход — CSV из `make licenses`: pip-licenses (`Name,Version,License,URL`) для api и ext-sim,
license-checker (`module name,license,repository`) для web.

    python scripts/ci/licenses.py check docs/licenses/*.csv
    python scripts/ci/licenses.py notices docs/licenses/*.csv > THIRD_PARTY_NOTICES.md

GPL и AGPL любой версии запрещены. LGPL разрешена: она допускает динамическую линковку
(psycopg). Пакет с выбором лицензий (`MIT OR GPL-2.0`) проходит, если среди вариантов
есть разрешённая. Неизвестная лицензия выводится предупреждением.
"""

import csv
import re
import sys
from pathlib import Path

FORBIDDEN = re.compile(r"\bA?GPL|GNU (Affero )?General Public License", re.IGNORECASE)
UNKNOWN = {"", "UNKNOWN", "UNLICENSED", "LICENSE"}
_ALTERNATIVES = re.compile(r"\s+OR\s+|\s*/\s*", re.IGNORECASE)


def read(path: Path) -> list[tuple[str, str, str]]:
    """(пакет, версия, лицензия) из CSV pip-licenses или license-checker."""
    with path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    result = []
    for row in rows:
        if "Name" in row:
            result.append((row["Name"], row["Version"], row["License"]))
        else:
            name, _, version = row["module name"].rpartition("@")
            result.append((name, version, row["license"]))
    return result


def forbidden(license_text: str) -> bool:
    expression = license_text.strip("()")
    alternatives = _ALTERNATIVES.split(expression)
    return all(FORBIDDEN.search(choice) for choice in alternatives)


def check(paths: list[Path]) -> int:
    failures = 0
    for path in paths:
        for name, version, license_text in read(path):
            if forbidden(license_text):
                print(f"::error file={path}::{name}=={version}: {license_text} запрещена")
                failures += 1
            elif license_text.strip().upper() in UNKNOWN:
                print(f"::warning file={path}::{name}=={version}: лицензия не определена")
    if failures:
        return 1
    print(f"licenses: GPL/AGPL нет ({', '.join(p.name for p in paths)})")
    return 0


def notices(paths: list[Path]) -> int:
    print("# Third-party notices\n")
    print("Runtime-зависимости CreditFlow и их лицензии. Генерируется `make licenses`")
    print("из `docs/licenses/*.csv`; вручную не редактируется.")
    for path in paths:
        print(f"\n## {path.stem}\n")
        print("| Пакет | Версия | Лицензия |")
        print("|---|---|---|")
        for name, version, license_text in sorted(read(path), key=lambda r: r[0].lower()):
            print(f"| {name} | {version} | {license_text.replace('|', '/')} |")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in {"check", "notices"}:
        print(__doc__)
        return 2
    paths = [Path(p) for p in argv[1:]]
    return check(paths) if argv[0] == "check" else notices(paths)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
