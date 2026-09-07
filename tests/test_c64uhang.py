"""`tools/c64uhang.py`'s reproducer generation, without a C64 Ultimate.

The tool's value to an upstream report is that the disk it builds is a correct,
runnable BASIC reproducer and contains nothing copyrighted. So what is tested
here is that the BASIC tokenizes to the exact bytes a real C64 would produce,
that the PRG's line links are right, and that the generated D64 round-trips
through the directory. Nothing here opens a socket.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools import c64uhang  # noqa: E402


def test_the_load_line_tokenizes_to_the_bytes_a_c64_would_make():
    # LOAD is $93; the quoted name and ,8,1 stay literal PETSCII.
    assert c64uhang.tokenize_line('LOAD"DATA",8,1').hex() == \
        "932244415441222c382c31"


def test_a_keyword_inside_a_quoted_string_is_not_tokenized():
    # "GET" and "TO" appear inside the string and must stay literal.
    body = c64uhang.tokenize_line('OPEN2,8,2,"GETODATA"')
    assert b"GETODATA" in body
    assert body[0] == 0x9F                 # OPEN tokenized
    assert body.count(0xA1) == 0           # no GET token
    assert body.count(0xA4) == 0           # no TO token


def test_st_and_then_tokenize_as_the_status_variable_and_the_keyword():
    body = c64uhang.tokenize_line("IF ST=0 THEN 20")
    assert body[0] == 0x8B                 # IF
    assert b"ST=0 " in body                # ST stays a variable
    assert 0xA7 in body                    # THEN tokenized


def test_the_prg_has_the_load_address_and_a_correct_line_link():
    prg = c64uhang.build_basic([(10, 'LOAD"HANGDATA",8,1')])
    assert prg[:2] == bytes([0x01, 0x08])          # loads at $0801
    assert prg[4:6] == bytes([0x0A, 0x00])         # line number 10
    assert prg[6] == 0x93                           # LOAD
    assert prg[-2:] == b"\x00\x00"                  # end of program
    link = prg[2] | (prg[3] << 8)
    # the link points just past this line's record
    assert link == 0x0801 + (len(prg) - 2 - 2)


def test_the_load_disk_round_trips_and_carries_only_generated_files():
    disk = D64.from_bytes(c64uhang.reproducer_disk("load"))
    names = {e.raw_name.rstrip(b"\xa0").decode("latin1")
             for e in disk.directory()}
    assert names == {"HANG", "HANGDATA"}
    hang = disk.read_file("HANG")
    assert hang == c64uhang.build_basic([(10, 'LOAD"HANGDATA",8,1')])
    addr, body = split_load_address(disk.read_file("HANGDATA"))
    assert addr == c64uhang.DATA_ADDR          # loads to free RAM at $C000
    assert len(body) == c64uhang.DATA_SIZE
    assert set(body) == {0}                    # zero-filled, nothing copied


def test_the_get_variant_builds_three_lines_and_round_trips():
    disk = D64.from_bytes(c64uhang.reproducer_disk("get"))
    hang = disk.read_file("HANG")
    # three linked lines, 10/20/30, ending in $00 $00
    assert hang[:2] == bytes([0x01, 0x08])
    assert hang[-2:] == b"\x00\x00"
    assert hang.count(0xA1) == 1               # exactly one GET


def write_log(tmp_path, dd00_values, jiffies):
    import json
    p = tmp_path / "run.jsonl"
    with p.open("w") as f:
        for i, (d, j) in enumerate(zip(dd00_values, jiffies)):
            f.write(json.dumps({"kind": "sample", "t": 1000.0 + 5 * i,
                                "jiffy": j, "dd00": d}) + "\n")
    return p


def test_a_bus_cycling_through_load_states_is_scored_as_loading(tmp_path):
    # The pattern the hung run and the sweep runs both showed.
    p = write_log(tmp_path, [0x27, 0x47, 0x87, 0x07, 0x27, 0x47],
                  [100, 300, 500, 700, 900, 1100])
    ev = c64uhang.loading_evidence(p)
    assert ev["was_loading"]
    assert ev["idle_prompt_samples"] == 0


def test_a_machine_at_the_prompt_is_not_scored_as_loading(tmp_path):
    # $97 every time is the idle KERNAL prompt, even with the jiffy moving.
    p = write_log(tmp_path, [0x97] * 6, [100, 300, 500, 700, 900, 1100])
    ev = c64uhang.loading_evidence(p)
    assert not ev["was_loading"]
    assert ev["idle_prompt_samples"] == 6


def test_a_frozen_jiffy_is_not_scored_as_loading_either(tmp_path):
    p = write_log(tmp_path, [0x27, 0x47, 0x87, 0x27, 0x47, 0x87], [500] * 6)
    assert not c64uhang.loading_evidence(p)["was_loading"]
