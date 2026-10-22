from pydantic import BaseModel
from .common import MoneyStr

class ManagerApplicationView(BaseModel):
    id: str
    status: str
    requested_amount_rub: MoneyStr
    term_months: int
    
    score: int
    dscr: MoneyStr
    calculated_limit_rub: MoneyStr | None
    risk_level: str
    suggested_action: str
    rule_trace: list[dict]