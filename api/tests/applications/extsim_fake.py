"""ext-sim в процессе для интеграционных тестов: закоммиченные фикстуры + управляемые сбои.

Повторяет контракт docs/openapi-ext-sim.json для того, что использует Submit. `fail`
задаёт источники, которые отвечают таймаутом (как `X-Sim-Fail`); `fail_mode` из
`meta.json` (T1: `bki_timeout`) соблюдается так же, как в настоящем ext-sim.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from tests.conftest import REPO_ROOT

FIXTURES: Path = REPO_ROOT / "ext-sim" / "fixtures"


def _read(inn: str, name: str) -> dict[str, Any] | None:
    path = FIXTURES / inn / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


@dataclass
class FakeExtSim:
    fail: set[str] = field(default_factory=set)  # egrul | egrip | fns | bki | bank
    calls: list[tuple[str, str]] = field(default_factory=list)  # (источник, consent_id/inn)
    # вызывается перед ответом выписки: «пока шли внешние вызовы, заявка изменилась»
    on_statement: Callable[[], Awaitable[None]] | None = None

    def _maybe_fail(self, source: str, inn: str, request: httpx.Request) -> None:
        meta = _read(inn, "meta") or {}
        if source in self.fail or meta.get("fail_mode") == f"{source}_timeout":
            raise httpx.ReadTimeout("ext-sim timeout", request=request)

    async def handler(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")
        source = parts[0]
        if source == "health":  # /health api проверяет ext-sim (design §3.7)
            return httpx.Response(200, json={"status": "ok"})
        if source in {"egrul", "egrip", "fns"}:
            inn = parts[-1]
            self.calls.append((source, inn))
            self._maybe_fail(source, inn, request)
            data = _read(inn, {"egrul": "egrul", "egrip": "egrip", "fns": "fns"}[source])
            return httpx.Response(200, json=data) if data else _not_found()
        if source == "bki":
            body = json.loads(request.content)
            self.calls.append(("bki", body["consent_id"]))
            self._maybe_fail("bki", body["inn"], request)
            data = _read(body["inn"], "bki")
            if data is None:
                return _not_found()
            return httpx.Response(200, json={"report_id": f"r-{body['consent_id']}", **data})
        if source == "bank":
            inn = request.url.params["inn"]
            self.calls.append(("bank", inn))
            self._maybe_fail("bank", inn, request)
            data = _read(inn, "statement")
            if self.on_statement is not None:
                await self.on_statement()
            if data is None:
                return _not_found()
            start = date.fromisoformat(request.url.params["from"])
            end = date.fromisoformat(request.url.params["to"])
            txs = [
                t
                for t in data["transactions"]
                if start <= date.fromisoformat(t["booked_at"]) <= end
            ]
            return httpx.Response(
                200,
                json={
                    "inn": inn,
                    "account_masked": data["account_masked"],
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                    "transactions": txs,
                },
            )
        return _not_found()

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def _not_found() -> httpx.Response:
    return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "Нет данных"}})
