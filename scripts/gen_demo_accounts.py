"""Таблица демо-учёток в docs/demo-data.md из api/app/demo/accounts.py (issue #7).

Запуск из каталога `api`: `uv run python ../scripts/gen_demo_accounts.py [--check]`.
Тот же текст отдаёт GET /auth/demo-accounts (поле scenario).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from app.demo.accounts import DOC_END, DOC_START, markdown_table

DOC = Path(__file__).resolve().parents[1] / "docs" / "demo-data.md"
SECTION = "## 0. Демо-учётки: что попробовать"


def render(current: str) -> str:
    table = markdown_table()
    if DOC_START in current:
        head, rest = current.split(DOC_START, 1)
        return head + table + rest.split(DOC_END, 1)[1]
    # первый запуск: раздел — сразу после заголовка документа
    title, body = current.split("\n", 1)
    return f"{title}\n\n{SECTION}\n\nСостояние после `make demo-reset`.\n\n{table}\n{body}"


def main() -> None:
    current = DOC.read_text(encoding="utf-8")
    value = render(current)
    if "--check" in sys.argv:
        if value != current:
            sys.exit("docs/demo-data.md устарел: выполните make demo-accounts")
    else:
        DOC.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    main()
