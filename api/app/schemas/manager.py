from pydantic import BaseModel
from .common import MoneyStr, DscrStr
from .enums import ApplicationStatus, SuggestedAction, RiskLevel, ManagerAction

class ManagerApplicationView(BaseModel):
    id: str
    status: ApplicationStatus
    requested_amount_rub: MoneyStr
    term_months: int
    score: int
    dscr: DscrStr
    calculated_limit_rub: MoneyStr | None
    risk_level: RiskLevel
    suggested_action: SuggestedAction
    rule_trace: list[dict]
    allowed_actions: list[ManagerAction]