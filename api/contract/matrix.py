"""Чтение единственного независимого эталона HTTP-контракта; OpenAPI не импортируется."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

MATRIX_PATH = Path(__file__).with_name("http_matrix.yaml")


class Declaration(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Response(Declaration):
    model: str | None
    codes: list[str] = []
    retry_after: bool | None = None


class Operation(Declaration):
    method: Literal["GET", "POST", "PATCH"]
    path: str
    access: Literal["public", "Bearer", "CLIENT", "MANAGER", "TestResetToken"]
    responses: dict[int, Response]
    condition: str


class Matrix(Declaration):
    design: str
    operations: list[Operation]

    @model_validator(mode="after")
    def _unique(self) -> "Matrix":
        keys = [(op.method, op.path) for op in self.operations]
        if len(keys) != len(set(keys)):
            raise ValueError("Повтор операции в HTTP-матрице")
        return self


def load_matrix() -> Matrix:
    return Matrix.model_validate(yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8")))


def wire_schema(model: str | None) -> dict[str, Any]:
    if model is None:
        return {}
    if model.startswith("list["):
        return {"type": "array", "items": wire_schema(model[5:-1])}
    if model == "OfferPreviewResponse":
        return {
            "oneOf": [wire_schema("CalculatedOfferPreview"), wire_schema("SkippedOfferPreview")],
            "discriminator": {
                "propertyName": "calculation_status",
                "mapping": {
                    "OK": "#/components/schemas/CalculatedOfferPreview",
                    "SKIPPED": "#/components/schemas/SkippedOfferPreview",
                },
            },
        }
    return {"$ref": f"#/components/schemas/{model}"}
