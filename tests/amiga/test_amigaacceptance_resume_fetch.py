"""The resume state fetched from the guest is judged against the receipt's hash in either letter case."""

from __future__ import annotations

import hashlib

from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.test_amigaacceptance_accept import _accept, readings  # noqa: F401
from tests.amiga.test_amigaacceptance_resume import (
    STATE_BYTES,
    STATE_PATH,
    ResumeAcceptGuest,
    _missing,
    _record,
)

clock = measure.clock  # the fixture that replaces the driver's time and sleep


class GuestCaseGuest(ResumeAcceptGuest):
    """A guest whose snapshot receipt carries the hash as `Get-FileHash` prints it, in upper case."""

    tag = None

    def snapshot(self, name, holder):
        receipt = super().snapshot(name, holder)
        receipt.tags["sha256"] = (self.tag if self.tag is not None
                                  else receipt.tags["sha256"].upper())
        return receipt


def test_an_upper_case_receipt_hash_of_the_same_file_writes_the_record(
        tmp_path, clock, readings):  # noqa: F811
    guest = GuestCaseGuest(clock)
    _, result = _accept(tmp_path, clock, guest=guest, guard=_missing(4))
    assert "resume_error" not in result
    record = _record(result)
    assert record["resumable"] is True and result["resumable"] is True
    assert record["machine"]["sha256"] == hashlib.sha256(STATE_BYTES).hexdigest()
    # The guest's own tag is kept as it printed it.
    assert record["machine"]["receipt"]["sha256"] == hashlib.sha256(STATE_BYTES).hexdigest().upper()


def test_an_upper_case_hash_of_another_file_names_both_hashes(
        tmp_path, clock, readings):  # noqa: F811
    guest = GuestCaseGuest(clock)
    guest.tag = hashlib.sha256(b"ASF another machine").hexdigest().upper()
    _, result = _accept(tmp_path, clock, guest=guest, guard=_missing(4))
    error = result["resume_error"]
    assert "differs from the one it wrote" in error
    assert hashlib.sha256(STATE_BYTES).hexdigest() in error
    assert hashlib.sha256(b"ASF another machine").hexdigest() in error
    assert result["resumable"] is False and "resume_record" not in result
    assert not (tmp_path / "recon1" / "resume" / "resume.json").exists()


def test_a_receipt_hash_that_is_not_a_sha256_is_not_fetched(
        tmp_path, clock, readings):  # noqa: F811
    guest = GuestCaseGuest(clock)
    guest.tag = "F64EFFCC"
    _, result = _accept(tmp_path, clock, guest=guest, guard=_missing(4))
    assert "is not a SHA-256" in result["resume_error"]
    assert ("get", STATE_PATH) not in [call[:2] for call in guest.calls]
    assert not (tmp_path / "recon1" / "resume" / "resume.json").exists()
