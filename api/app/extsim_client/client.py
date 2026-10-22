"""HTTP-клиент ext-sim (design.md §3.2, §4 «Недоступность симуляторов»).

Только транспорт и разбор ответов: таймаут 3 с на попытку, один повтор через
200 мс на таймаут, ошибку соединения и 5xx; на 4xx повтора нет. Бизнес-правил
здесь нет. Тела запросов и ответов не логируются.
"""

import asyncio
import logging
import time
from types import TracebackType
from typing import Any, Self, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from app.extsim_client.dto import (
    BankStatement,
    BkiReport,
    EgripEntrepreneur,
    EgrulCompany,
    FnsCompanyStatus,
    RegistryRecord,
    StatementPeriod,
    SubmitData,
)
from app.extsim_client.errors import CompanyNotInRegistryError, ProviderUnavailableError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 3.0
DEFAULT_RETRY_DELAY_SECONDS = 0.2
HEALTH_TIMEOUT_SECONDS = 2.0

_Model = TypeVar("_Model", bound=BaseModel)


class ExtSimClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        retry_delay: float = DEFAULT_RETRY_DELAY_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._retry_delay = retry_delay
        # ext-sim живёт во внутренней сети compose: системные HTTP(S)_PROXY не применяются.
        self._http = httpx.AsyncClient(
            base_url=base_url, timeout=timeout, transport=transport, trust_env=False
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def health(self) -> bool:
        try:
            async with asyncio.timeout(HEALTH_TIMEOUT_SECONDS):
                response = await self._http.get("/health", timeout=HEALTH_TIMEOUT_SECONDS)
        except (httpx.HTTPError, TimeoutError):
            return False
        return response.status_code == 200

    async def get_egrul_company(self, inn: str, *, request_id: str | None = None) -> EgrulCompany:
        response = await self._request("egrul", "GET", f"/egrul/v1/companies/{inn}", request_id)
        return self._parse("egrul", response, EgrulCompany, registry_inn=inn)

    async def get_egrip_entrepreneur(
        self, inn: str, *, request_id: str | None = None
    ) -> EgripEntrepreneur:
        response = await self._request("egrip", "GET", f"/egrip/v1/entrepreneurs/{inn}", request_id)
        return self._parse("egrip", response, EgripEntrepreneur, registry_inn=inn)

    async def get_registry_record(
        self, inn: str, *, request_id: str | None = None
    ) -> RegistryRecord:
        """ЕГРЮЛ для 10-значного ИНН, ЕГРИП — для 12-значного (design.md §3.3)."""
        if len(inn) == 10:
            return await self.get_egrul_company(inn, request_id=request_id)
        if len(inn) == 12:
            return await self.get_egrip_entrepreneur(inn, request_id=request_id)
        raise ValueError("ИНН должен состоять из 10 или 12 цифр")

    async def get_fns_status(self, inn: str, *, request_id: str | None = None) -> FnsCompanyStatus:
        response = await self._request("fns", "GET", f"/fns/v1/companies/{inn}", request_id)
        return self._parse("fns", response, FnsCompanyStatus)

    async def create_bki_report(
        self, inn: str, consent_id: UUID | str, *, request_id: str | None = None
    ) -> BkiReport:
        if not str(consent_id):
            # design.md §4: адаптер не вызывает БКИ без согласия.
            raise ValueError("запрос в БКИ без consent_id запрещён")
        response = await self._request(
            "bki",
            "POST",
            "/bki/v1/reports",
            request_id,
            json={"inn": inn, "consent_id": str(consent_id)},
        )
        return self._parse("bki", response, BkiReport)

    async def get_statement(
        self, inn: str, period: StatementPeriod, *, request_id: str | None = None
    ) -> BankStatement:
        params = {"inn": inn, "from": period.from_.isoformat(), "to": period.to.isoformat()}
        response = await self._request(
            "bank", "GET", "/bank/v1/statements", request_id, params=params
        )
        return self._parse("bank", response, BankStatement)

    async def fetch_all_for_submit(
        self,
        inn: str,
        consent_id: UUID | str,
        period: StatementPeriod,
        *,
        request_id: str | None = None,
    ) -> SubmitData:
        """Все источники параллельно; любой сбой — исключение, частичных данных нет."""
        tasks = [
            asyncio.ensure_future(self.get_registry_record(inn, request_id=request_id)),
            asyncio.ensure_future(self.get_fns_status(inn, request_id=request_id)),
            asyncio.ensure_future(self.create_bki_report(inn, consent_id, request_id=request_id)),
            asyncio.ensure_future(self.get_statement(inn, period, request_id=request_id)),
        ]
        try:
            registry, fns, bki, statement = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return SubmitData(registry=registry, fns=fns, bki=bki, statement=statement)

    async def _request(
        self,
        source: str,
        method: str,
        url: str,
        request_id: str | None,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = {"X-Request-ID": request_id} if request_id else {}
        reason = ""
        status_code: int | None = None
        for attempt in (1, 2):
            started = time.perf_counter()
            try:
                async with asyncio.timeout(self._timeout):
                    response = await self._http.request(
                        method, url, params=params, json=json, headers=headers
                    )
            except (httpx.TransportError, TimeoutError) as exc:
                reason, status_code = type(exc).__name__, None
            else:
                status_code = response.status_code
                if status_code < 500:
                    self._log(source, attempt, status_code, started, request_id)
                    return response
                reason = f"HTTP {status_code}"
            self._log(source, attempt, status_code, started, request_id, reason)
            if attempt == 1:
                await asyncio.sleep(self._retry_delay)
        raise ProviderUnavailableError(source, reason, status_code)

    @staticmethod
    def _parse(
        source: str,
        response: httpx.Response,
        model: type[_Model],
        *,
        registry_inn: str | None = None,
    ) -> _Model:
        if response.status_code == 404 and registry_inn is not None:
            raise CompanyNotInRegistryError(registry_inn)
        if response.status_code != 200:
            raise ProviderUnavailableError(
                source, f"HTTP {response.status_code}", response.status_code
            )
        try:
            return model.model_validate_json(response.content)
        except ValidationError as exc:
            raise ProviderUnavailableError(source, "ответ не соответствует контракту", 200) from exc

    @staticmethod
    def _log(
        source: str,
        attempt: int,
        status_code: int | None,
        started: float,
        request_id: str | None,
        failure: str | None = None,
    ) -> None:
        logger.log(
            logging.WARNING if failure else logging.INFO,
            "ext_sim source=%s attempt=%d status=%s duration_ms=%d request_id=%s%s",
            source,
            attempt,
            status_code,
            (time.perf_counter() - started) * 1000,
            request_id or "-",
            f" failure={failure}" if failure else "",
        )
