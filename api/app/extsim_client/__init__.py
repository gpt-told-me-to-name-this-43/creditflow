"""ExtSimClient: HTTP-клиент симулятора внешних систем."""

from app.extsim_client.client import ExtSimClient
from app.extsim_client.dto import StatementPeriod, SubmitData
from app.extsim_client.errors import (
    CompanyNotInRegistryError,
    ExtSimError,
    ProviderUnavailableError,
)

__all__ = [
    "CompanyNotInRegistryError",
    "ExtSimClient",
    "ExtSimError",
    "ProviderUnavailableError",
    "StatementPeriod",
    "SubmitData",
]
