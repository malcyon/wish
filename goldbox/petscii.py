"""C64 text helpers.

Two *distinct* string conventions appear in this project and they must not be
confused:

1. **Character-record names** -- a fixed 20-byte field inside the 580-byte
   character record, plain ASCII, padded with NUL (``0x00``).  Use
   :func:`decode_record_name` / :func:`encode_record_name`.

2. **1541 directory names** -- a fixed 16-byte field in a CBM DOS directory
   entry, PETSCII, padded with shifted-space (``0xA0``).  A name may also
   carry a leading ``0x01`` control byte (used by some Gold Box save files to
   sort/flag entries), which is not part of the displayed name.  Use
   :func:`decode_directory_name` / :func:`encode_directory_name`.

Decoding is deliberately *display-oriented* and therefore lossy for control
bytes: unrepresentable bytes become :data:`SUBSTITUTE`.  Round-tripping of a
record is never done through text -- :class:`goldbox.record.CharacterRecord` keeps
the raw bytes and only rewrites a name field when it is explicitly assigned.
Use :func:`is_canonical_record_name` to check whether a particular field will
survive a decode/encode cycle unchanged.
"""

from __future__ import annotations

__all__ = [
    "RECORD_NAME_SIZE",
    "RECORD_NAME_PAD",
    "DIR_NAME_SIZE",
    "DIR_NAME_PAD",
    "DIR_NAME_CONTROL",
    "SUBSTITUTE",
    "decode_record_name",
    "encode_record_name",
    "is_canonical_record_name",
    "decode_directory_name",
    "encode_directory_name",
    "petscii_to_text",
    "text_to_petscii",
]

#: Width of the name field inside a character record.
RECORD_NAME_SIZE = 20
#: Padding byte for record names.
RECORD_NAME_PAD = 0x00

#: Width of a 1541 directory name field.
DIR_NAME_SIZE = 16
#: Padding byte for directory names (shifted space).
DIR_NAME_PAD = 0xA0
#: Control byte that may precede a directory name; not part of the text.
DIR_NAME_CONTROL = 0x01

#: Replacement character used for bytes with no printable representation.
SUBSTITUTE = "."


# ---------------------------------------------------------------------------
# Character-record names (ASCII, NUL-padded, 20 bytes)
# ---------------------------------------------------------------------------
def decode_record_name(raw: bytes) -> str:
    """Decode a NUL-padded record-name field to text.

    Everything from the first NUL onwards is dropped; trailing spaces are
    stripped.  Non-printable bytes become :data:`SUBSTITUTE`.

    Args:
        raw: The name field's bytes (any length; typically 20).
    """
    data = bytes(raw)
    end = data.find(RECORD_NAME_PAD)
    if end >= 0:
        data = data[:end]
    return "".join(
        chr(b) if 0x20 <= b < 0x7F else SUBSTITUTE for b in data
    ).rstrip(" ")


def encode_record_name(text: str, size: int = RECORD_NAME_SIZE) -> bytes:
    """Encode *text* as a NUL-padded record-name field of exactly *size* bytes.

    Raises:
        ValueError: if the text is too long or contains non-ASCII / control
            characters.
    """
    encoded = bytearray()
    for ch in text:
        code = ord(ch)
        if not 0x20 <= code < 0x7F:
            raise ValueError(
                f"character {ch!r} (U+{code:04X}) cannot be stored in a record name"
            )
        encoded.append(code)
    if len(encoded) > size:
        raise ValueError(
            f"name {text!r} is {len(encoded)} bytes; field holds at most {size}"
        )
    encoded.extend(bytes([RECORD_NAME_PAD]) * (size - len(encoded)))
    return bytes(encoded)


def is_canonical_record_name(raw: bytes) -> bool:
    """True if ``encode_record_name(decode_record_name(raw))`` reproduces *raw*.

    False means the field holds bytes the text form cannot represent (control
    bytes, or data past the terminating NUL) and must be preserved verbatim.
    """
    data = bytes(raw)
    try:
        return encode_record_name(decode_record_name(data), len(data)) == data
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# PETSCII <-> text (used for 1541 directory names)
# ---------------------------------------------------------------------------
def petscii_to_text(raw: bytes) -> str:
    """Map PETSCII bytes to displayable ASCII.

    ``0x20``-``0x5F`` map straight through (letters read as upper case, as they
    display in the default uppercase/graphics charset).  ``0xC1``-``0xDA`` --
    the shifted letter range -- also map to ``A``-``Z``.  Anything else becomes
    :data:`SUBSTITUTE`.
    """
    out = []
    for b in bytes(raw):
        if 0x20 <= b <= 0x5F:
            out.append(chr(b))
        elif 0xC1 <= b <= 0xDA:
            out.append(chr(b - 0x80))
        else:
            out.append(SUBSTITUTE)
    return "".join(out)


def text_to_petscii(text: str) -> bytes:
    """Map ASCII text to PETSCII bytes (inverse of the ``0x20``-``0x5F`` range).

    Lower-case letters are folded to upper case, which is how they appear in a
    1541 directory.

    Raises:
        ValueError: on a character with no PETSCII representation here.
    """
    out = bytearray()
    for ch in text.upper():
        code = ord(ch)
        if not 0x20 <= code <= 0x5F:
            raise ValueError(
                f"character {ch!r} (U+{code:04X}) has no PETSCII mapping here"
            )
        out.append(code)
    return bytes(out)


# ---------------------------------------------------------------------------
# 1541 directory names (PETSCII, 0xA0-padded, 16 bytes)
# ---------------------------------------------------------------------------
def decode_directory_name(raw: bytes, keep_control: bool = False) -> str:
    """Decode a 16-byte, ``0xA0``-padded CBM DOS directory name.

    Args:
        raw: The name field's bytes.
        keep_control: If True, a leading :data:`DIR_NAME_CONTROL` byte is
            rendered as ``SUBSTITUTE`` instead of being dropped.
    """
    data = bytes(raw)
    if not keep_control and data[:1] == bytes([DIR_NAME_CONTROL]):
        data = data[1:]
    end = data.find(DIR_NAME_PAD)
    if end >= 0:
        data = data[:end]
    return petscii_to_text(data).rstrip(" ")


def encode_directory_name(
    text: str,
    size: int = DIR_NAME_SIZE,
    leading_control: bool = False,
) -> bytes:
    """Encode *text* as a ``0xA0``-padded directory-name field of *size* bytes.

    Args:
        text: The name.
        size: Field width (16 for a standard directory entry).
        leading_control: Emit a :data:`DIR_NAME_CONTROL` byte before the name;
            it counts against the field width.

    Raises:
        ValueError: if the encoded name does not fit.
    """
    body = text_to_petscii(text)
    if leading_control:
        body = bytes([DIR_NAME_CONTROL]) + body
    if len(body) > size:
        raise ValueError(
            f"name {text!r} needs {len(body)} bytes; field holds at most {size}"
        )
    return body + bytes([DIR_NAME_PAD]) * (size - len(body))
