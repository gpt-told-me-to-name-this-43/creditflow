from pydantic import BaseModel
from .common import MoneyStr

class ClientApplicationView(BaseModel):
    id: str
    status: str
    requested_amount_rub: MoneyStr
    term_months: int
    product_id: str
    
    # ВНИМАНИЕ: НЕТ полей score, dscr, limit_rub, risk_level, ai_report, manager_comment
    # Они не отфильтрованы через exclude, их здесь просто не существует в классе.
    # Не ещкере!!!