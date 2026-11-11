import json
from datetime import date, datetime, timezone

import numpy as np

import backend.core  # noqa: F401
from backend.core.contracts import MESSAGES, Claimed, ReasonCode
from backend.core.stages.barcode import run_barcode_stage
from tests.fixtures.aamva_factory import FAKE_FIELDS, make_aamva_text, render_card

NOW = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)
CLAIMED = Claimed(
    full_name="Alex Jamie Tester", date_of_birth=date(1990, 3, 15), licence_number="T12345678901234",
    issuing_province="ON", plate_number="ABC123", vehicle_colour="Grey",
)


def test_unreadable_gives_retryable_barcode_unreadable():
    result, record = run_barcode_stage(np.full((500, 800, 3), 200, np.uint8), CLAIMED, NOW, budget_s=3)
    assert record is None and not result.details["readable"]
    [reason] = result.reasons
    assert reason.code == ReasonCode.BARCODE_UNREADABLE and reason.retryable
    assert reason.message == MESSAGES[ReasonCode.BARCODE_UNREADABLE]
    assert "not clearly visible" in reason.message and "retake" in reason.message.lower()


def test_pdf417_not_aamva_gives_barcode_not_aamva():
    result, record = run_barcode_stage(render_card("hello world, not a licence"), CLAIMED, NOW)
    assert record is None
    assert [r.code for r in result.reasons] == [ReasonCode.BARCODE_NOT_AAMVA] and result.reasons[0].retryable


def test_valid_card_passes():
    result, record = run_barcode_stage(render_card(make_aamva_text()), CLAIMED, NOW)
    assert result.reasons == [] and record is not None
    assert result.details["jurisdiction"] == "ON" and result.details["aamva"]
    assert set(result.timings_ms) == {"decode", "parse", "gates"}


def test_failed_gates_listed_in_details():
    card = render_card(make_aamva_text(fields=dict(FAKE_FIELDS, DCA="G2")))
    result, _ = run_barcode_stage(card, CLAIMED, NOW)
    assert result.details["gates_failed"] == ["CLASS_NOT_ALLOWED"]


def test_details_have_no_pii():
    result, _ = run_barcode_stage(render_card(make_aamva_text()), CLAIMED, NOW)
    blob = json.dumps(result.details)
    for secret in ("TESTER", "ALEX", "JAMIE", "19900315", "1990-03-15", FAKE_FIELDS["DAQ"], "1 TEST ST"):
        assert secret not in blob
