"""Рендер HTTP-матрицы исключительно из вручную поддерживаемого YAML (без OpenAPI)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from contract.matrix import load_matrix


def render() -> str:
    matrix = load_matrix()
    rows = [
        "# HTTP-матрица API v1 — Design " + matrix.design,
        "",
        "Генерируется `make api-matrix` из `api/contract/http_matrix.yaml`. Не "
        "редактировать вручную.",
        "Ожидания независимы от OpenAPI; `test_http_policy.py` сверяет операции, "
        "статусы, схемы, коды и security.",
        "Все маршруты контракта, кроме health, — стабы local/test; production "
        "предоставляет только health.",
        "`/_test/reset` дополнительно требует TEST_RESET_ENABLED и отдельный токен; "
        "не входит в экспорт по умолчанию.",
        "500 INTERNAL_ERROR / 503 SERVICE_UNAVAILABLE — общая инфраструктура, не вызов ext-sim.",
        "",
        "| Метод | Путь | Доступ | Статус | Модель | ErrorCode |",
        "|---|---|---|---|---|---|",
    ]
    for op in matrix.operations:
        for status, response in op.responses.items():
            codes = ", ".join(response.codes) or "—"
            rows.append(
                f"| {op.method} | `{op.path}` | {op.access} | {status} "
                f"| {response.model or 'без тела'} | {codes} |"
            )
    rows += [
        "",
        "Условия ошибок и формат details: [api.md](api.md).",
        "GET /company и /applications* имеют 409 COMPANY_NOT_BOUND независимо от revision.",
        "409 offer-preview означает статус вне UNDER_REVIEW; бизнес-нарушения "
        "возвращаются в 200 valid=false.",
        "LLM возвращает UNAVAILABLE/FALLBACK без PROVIDER_UNAVAILABLE.",
        "",
    ]
    return "\n".join(rows)


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "docs/api-matrix.md"
    value = render()
    if "--check" in sys.argv:
        if output.read_text(encoding="utf-8") != value:
            sys.exit("docs/api-matrix.md устарел: выполните make api-matrix")
    else:
        output.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    main()
