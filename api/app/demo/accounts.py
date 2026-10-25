"""Демо-учётки: «логин → компания → что попробовать → ожидаемый результат» (issue #7).

Один источник для `GET /auth/demo-accounts` и таблицы в docs/demo-data.md
(`make demo-accounts`; тест сверяет документ с этим модулем).
Состояние «после `make demo-reset`» создаёт scripts/seed_demo.py.
"""

from dataclasses import dataclass

from app.seed import DEMO_USERS


@dataclass(frozen=True)
class DemoScenario:
    login: str
    company: str
    try_: str
    expected: str

    @property
    def text(self) -> str:
        return f"{self.company}. {self.try_} → {self.expected}"


SCENARIOS = (
    DemoScenario(
        "director.techservice@creditflow.demo",
        "C1 · ООО «ТехСервис», 0099010012",
        "Прошлая заявка уже выдана. Подать новую: инвестиционный, 2 000 000 ₽ на 36 мес.",
        "в очереди ELIGIBLE_FOR_MANAGER_REVIEW; APPROVE → код → SIGNED → через 3–5 с ISSUED",
    ),
    DemoScenario(
        "director.bakery@creditflow.demo",
        "C2 · ООО «Пекарня Плюс», 0099020010 (не привязана)",
        "Привязать ИНН, подать инвестиционный, 3 000 000 ₽ на 36 мес.",
        "COUNTER_OFFER_CANDIDATE, лимит 2 340 000; оффер 2 340 000 / 36 → принять → подписать",
    ),
    DemoScenario(
        "ip.sokolova@creditflow.demo",
        "C3 · ИП Соколова А. В., 009903001040",
        "Ответить на вопрос менеджера по открытой заявке",
        "заявка возвращается в UNDER_REVIEW без пересчёта (MANUAL_REVIEW: БКИ SERIOUS)",
    ),
    DemoScenario(
        "director.newstart@creditflow.demo",
        "C4 · ООО «Новый Старт», 0099040017 (не привязана)",
        "Привязать ИНН, подать инвестиционный, 500 000 ₽ на 24 мес.",
        "BLOCKED_BY_RULE: ACCOUNT_HISTORY_INSUFFICIENT, менеджеру доступен только REJECT",
    ),
    DemoScenario(
        "director.vector@creditflow.demo",
        "C5 · ООО «Вектор», 0099050015",
        "Открыть отклонённую заявку",
        "REJECTED, причина для клиента COMPANY_STATUS (компания в ликвидации)",
    ),
    DemoScenario(
        "director.sklad@creditflow.demo",
        "C6 · ООО «Склад-М», 0099060013",
        "Заявка на рассмотрении; менеджер открывает карточку",
        "BLOCKED_BY_RULE: ACCOUNT_BLOCKED_BY_FNS; APPROVE → 422 ACTION_NOT_ALLOWED",
    ),
    DemoScenario(
        "ip.orlov@creditflow.demo",
        "C7 · ИП Орлов Д. С., 009907001027",
        "Заявка на рассмотрении; менеджер открывает карточку",
        "MANUAL_REVIEW: DSCR 0.86, лимита нет — встречное предложение недоступно",
    ),
    DemoScenario(
        "accountant.bakery@creditflow.demo",
        "Бухгалтер «Пекарни Плюс» (не руководитель)",
        "Привязать ИНН 0099020010",
        "403 APPLICANT_NOT_AUTHORIZED — подавать может только руководитель или ИП",
    ),
    DemoScenario(
        "manager.anna@creditflow.demo",
        "Кредитный менеджер",
        "Очередь, карточки C6/C7, сводка; после ответа C3 — её карточка",
        "очередь и сводка непустые; решения по C6 — только REJECT",
    ),
    DemoScenario(
        "manager.oleg@creditflow.demo",
        "Второй кредитный менеджер",
        "Решение по той же заявке, что и у первого менеджера, во второй вкладке",
        "второй получает 409 REVISION_CONFLICT или INVALID_STATUS_TRANSITION",
    ),
)

assert [s.login for s in SCENARIOS] == [u.email for u in DEMO_USERS]

DOC_START = "<!-- demo-accounts:start -->"
DOC_END = "<!-- demo-accounts:end -->"


def markdown_table() -> str:
    rows = [
        DOC_START,
        "<!-- Генерируется `make demo-accounts` из api/app/demo/accounts.py. -->",
        "",
        "| Логин | Компания | Что попробовать | Ожидаемый результат |",
        "| --- | --- | --- | --- |",
    ]
    rows += [f"| `{s.login}` | {s.company} | {s.try_} | {s.expected} |" for s in SCENARIOS]
    rows += ["", "Пароль всех учёток — `creditflow-demo`.", DOC_END]
    return "\n".join(rows)
