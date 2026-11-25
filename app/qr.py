"""Minimal zero-dependency ISO/IEC 18004 QR Code SVG generator (Versions 2-L & 3-L)."""

import base64

# GF(256) log/exp tables for primitive polynomial 0x11D
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_ecc(data: list[int], ec_count: int) -> list[int]:
    gen = [1]
    for i in range(ec_count):
        nxt = [0] * (len(gen) + 1)
        factor = _EXP[i]
        for j, coeff in enumerate(gen):
            nxt[j] ^= coeff
            nxt[j + 1] ^= _gf_mul(coeff, factor)
        gen = nxt

    rem = [0] * ec_count
    for byte in data:
        lead = byte ^ rem[0]
        rem = rem[1:] + [0]
        for j in range(ec_count):
            rem[j] ^= _gf_mul(gen[j + 1], lead)
    return rem


def _format_bits(mask: int = 0) -> int:
    # ECC Level L = 0b01
    fmt = (0b01 << 3) | (mask & 0b111)
    d = fmt << 10
    for shift in range(4, -1, -1):
        if d & (1 << (shift + 10)):
            d ^= 0x537 << shift
    return ((fmt << 10) | d) ^ 0x5412


def encode_qr_matrix(text: str) -> list[list[bool]]:
    raw = text.encode("utf-8")
    if len(raw) <= 32:
        version, size, data_cw, ec_cw, align = 2, 25, 34, 10, [(18, 18)]
    else:
        raw = raw[:53]
        version, size, data_cw, ec_cw, align = 3, 29, 55, 15, [(22, 22)]

    # Bitstream: Byte mode (0100) + 8-bit length + bytes + terminator + pad
    bits: list[int] = []

    def push(val: int, width: int):
        for s in range(width - 1, -1, -1):
            bits.append((val >> s) & 1)

    push(0b0100, 4)
    push(len(raw), 8)
    for b in raw:
        push(b, 8)
    max_bits = data_cw * 8
    term = min(4, max_bits - len(bits))
    push(0, term)
    while len(bits) % 8 != 0:
        bits.append(0)

    codewords = [
        int("".join(str(b) for b in bits[i : i + 8]), 2)
        for i in range(0, len(bits), 8)
    ]
    pad_bytes = (0xEC, 0x11)
    idx = 0
    while len(codewords) < data_cw:
        codewords.append(pad_bytes[idx % 2])
        idx += 1

    all_cw = codewords + _rs_ecc(codewords, ec_cw)
    all_bits: list[int] = []
    for cw in all_cw:
        for s in range(7, -1, -1):
            all_bits.append((cw >> s) & 1)
    all_bits.extend([0] * 7)  # 7 remainder bits for Versions 2 & 3

    modules = [[False] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def set_fn(r: int, c: int, dark: bool):
        if 0 <= r < size and 0 <= c < size:
            modules[r][c] = dark
            reserved[r][c] = True

    def place_finder(top: int, left: int):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = top + dr, left + dc
                if 0 <= r < size and 0 <= c < size:
                    in_outer = 0 <= dr <= 6 and 0 <= dc <= 6
                    dark = in_outer and (
                        dr in (0, 6) or dc in (0, 6) or (2 <= dr <= 4 and 2 <= dc <= 4)
                    )
                    set_fn(r, c, dark)

    place_finder(0, 0)
    place_finder(0, size - 7)
    place_finder(size - 7, 0)

    for ar, ac in align:
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                dark = max(abs(dr), abs(dc)) != 1
                set_fn(ar + dr, ac + dc, dark)

    for i in range(8, size - 8):
        dark = i % 2 == 0
        set_fn(6, i, dark)
        set_fn(i, 6, dark)

    set_fn(4 * version + 9, 8, True)

    # Reserve format info cells
    for i in range(9):
        if i != 6:
            reserved[8][i] = True
            reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
    for i in range(7):
        reserved[size - 1 - i][8] = True

    # Zigzag data placement with Mask 0: (r + c) % 2 == 0
    bit_idx = 0
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for c in (col, col - 1):
                if not reserved[r][c]:
                    bit = all_bits[bit_idx] if bit_idx < len(all_bits) else 0
                    bit_idx += 1
                    modules[r][c] = bool(bit ^ (1 if (r + c) % 2 == 0 else 0))
        upward = not upward
        col -= 2

    # Write format info for Level L + Mask 0
    fmt = _format_bits(0)
    for i in range(6):
        bit = bool((fmt >> (14 - i)) & 1)
        modules[8][i] = bit
        modules[size - 1 - i][8] = bit
    modules[8][7] = bool((fmt >> 8) & 1)
    modules[size - 7][8] = bool((fmt >> 8) & 1)
    modules[8][8] = bool((fmt >> 7) & 1)
    modules[8][size - 8] = bool((fmt >> 7) & 1)
    modules[7][8] = bool((fmt >> 6) & 1)
    modules[8][size - 7] = bool((fmt >> 6) & 1)
    for i in range(6):
        bit = bool((fmt >> (5 - i)) & 1)
        modules[5 - i][8] = bit
        modules[8][size - 6 + i] = bit

    return modules


def make_qr_data_uri(text: str) -> str:
    """Return a compact base64 SVG data URI for a scannable QR code."""
    matrix = encode_qr_matrix(text)
    size = len(matrix)
    quiet = 4
    total = size + quiet * 2
    cmds = []
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                cmds.append(f"M{c + quiet},{r + quiet}h1v1h-1z")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
        f'shape-rendering="crispEdges">'
        f'<rect width="{total}" height="{total}" fill="#ffffff"/>'
        f'<path d="{"".join(cmds)}" fill="#1c1917"/>'
        f"</svg>"
    )
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"
