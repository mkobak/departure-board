"""Text measurement, row layout, and draw helper factory."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

import fetch_departures as fd

from .font import ADV_WIDTH, BITMAP, CHAR_H, CHAR_SPACING, CHAR_W, DESCENDERS, LINE_SPACING
from .constants import (
    BOARD_MARGIN, DEST_MINS_GAP, LINE_ID_DEST_GAP, MIN_IDENT_CHARS, RIGHT_MARGIN,
)


def make_draw_helpers(off, renderer: 'Renderer', color: Tuple[int, int, int] = (255, 140, 0)):
    """Return (draw_glyph, draw_text, measure) closures bound to the given canvas and color."""
    r = renderer

    def glyph_width(ch: str) -> int:
        return r.glyph_width(ch)

    def draw_glyph(x: int, y: int, ch: str) -> None:
        bmp = BITMAP.get(ch, BITMAP[' '])
        whole_offset = 2 if ch in DESCENDERS else (1 if ch == ',' else 0)
        for dy, brow in enumerate(bmp):
            for dx, bit in enumerate(brow[:glyph_width(ch)]):
                if bit:
                    off.SetPixel(x + dx, y + dy + whole_offset, *color)

    def measure(text: str) -> int:
        return r.measure(text)

    def draw_text(x: int, y: int, text: str) -> int:
        cur = x
        for i, ch in enumerate(text):
            draw_glyph(cur, y, ch)
            cur += glyph_width(ch)
            if i != len(text) - 1:
                cur += CHAR_SPACING
        return cur - x

    return draw_glyph, draw_text, measure


class Renderer:
    def __init__(self, cols: int, rows: int):
        self.cols = cols
        self.rows = rows

    def glyph_width(self, ch: str) -> int:
        return ADV_WIDTH.get(ch, CHAR_W)

    def measure(self, text: str) -> int:
        if not text:
            return 0
        w = 0
        for i, ch in enumerate(text):
            w += self.glyph_width(ch)
            if i != len(text) - 1:
                w += CHAR_SPACING
        return w

    def rows_capacity(self, start_y: int) -> int:
        """Compute number of departure rows fitting starting at start_y (baseline of first row).

        Leaves a bottom BOARD_MARGIN row unused as border.
        """
        available = self.rows - start_y - BOARD_MARGIN
        line_height = CHAR_H + LINE_SPACING
        full = available // line_height
        leftover = available - full * line_height
        if leftover >= CHAR_H + 1:  # allow one more if glyph fits sans spacing fully
            full += 1
        return full

    def prepare_rows(self, rows: List[Dict[str, Any]], origin: str, cap: int) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for r in rows[:cap]:
            cat = (r.get('category') or '').strip().upper()
            num = (r.get('number') or '').strip()
            # Identifier column logic:
            # - Trams: show numeric part only, 2-char column (right-aligned if 1 digit)
            # - Trains/others: show category letters only (strip digits), max 3 chars, 3-char column right-aligned
            if cat in {'T', 'TRAM'} and num:
                ident_display = num
                ident_col_chars = MIN_IDENT_CHARS
            else:
                letters = ''.join(ch for ch in cat if ch.isalpha()).upper() or cat[:3].upper()
                ident_display = letters[:3]
                ident_col_chars = 3
            station_city = fd._station_city(origin)
            # Allow an explicit destination override (e.g., platform label)
            dest_override = r.get('_dest_override')
            if dest_override:
                dest = str(dest_override)
            else:
                dest_raw = (r.get('dest') or '').replace('\n', ' ')
                dest = fd._strip_same_city(dest_raw, station_city)
                dest = fd.BAHNHOF_PATTERN.sub('Bhf', dest)
            mins = int(r.get('mins') or 0)
            # width budgeting with variable advance
            ident_w = self.measure('X' * ident_col_chars)
            digits = str(mins)
            digits_w = self.measure(digits)
            apostrophe_w = self.glyph_width("'")
            inner_width = self.cols - 2 * BOARD_MARGIN
            total_minutes_w = digits_w + CHAR_SPACING + apostrophe_w + RIGHT_MARGIN
            digits_start_x = BOARD_MARGIN + inner_width - total_minutes_w
            dest_start_x = BOARD_MARGIN + ident_w + LINE_ID_DEST_GAP
            max_dest_w = digits_start_x - DEST_MINS_GAP - dest_start_x
            if max_dest_w < 0:
                max_dest_w = 0
            # truncate destination
            draw_chars: List[str] = []
            cur = 0
            for ch in dest:
                gw = self.glyph_width(ch)
                add = gw if not draw_chars else CHAR_SPACING + gw
                if cur + add > max_dest_w:
                    break
                draw_chars.append(ch)
                cur += add
            out.append({
                'ident_display': ident_display,
                'ident_col_chars': str(ident_col_chars),
                'dest': ''.join(draw_chars),
                'mins': str(mins),
            })
        return out
