"""FSM заявки (issue #7). Все переходы через validate_transition."""

from enum import Enum
from typing import Dict, Set


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COUNTER_OFFER = "COUNTER_OFFER"
    DECLINED = "DECLINED"
    NEED_INFO = "NEED_INFO"
    SIGNED = "SIGNED"
    ISSUED = "ISSUED"


ALLOWED_TRANSITIONS: Dict[ApplicationStatus, Set[ApplicationStatus]] = {
    ApplicationStatus.DRAFT: {ApplicationStatus.UNDER_REVIEW},
    ApplicationStatus.UNDER_REVIEW: {
        ApplicationStatus.APPROVED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.COUNTER_OFFER,
        ApplicationStatus.NEED_INFO,
    },
    ApplicationStatus.NEED_INFO: {ApplicationStatus.UNDER_REVIEW},
    ApplicationStatus.COUNTER_OFFER: {ApplicationStatus.APPROVED, ApplicationStatus.DECLINED},
    ApplicationStatus.APPROVED: {ApplicationStatus.SIGNED},
    ApplicationStatus.SIGNED: {ApplicationStatus.ISSUED},
    ApplicationStatus.REJECTED: set(),
    ApplicationStatus.DECLINED: set(),
    ApplicationStatus.ISSUED: set(),
}


class FSMError(Exception):
    def __init__(self, current: str, target: str):
        super().__init__(f"INVALID_STATUS_TRANSITION: {current} -> {target}")


def validate_transition(current: ApplicationStatus, target: ApplicationStatus):
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise FSMError(current.value, target.value)