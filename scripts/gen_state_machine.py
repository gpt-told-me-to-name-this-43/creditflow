"""Рендер docs/state-machine.md из таблицы переходов FSM (app/applications/fsm.py).

Запуск из каталога `api`: `uv run python ../scripts/gen_state_machine.py [--check]`.
С `--check` ничего не пишет и падает, если документ устарел (CI и тест).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from app.applications.fsm import TRANSITIONS

OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "state-machine.md"


def render() -> str:
    rows = [
        "# Статусы заявки (FSM)",
        "",
        "<!-- Генерируется `make state-machine` из app/applications/fsm.py. "
        "Не редактировать вручную. -->",
        "",
        "Статус меняется только через `transition()`. Каждый переход пишет событие в "
        "`application_events` и увеличивает `revision`. Любой переход не из таблицы — "
        "`409 INVALID_STATUS_TRANSITION`.",
        "",
        "| Из | Действие | Кто | В |",
        "| --- | --- | --- | --- |",
    ]
    for t in TRANSITIONS:
        source = f"`{t.source.value}`" if t.source else "—"
        rows.append(f"| {source} | `{t.action.value}` | {t.actor.value} | `{t.target.value}` |")
    rows += ["", "```mermaid", "stateDiagram-v2"]
    for t in TRANSITIONS:
        source = t.source.value if t.source else "[*]"
        rows.append(f"    {source} --> {t.target.value}: {t.actor.value} {t.action.value}")
    finals = sorted({t.target for t in TRANSITIONS} - {t.source for t in TRANSITIONS if t.source})
    rows += [f"    {s.value} --> [*]" for s in finals]
    rows += ["```", ""]
    return "\n".join(rows)


def main() -> None:
    value = render()
    if "--check" in sys.argv:
        if OUTPUT.read_text(encoding="utf-8") != value:
            sys.exit("docs/state-machine.md устарел: выполните make state-machine")
    else:
        OUTPUT.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    main()
