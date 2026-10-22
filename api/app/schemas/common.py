from pydantic import BaseModel, Field, field_validator
import re

MONEY_PATTERN = r'^-?\d+\.\d{2}$'

class MoneyStr(str):
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        from pydantic_core import core_schema
        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.str_schema(pattern=MONEY_PATTERN)
        )

    @classmethod
    def _validate(cls, v: str) -> str:
        if not re.match(MONEY_PATTERN, v):
            raise ValueError(f"Money must match {MONEY_PATTERN}")
        return v

class ErrorEnvelope(BaseModel):
    error: dict = Field(..., description="{code: str, message: str, details: dict | None}")