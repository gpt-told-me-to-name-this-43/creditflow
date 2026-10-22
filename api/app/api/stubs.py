from fastapi import APIRouter, HTTPException
from ..schemas.client import ClientApplicationView
from ..schemas.manager import ManagerApplicationView
from ..schemas.enums import *
from ..schemas.common import MoneyStr, DscrStr

router = APIRouter()

@router.get("/applications/{app_id}", response_model=ClientApplicationView,
            responses={401: {"model": dict}, 403: {"model": dict}, 404: {"model": dict}})
async def get_application(app_id: str):
    return ClientApplicationView(
        id=app_id, status=ApplicationStatus.DRAFT,
        requested_amount_rub=MoneyStr("1000000.00"),
        term_months=12, product_id="investment",
        purpose_code=PurposeCode.EQUIPMENT,
        terms_source=TermsSource.MANUAL,
    )

@router.get("/manager/applications/{app_id}", response_model=ManagerApplicationView,
            responses={401: {"model": dict}, 403: {"model": dict}, 404: {"model": dict}})
async def get_manager_application(app_id: str):
    return ManagerApplicationView(
        id=app_id, status=ApplicationStatus.UNDER_REVIEW,
        requested_amount_rub=MoneyStr("1000000.00"),
        term_months=12, score=80, dscr=DscrStr("1.50"),
        calculated_limit_rub=MoneyStr("1000000.00"),
        risk_level=RiskLevel.LOW,
        suggested_action=SuggestedAction.ELIGIBLE_FOR_MANAGER_REVIEW,
        rule_trace=[], allowed_actions=[ManagerAction.APPROVE, ManagerAction.REJECT],
    )