"""
Minimal EXIF writer with explicit TIFF types.

Pillow infers a TIFF type from the Python value, which is wrong for EXIF in
three ways that matter here: a (num, den) tuple is written as two SHORTs
instead of one RATIONAL, a positive SRATIONAL tag is written as RATIONAL, and
bytes become BYTE instead of UNDEFINED. Every one of those shows up as a
"Non-standard format" warning in `exiftool -validate`, and a reader that trusts
the bytes gets nonsense like f/"178 100" or a 6765 mm lens. A real phone never
writes those, so here every tag carries its type explicitly.

Values:
    ASCII                str
    BYTE, UNDEFINED      bytes
    SHORT, LONG, SLONG   int or list of int
    RATIONAL, SRATIONAL  (num, den) or list of (num, den)
"""

import struct

BYTE, ASCII, SHORT, LONG, RATIONAL, UNDEFINED, SLONG, SRATIONAL = 1, 2, 3, 4, 5, 7, 9, 10

TAG_EXIF_IFD = 0x8769
TAG_GPS_IFD = 0x8825
TAG_THUMB_OFFSET = 0x0201
TAG_THUMB_LENGTH = 0x0202


def _payload(bo, typ, value):
    """Encode one tag value. Returns (count, bytes)."""
    if typ == ASCII:
        raw = value.encode("ascii") + b"\0"
        return len(raw), raw
    if typ in (BYTE, UNDEFINED):
        raw = bytes(value)
        return len(raw), raw
    values = value if isinstance(value, list) else [value]
    if typ in (RATIONAL, SRATIONAL):
        fmt = bo + ("II" if typ == RATIONAL else "ii")
        return len(values), b"".join(struct.pack(fmt, n, d) for n, d in values)
    fmt = bo + {SHORT: "H", LONG: "I", SLONG: "i"}[typ]
    return len(values), b"".join(struct.pack(fmt, v) for v in values)


def _data_len(bo, entries):
    """Bytes an IFD needs outside its 12-byte entries (word-aligned)."""
    total = 0
    for _, typ, value in entries:
        size = len(_payload(bo, typ, value)[1])
        if size > 4:
            total += size + (size & 1)
    return total


def _ifd_size(bo, entries):
    return 2 + 12 * len(entries) + 4 + _data_len(bo, entries)


def _ifd(bo, entries, offset, next_ifd=0):
    """Serialize one IFD that starts `offset` bytes into the TIFF stream."""
    entries = sorted(entries, key=lambda e: e[0])
    data_at = offset + 2 + 12 * len(entries) + 4
    table = struct.pack(bo + "H", len(entries))
    data = b""
    for tag, typ, value in entries:
        count, raw = _payload(bo, typ, value)
        if len(raw) <= 4:
            field = raw.ljust(4, b"\0")
        else:
            field = struct.pack(bo + "I", data_at + len(data))
            data += raw + (b"\0" if len(raw) & 1 else b"")
        table += struct.pack(bo + "HHI", tag, typ, count) + field
    table += struct.pack(bo + "I", next_ifd)
    return table + data


def _with_pointer(entries, tag, value):
    return [e for e in entries if e[0] != tag] + [(tag, LONG, value)]


def build_tiff(big_endian, ifd0, exif_ifd, gps_ifd=None, thumb_ifd=None, thumbnail=None):
    """Build the TIFF stream that follows "Exif\\0\\0" in a JPEG APP1 segment.

    Pointer tags (Exif IFD, GPS IFD, thumbnail offset/length) are added here;
    callers pass only real tags. `thumbnail` is a complete JPEG, stored in IFD1.
    """
    bo = ">" if big_endian else "<"
    header = (b"MM\0*" if big_endian else b"II*\0") + struct.pack(bo + "I", 8)

    # Sizes do not depend on pointer values (each is one LONG), so lay out with
    # zeros first, then patch the real offsets in.
    ifd0 = _with_pointer(ifd0, TAG_EXIF_IFD, 0)
    if gps_ifd:
        ifd0 = _with_pointer(ifd0, TAG_GPS_IFD, 0)
    thumb = None
    if thumbnail:
        thumb = _with_pointer(thumb_ifd or [], TAG_THUMB_OFFSET, 0)
        thumb = _with_pointer(thumb, TAG_THUMB_LENGTH, len(thumbnail))

    at_ifd0 = 8
    at_exif = at_ifd0 + _ifd_size(bo, ifd0)
    at_gps = at_exif + _ifd_size(bo, exif_ifd)
    at_ifd1 = at_gps + (_ifd_size(bo, gps_ifd) if gps_ifd else 0)

    ifd0 = _with_pointer(ifd0, TAG_EXIF_IFD, at_exif)
    if gps_ifd:
        ifd0 = _with_pointer(ifd0, TAG_GPS_IFD, at_gps)

    out = header + _ifd(bo, ifd0, at_ifd0, next_ifd=at_ifd1 if thumb else 0)
    out += _ifd(bo, exif_ifd, at_exif)
    if gps_ifd:
        out += _ifd(bo, gps_ifd, at_gps)
    if thumb:
        at_thumb = at_ifd1 + _ifd_size(bo, thumb)
        thumb = _with_pointer(thumb, TAG_THUMB_OFFSET, at_thumb)
        out += _ifd(bo, thumb, at_ifd1) + thumbnail
    return out


def jpeg_with_exif(jpeg, tiff):
    """Return `jpeg` with its APP0/APP1 segments replaced by one EXIF APP1.

    Pillow always writes a JFIF APP0 header. Phone cameras do not, so it is
    dropped rather than kept next to the EXIF block.
    """
    if jpeg[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG stream")
    body = b"Exif\0\0" + tiff
    if len(body) + 2 > 0xFFFF:
        raise ValueError(f"EXIF block too large for one APP1 segment ({len(body)} bytes)")
    app1 = b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body

    pos = 2
    while jpeg[pos] == 0xFF and jpeg[pos + 1] in (0xE0, 0xE1):
        pos += 2 + struct.unpack(">H", jpeg[pos + 2:pos + 4])[0]
    return b"\xff\xd8" + app1 + jpeg[pos:]
