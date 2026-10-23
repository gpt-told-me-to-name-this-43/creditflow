"""ext-sim: детерминированный симулятор ЕГРЮЛ, ЕГРИП, ФНС, БКИ и банковской выписки.

Контракт — design.md §3.4. Ответы берутся из `fixtures/<inn>/`. Сбои моделируются
заголовками `X-Sim-Fail` / `X-Sim-Latency-Ms` и полем `fail_mode` в фикстуре.
"""

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.fixtures import DEFAULT_FIXTURES_DIR, CompanyFixture, FailKind, Source, load_fixtures
from app.schemas import (
    BankStatement,
    BkiReport,
    BkiReportRequest,
    EgripEntrepreneur,
    EgrulCompany,
    ErrorBody,
    ErrorResponse,
    FnsCompanyStatus,
    Health,
)

logger = logging.getLogger("ext_sim")

# Режим `timeout` держит соединение заметно дольше таймаута ExtSimClient (3 с).
TIMEOUT_SLEEP_SECONDS = 30.0
MAX_LATENCY_MS = 30_000
_BKI_NAMESPACE = uuid.UUID("6f1d8a52-3a5e-4f0b-9a0e-6c2f1d1b7e40")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

INN_LLC = r"^\d{10}$"
INN_IE = r"^\d{12}$"
INN_ANY = r"^\d{10}$|^\d{12}$"


class SimError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _error(status_code: int, body: ErrorBody) -> JSONResponse:
    content = ErrorResponse(error=body).model_dump(mode="json", exclude_none=True)
    return JSONResponse(status_code=status_code, content=content)


async def _fail(kind: FailKind) -> None:
    if kind is FailKind.TIMEOUT:
        await asyncio.sleep(TIMEOUT_SLEEP_SECONDS)
        raise SimError(504, "SIMULATED_TIMEOUT", "Смоделированный таймаут")
    if kind is FailKind.HTTP_500:
        raise SimError(500, "SIMULATED_ERROR", "Смоделированная внутренняя ошибка")
    raise SimError(503, "SIMULATED_UNAVAILABLE", "Смоделированная недоступность")


async def sim_controls(
    x_sim_fail: Annotated[
        FailKind | None, Header(description="Смоделировать сбой: timeout, 500 или 503")
    ] = None,
    x_sim_latency_ms: Annotated[
        int | None, Header(ge=0, le=MAX_LATENCY_MS, description="Задержка ответа, мс")
    ] = None,
) -> None:
    if x_sim_latency_ms:
        await asyncio.sleep(x_sim_latency_ms / 1000)
    if x_sim_fail is not None:
        await _fail(x_sim_fail)


_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (404, 422, 500, 503, 504)
}


def create_app(fixtures_dir: Path = DEFAULT_FIXTURES_DIR) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    companies = load_fixtures(fixtures_dir)

    app = FastAPI(
        title="CreditFlow ext-sim",
        summary="Симулятор внешних систем: ЕГРЮЛ, ЕГРИП, ФНС, БКИ, банковская выписка",
        description="Синтетические данные. Контракт — docs/design.md §3.4.",
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID.match(incoming) else str(uuid.uuid4())
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_id=%s method=%s path=%s status=%d duration_ms=%d",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    @app.exception_handler(SimError)
    async def sim_error_handler(_: Request, exc: SimError) -> JSONResponse:
        return _error(exc.status_code, ErrorBody(code=exc.code, message=exc.message))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
        ]
        body = ErrorBody(code="VALIDATION_ERROR", message="Некорректный запрос", details=details)
        return _error(422, body)

    def company(inn: str) -> CompanyFixture:
        found = companies.get(inn)
        if found is None:
            raise not_found()
        return found

    async def apply_fixture_fail(fixture: CompanyFixture, source: Source) -> None:
        if fixture.fail_mode is not None and fixture.fail_mode[0] is source:
            await _fail(fixture.fail_mode[1])

    def not_found() -> SimError:
        return SimError(404, "NOT_FOUND", "Нет данных по ИНН")

    sim = [Depends(sim_controls)]

    @app.get("/health", response_model=Health, tags=["service"])
    async def health() -> Health:
        return Health(status="ok")

    @app.get(
        "/egrul/v1/companies/{inn}",
        response_model=EgrulCompany,
        responses=_ERRORS,
        dependencies=sim,
        tags=["egrul"],
    )
    async def egrul_company(inn: Annotated[str, PathParam(pattern=INN_LLC)]) -> EgrulCompany:
        fixture = company(inn)
        await apply_fixture_fail(fixture, Source.EGRUL)
        if fixture.egrul is None:
            raise not_found()
        return fixture.egrul

    @app.get(
        "/egrip/v1/entrepreneurs/{inn}",
        response_model=EgripEntrepreneur,
        responses=_ERRORS,
        dependencies=sim,
        tags=["egrip"],
    )
    async def egrip_entrepreneur(
        inn: Annotated[str, PathParam(pattern=INN_IE)],
    ) -> EgripEntrepreneur:
        fixture = company(inn)
        await apply_fixture_fail(fixture, Source.EGRIP)
        if fixture.egrip is None:
            raise not_found()
        return fixture.egrip

    @app.get(
        "/fns/v1/companies/{inn}",
        response_model=FnsCompanyStatus,
        responses=_ERRORS,
        dependencies=sim,
        tags=["fns"],
    )
    async def fns_company(inn: Annotated[str, PathParam(pattern=INN_ANY)]) -> FnsCompanyStatus:
        fixture = company(inn)
        await apply_fixture_fail(fixture, Source.FNS)
        if fixture.fns is None:
            raise not_found()
        return fixture.fns

    @app.post(
        "/bki/v1/reports",
        response_model=BkiReport,
        responses={403: {"model": ErrorResponse}, **_ERRORS},
        dependencies=sim,
        tags=["bki"],
    )
    async def bki_report(body: BkiReportRequest) -> BkiReport:
        if not body.consent_id:
            raise SimError(403, "CONSENT_REQUIRED", "Нет согласия на запрос в БКИ")
        fixture = company(body.inn)
        await apply_fixture_fail(fixture, Source.BKI)
        if fixture.bki is None:
            raise not_found()
        report_id = uuid.uuid5(_BKI_NAMESPACE, f"{body.inn}:{body.consent_id}")
        return BkiReport(report_id=str(report_id), **fixture.bki.model_dump())

    @app.get(
        "/bank/v1/statements",
        response_model=BankStatement,
        responses=_ERRORS,
        dependencies=sim,
        tags=["bank"],
    )
    async def bank_statement(
        inn: Annotated[str, Query(pattern=INN_ANY)],
        from_: Annotated[date, Query(alias="from")],
        to: Annotated[date, Query()],
    ) -> BankStatement:
        if from_ > to:
            raise SimError(422, "INVALID_PERIOD", "Начало периода позже конца")
        fixture = company(inn)
        await apply_fixture_fail(fixture, Source.BANK)
        if fixture.statement is None:
            raise not_found()
        transactions = [t for t in fixture.statement.transactions if from_ <= t.booked_at <= to]
        return BankStatement(
            inn=inn,
            account_masked=fixture.statement.account_masked,
            from_=from_,
            to=to,
            transactions=transactions,
        )

    return app


app = create_app()
