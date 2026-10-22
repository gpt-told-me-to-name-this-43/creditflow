import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.schemas import BankStatement, BkiReport, EgripEntrepreneur, EgrulCompany, FnsCompanyStatus


class Source(StrEnum):
    EGRUL = "EGRUL"
    EGRIP = "EGRIP"
    FNS = "FNS"
    BKI = "BKI"
    BANK = "BANK"


class FailKind(StrEnum):
    BKI_TIMEOUT = "bki_timeout"
    FNS_TIMEOUT = "fns_timeout"
    EGRUL_TIMEOUT = "egrul_timeout"
    EGRIP_TIMEOUT = "egrip_timeout"


class CompanyFixture:
    def __init__(self, inn: str, data: dict[str, Any]):
        self.inn = inn
        self.data = data

    @property
    def fail_mode(self) -> str | None:
        return self.data.get("fail_mode")

    @property
    def egrul(self) -> EgrulCompany | None:
        raw = self.data.get("egrul")
        return EgrulCompany.model_validate(raw) if raw is not None else None

    @property
    def egrip(self) -> EgripEntrepreneur | None:
        raw = self.data.get("egrip")
        return EgripEntrepreneur.model_validate(raw) if raw is not None else None

    @property
    def fns(self) -> FnsCompanyStatus | None:
        raw = self.data.get("fns")
        return FnsCompanyStatus.model_validate(raw) if raw is not None else None

    @property
    def bki(self) -> BkiReport | None:
        raw = self.data.get("bki")
        return BkiReport.model_validate(raw) if raw is not None else None

    @property
    def statement(self) -> BankStatement | None:
        raw = self.data.get("statement")
        return BankStatement.model_validate(raw) if raw is not None else None


DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def load_fixtures(
    fixtures_dir: Path | None = None,
) -> dict[str, CompanyFixture]:
    target_dir = fixtures_dir or DEFAULT_FIXTURES_DIR

    if not target_dir.exists():
        raise FileNotFoundError(f"Директория с фикстурами не найдена: {target_dir}")

    companies: dict[str, CompanyFixture] = {}

    for directory in target_dir.iterdir():
        if not directory.is_dir():
            continue

        inn = directory.name

        if not (inn.isdigit() and len(inn) in (10, 12)):
            raise ValueError(
                f"{target_dir}: имя каталога должно быть ИНН (10 или 12 цифр), получено: '{inn}'"
            )

        company_data: dict[str, Any] = {"inn": inn}

        for file_path in directory.iterdir():
            is_json = file_path.is_file() and file_path.suffix == ".json"
            if is_json and file_path.name != "statements.json":
                try:
                    key = file_path.stem
                    company_data[key] = json.loads(file_path.read_text(encoding="utf-8"))
                except Exception as e:
                    print(f"Warning: Failed to load {file_path}: {e}")

        companies[inn] = CompanyFixture(inn, company_data)

    return companies
