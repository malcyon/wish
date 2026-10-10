"""`dos_codec.pod_item_type_table` reads Pools of Darkness's headerless `ITEMS`."""
from goldbox import dos_codec

WHOLE = bytes(range(256)) * 8


def test_a_headerless_items_file_is_returned_whole(tmp_path):
    (tmp_path / "ITEMS").write_bytes(WHOLE)
    assert dos_codec.pod_item_type_table(tmp_path) == WHOLE


def test_the_file_is_found_beside_a_save_folder(tmp_path):
    (tmp_path / "ITEMS").write_bytes(WHOLE)
    save = tmp_path / "SAVE"
    save.mkdir()
    assert dos_codec.pod_item_type_table(save) == WHOLE


def test_a_file_with_the_two_byte_header_is_not_this_titles(tmp_path):
    (tmp_path / "ITEMS").write_bytes(b"\0\0" + WHOLE)
    assert dos_codec.pod_item_type_table(tmp_path) is None


def test_no_file_and_no_folder_give_none(tmp_path):
    assert dos_codec.pod_item_type_table(tmp_path) is None
    assert dos_codec.pod_item_type_table(None) is None
