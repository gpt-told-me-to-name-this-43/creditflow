"""Контракт ExtSimClient ↔ ext-sim: DTO клиента принимают примеры из docs/openapi-ext-sim.json.

Если ext-sim меняет схему, `make openapi` обновляет пример, и этот тест падает,
пока DTO клиента не приведены в соответствие.
"""

import json
from typing import Any

import pytest
from pydantic import BaseModel

from app.extsim_client import dto

from .conftest import EXT_SIM_OPENAPI, ext_sim_examples

RESPONSE_DTOS: dict[str, type[BaseModel]] = {
    "EgrulCompany": dto.EgrulCompany,
    "EgripEntrepreneur": dto.EgripEntrepreneur,
    "FnsCompanyStatus": dto.FnsCompanyStatus,
    "BkiReport": dto.BkiReport,
    "BankStatement": dto.BankStatement,
}
NESTED_DTOS: dict[str, type[BaseModel]] = {
    "Director": dto.Director,
    "BkiObligation": dto.BkiObligation,
    "Counterparty": dto.Counterparty,
    "Transaction": dto.Transaction,
}


def schemas() -> dict[str, Any]:
    spec = json.loads(EXT_SIM_OPENAPI.read_text(encoding="utf-8"))
    result: dict[str, Any] = spec["components"]["schemas"]
    return result


def test_every_response_schema_has_example() -> None:
    assert set(ext_sim_examples()) == set(RESPONSE_DTOS)


@pytest.mark.parametrize("name", sorted(RESPONSE_DTOS))
def test_dto_accepts_openapi_example(name: str) -> None:
    RESPONSE_DTOS[name].model_validate_json(json.dumps(ext_sim_examples()[name]))


@pytest.mark.parametrize("name", sorted(RESPONSE_DTOS | NESTED_DTOS))
def test_dto_fields_match_schema(name: str) -> None:
    model = (RESPONSE_DTOS | NESTED_DTOS)[name]
    schema = schemas()[name]
    aliases = {field.alias or key for key, field in model.model_fields.items()}
    assert aliases == set(schema["properties"])


@pytest.mark.parametrize(
    ("schema_name", "enum"),
    [("RegistryStatus", dto.RegistryStatus), ("BkiSummaryStatus", dto.BkiSummaryStatus)],
)
def test_enums_match_schema(schema_name: str, enum: type[Any]) -> None:
    assert set(schemas()[schema_name]["enum"]) == {member.value for member in enum}
