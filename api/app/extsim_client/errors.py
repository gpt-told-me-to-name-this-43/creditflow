"""Ошибки ExtSimClient. Маппинг в HTTP-ответы API — в #5 и #6."""


class ExtSimError(Exception):
    """Базовая ошибка обращения к ext-sim."""


class ProviderUnavailableError(ExtSimError):
    """Источник не ответил корректно → `503 PROVIDER_UNAVAILABLE`.

    Таймаут, ошибка соединения и 5xx — после одного повтора; прочие 4xx и
    ответ, не прошедший разбор, — сразу.
    """

    def __init__(self, source: str, reason: str, status_code: int | None = None) -> None:
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason
        self.status_code = status_code


class CompanyNotInRegistryError(ExtSimError):
    """ЕГРЮЛ/ЕГРИП ответил 404 → `422 COMPANY_NOT_IN_REGISTRY`."""

    def __init__(self, inn: str) -> None:
        super().__init__("компании нет в реестре")
        self.inn = inn
