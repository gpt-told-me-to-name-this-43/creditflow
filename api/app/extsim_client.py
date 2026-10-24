"""Клиент для ext-sim (issue #7)."""

import httpx
from dataclasses import dataclass

from app.ext_sim.schemas import (
    EgrulCompany,
    EgripEntrepreneur,
    FnsCompanyStatus,
    BkiReport,
    BankStatement,
)


class ExtSimError(Exception):
    pass


class ExtSimUnavailableError(ExtSimError):
    """Симулятор недоступен (503, 504, 500)."""
    pass


@dataclass(frozen=True)
class ExtSimDataDTO:
    registry: EgrulCompany | EgripEntrepreneur
    fns: FnsCompanyStatus
    bki: BkiReport
    statement: BankStatement


class ExtSimClient:
    def __init__(self, base_url: str, timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch_all_for_submit(self, inn: str, consent_id: str) -> ExtSimDataDTO:
        try:
            resp_egrul = await self._client.get(f"{self.base_url}/egrul/v1/companies/{inn}")
            if resp_egrul.status_code == 404:
                resp_egrip = await self._client.get(
                    f"{self.base_url}/egrip/v1/entrepreneurs/{inn}"
                )
                resp_egrip.raise_for_status()
                registry = EgripEntrepreneur.model_validate(resp_egrip.json())
            else:
                resp_egrul.raise_for_status()
                registry = EgrulCompany.model_validate(resp_egrul.json())

            resp_fns = await self._client.get(f"{self.base_url}/fns/v1/companies/{inn}")
            resp_fns.raise_for_status()
            fns = FnsCompanyStatus.model_validate(resp_fns.json())

            resp_bki = await self._client.post(
                f"{self.base_url}/bki/v1/reports",
                json={"inn": inn, "consent_id": consent_id},
            )
            resp_bki.raise_for_status()
            bki = BkiReport.model_validate(resp_bki.json())

            resp_bank = await self._client.get(
                f"{self.base_url}/bank/v1/statements",
                params={"inn": inn, "from": "2025-10-01", "to": "2026-10-01"},
            )
            resp_bank.raise_for_status()
            statement = BankStatement.model_validate(resp_bank.json())

            return ExtSimDataDTO(registry=registry, fns=fns, bki=bki, statement=statement)

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (500, 503, 504):
                raise ExtSimUnavailableError(f"Simulator failed with {exc.response.status_code}")
            raise ExtSimError(f"HTTP error: {exc.response.status_code}")
        except httpx.TimeoutException:
            raise ExtSimUnavailableError("Simulator timeout")
