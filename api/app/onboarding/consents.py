"""Тексты и актуальные версии согласий (design.md §3.3, §4 «Согласия»)."""

from app.schemas.auth import ConsentText, ConsentType

PD_VERSION = "pd-v1"
BKI_VERSION = "bki-v1"

TEXTS = (
    ConsentText(
        type=ConsentType.PD_PROCESSING,
        version=PD_VERSION,
        text="Согласен на обработку персональных данных для рассмотрения заявки (демо).",
    ),
    ConsentText(
        type=ConsentType.BKI_REQUEST,
        version=BKI_VERSION,
        text="Согласен на запрос кредитного отчёта в БКИ для рассмотрения заявки (демо).",
    ),
)
