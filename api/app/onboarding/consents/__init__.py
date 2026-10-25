"""Тексты согласий (#5): `<prefix>-v<N>.md`, версия = имя файла без `.md`.

`pd-*` — `PD_PROCESSING` (при привязке компании), `bki-*` — `BKI_REQUEST` (при Submit, #7).
Действующая версия типа — файл с наибольшим `N`; прежние файлы остаются для истории.
"""

import re
from functools import cache
from pathlib import Path

from app.schemas.auth import ConsentText, ConsentType

CONSENTS_DIR = Path(__file__).parent
_NAME = re.compile(r"^(pd|bki)-v(\d+)$")
_TYPES = {"pd": ConsentType.PD_PROCESSING, "bki": ConsentType.BKI_REQUEST}


@cache
def current_consents() -> dict[ConsentType, ConsentText]:
    """Действующий текст каждого типа. Файл с неожиданным именем или отсутствие типа
    роняют загрузку, а не выдачу согласия."""
    best: dict[ConsentType, tuple[int, Path]] = {}
    for path in sorted(CONSENTS_DIR.glob("*.md")):
        match = _NAME.fullmatch(path.stem)
        if match is None:
            raise ValueError(f"{path.name}: имя текста согласия — <pd|bki>-v<N>.md")
        kind, number = _TYPES[match[1]], int(match[2])
        if kind not in best or number > best[kind][0]:
            best[kind] = (number, path)
    missing = set(ConsentType) - best.keys()
    if missing:
        raise ValueError(f"нет текста согласия: {', '.join(sorted(missing))}")
    return {
        kind: ConsentText(type=kind, version=path.stem, text=path.read_text("utf-8").strip())
        for kind, (_, path) in best.items()
    }


def current_version(kind: ConsentType) -> str:
    return current_consents()[kind].version
