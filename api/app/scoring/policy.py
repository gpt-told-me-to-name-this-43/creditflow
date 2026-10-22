from decimal import Decimal
from typing import ClassVar


class DecisionPolicy:
    STOP_FACTORS: ClassVar[frozenset[str]] = frozenset(
        {
            "COMPANY_INACTIVE",
            "APPLICANT_NOT_AUTHORIZED",
            "BANKRUPTCY_PROCEEDING",
            "ACCOUNT_BLOCKED_BY_FNS",
            "ACCOUNT_HISTORY_INSUFFICIENT",
        }
    )

    def evaluate(
        self,
        blocking_codes: list[str],
        bki_status: str,
        dscr_raw: Decimal,
        limit_rub: Decimal | None,
        score: int,
    ) -> dict:
        rule_trace = []
        suggested_action = None

        is_blocked = len(blocking_codes) > 0
        rule_trace.append(
            {
                "rule": "R1",
                "matched": is_blocked,
                "detail": blocking_codes if is_blocked else None,
            }
        )
        if is_blocked:
            suggested_action = "BLOCKED_BY_RULE"

        is_serious = bki_status == "SERIOUS"
        rule_trace.append({"rule": "R2", "matched": is_serious, "detail": None})
        if not suggested_action and is_serious:
            suggested_action = "MANUAL_REVIEW"

        is_counter = dscr_raw < Decimal("1.25") and limit_rub is not None
        rule_trace.append({"rule": "R3", "matched": is_counter, "detail": None})
        if not suggested_action and is_counter:
            suggested_action = "COUNTER_OFFER_CANDIDATE"

        is_eligible = dscr_raw >= Decimal("1.25") and score >= 80
        rule_trace.append({"rule": "R4", "matched": is_eligible, "detail": None})
        if not suggested_action and is_eligible:
            suggested_action = "ELIGIBLE_FOR_MANAGER_REVIEW"

        rule_trace.append(
            {
                "rule": "R5",
                "matched": suggested_action is None,
                "detail": None,
            }
        )
        if not suggested_action:
            suggested_action = "MANUAL_REVIEW"

        return {
            "suggested_action": suggested_action,
            "rule_trace": rule_trace,
            "allowed_actions": self._get_allowed_actions(blocking_codes, limit_rub),
        }

    def _get_allowed_actions(
        self,
        blocking_codes: list[str],
        limit_rub: Decimal | None,
    ) -> list[str]:
        actions = ["REJECT"]
        if not blocking_codes:
            actions.extend(["APPROVE", "REQUEST_INFO"])
            if limit_rub is not None:
                actions.append("COUNTER_OFFER")
        return actions
