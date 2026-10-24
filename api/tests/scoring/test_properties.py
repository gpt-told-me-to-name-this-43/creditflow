"""Property-тесты ядра (issue #6, «Property (hypothesis)»).

Golden- и M-тесты проверяют конкретные точки; здесь — инварианты на всём диапазоне входов.
Деньги генерируются целыми рублями и переводятся в Decimal через str — float в ядро не попадает.
"""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.schemas.enums import BkiSummaryStatus as Bki
from app.schemas.enums import ManagerAction, StopFactor
from app.scoring.policy import allowed_actions
from app.scoring.risk import TARGET_DSCR, Product, assess, limit_for_term
from tests.scoring._data import INVESTMENT, WORKING_CAPITAL, features

products = st.sampled_from([INVESTMENT, WORKING_CAPITAL])
cfads = st.integers(min_value=1, max_value=3_000_000)
debt = st.integers(min_value=0, max_value=500_000)
bki = st.sampled_from(list(Bki))


@st.composite
def amount_term(draw: st.DrawFn, product: Product) -> tuple[Decimal, int]:
    amount = draw(st.integers(int(product.min_amount_rub), int(product.max_amount_rub)))
    term = draw(st.integers(product.min_term_months, product.max_term_months))
    return Decimal(amount), term


@given(product=products, data=st.data(), c=cfads, d=debt, extra=st.integers(1, 1_000_000))
def test_bigger_amount_never_raises_dscr(
    product: Product, data: st.DataObject, c: int, d: int, extra: int
) -> None:
    amount, term = data.draw(amount_term(product))
    bigger = min(amount + extra, product.max_amount_rub)
    f = features(str(c), str(d))
    assert (
        assess(product, bigger, term, f, Bki.CLEAN).dscr
        <= assess(product, amount, term, f, Bki.CLEAN).dscr
    )


@given(product=products, data=st.data(), c=cfads, d=debt, extra=cfads, b=bki)
def test_more_cfads_never_lowers_score(
    product: Product, data: st.DataObject, c: int, d: int, extra: int, b: Bki
) -> None:
    amount, term = data.draw(amount_term(product))
    low = assess(product, amount, term, features(str(c), str(d)), b)
    high = assess(product, amount, term, features(str(c + extra), str(d)), b)
    assert high.score >= low.score


@given(product=products, data=st.data(), c=cfads, d=debt)
def test_limit_is_rounded_bounded_and_affordable(
    product: Product, data: st.DataObject, c: int, d: int
) -> None:
    _, term = data.draw(amount_term(product))
    limit = limit_for_term(product, Decimal(c), Decimal(d), term)
    if limit is None:
        return
    assert limit % 10_000 == 0
    assert product.min_amount_rub <= limit <= product.max_amount_rub
    # DSCR на самом лимите не ниже целевого: округление вниз не может его нарушить
    assert assess(product, limit, term, features(str(c), str(d)), Bki.CLEAN).dscr >= TARGET_DSCR


@given(
    codes=st.lists(st.sampled_from(list(StopFactor)), unique=True, max_size=3),
    limit=st.none() | st.integers(1, 500).map(lambda n: Decimal(n * 10_000)),
)
def test_reject_always_allowed_and_alone_on_stop_factor(
    codes: list[StopFactor], limit: Decimal | None
) -> None:
    actions = allowed_actions(codes, limit)
    assert ManagerAction.REJECT in actions
    if codes:
        assert actions == (ManagerAction.REJECT,)
