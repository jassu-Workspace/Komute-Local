from backend.core.contracts import MESSAGES, RETRYABLE, Advisory, Reason, ReasonCode as R

EXPECTED_RETRYABLE = {
    R.BARCODE_UNREADABLE, R.BARCODE_NOT_AAMVA, R.FACE_NOT_FOUND_SELFIE,
    R.FACE_NOT_FOUND_LICENCE, R.IMAGE_QUALITY, R.PLATE_NOT_FOUND,
    R.PLATE_UNREADABLE, R.LIVENESS_FAILED,
}


def test_every_code_has_message_and_retry_flag_matches_spec():
    assert len(R) == 16
    assert set(MESSAGES) == set(R)
    assert all(MESSAGES[c].strip() for c in R)
    assert RETRYABLE == EXPECTED_RETRYABLE
    for c in R:
        assert Reason.of(c).retryable == (c in EXPECTED_RETRYABLE)
        assert Reason.of(c).message == MESSAGES[c]


def test_barcode_message_and_advisories():
    assert MESSAGES[R.BARCODE_UNREADABLE] == (
        "The barcode on the back of your licence is not clearly visible. "
        "Please retake the photo of the barcode."
    )
    assert {a.value for a in Advisory} == {
        "COLOUR_MISMATCH", "COLOUR_UNVERIFIED", "LICENCE_FORMAT_UNUSUAL", "LIVENESS_SKIPPED_DEV",
    }
