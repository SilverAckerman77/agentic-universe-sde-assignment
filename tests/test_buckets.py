
from agentic_assignment_reporting.reports import _lead_bucket


def test_yet_to_reach_out():
    assert _lead_bucket([]) == "yet_to_reach_out"


def test_completed():
    calls = [
        {"is_terminal": True, "telephony_failed": False},
    ]
    assert _lead_bucket(calls) == "completed"


def test_all_calls_telephony_failed():
    calls = [
        {"is_terminal": False, "telephony_failed": True},
        {"is_terminal": False, "telephony_failed": True},
    ]
    assert _lead_bucket(calls) == "in_progress_telephony_failed"


def test_in_progress_dialed():
    calls = [
        {"is_terminal": False, "telephony_failed": False},
        {"is_terminal": False, "telephony_failed": True},
    ]
    assert _lead_bucket(calls) == "in_progress_dialed"


def test_completed_has_priority_over_telephony_failure():
    calls = [
        {"is_terminal": True, "telephony_failed": True},
        {"is_terminal": False, "telephony_failed": True},
    ]
    assert _lead_bucket(calls) == "completed"
