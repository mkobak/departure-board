#!/usr/bin/env python3
"""Interactive 128x64 virtual departure board demo (single fixed 5x7 font).

Key details:
1. Fixed 5x7 pixel font (base cell 5x7) with variable visual advance for some glyphs.
2. One pixel of spacing between characters (not added after final glyph in a run).
3. Minutes column right-aligned; destination truncated to fit between line id and minutes.
4. Original capitalization from API is preserved (no Title Case transformation).
5. Pixels drawn as circular amber "LED" dots.
6. Reduced word gap: space = 2px advance + 1px char spacing -> 3px visible gap.
7. Dash rendered 3px wide. Apostrophe 1px wide and minutes block leaves 1px board margin.
"""
from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Dict, List

import requests  # noqa: F401  (Needed by fetch_departures import side effects)

import fetch_departures as fd

###################################################################################################
# Fixed 5x7 font (every glyph exactly 5 columns x 7 rows). Both UPPERCASE and lowercase provided.  #
# Each entry: list of 7 strings, each 5 chars '0'/'1'. Lowercase uses simplified shapes.           #
# Added: lowercase umlauts (ä, ö, ü). Apostrophe tightened (pixel shifted left) to reduce gap to   #
# minutes. Descenders (p,g,j,q,y) rendered with runtime vertical offset to extend below baseline.  #
###################################################################################################
FONT_5x7: Dict[str, List[str]] = {
    ' ': ["00000"] * 7,  # (advance overridden to 2px)
    '0': ["01110","10001","10011","10101","11001","10001","01110"],
    '1': ["00100","01100","00100","00100","00100","00100","01110"],
    '2': ["01110","10001","00001","00010","00100","01000","11111"],
    '3': ["11110","00001","00001","01110","00001","00001","11110"],
    '4': ["10010","10010","10010","11111","00010","00010","00010"],
    '5': ["11111","10000","10000","11110","00001","00001","11110"],
    '6': ["01110","10000","10000","11110","10001","10001","01110"],
    '7': ["11111","00001","00010","00100","01000","01000","01000"],
    '8': ["01110","10001","10001","01110","10001","10001","01110"],
    '9': ["01110","10001","10001","01111","00001","00001","01110"],
    'A': ["01110","10001","10001","11111","10001","10001","10001"],
    'B': ["11110","10001","10001","11110","10001","10001","11110"],
    'C': ["01110","10001","10000","10000","10000","10001","01110"],
    'D': ["11110","10001","10001","10001","10001","10001","11110"],
    'E': ["11111","10000","10000","11110","10000","10000","11111"],
    'F': ["11111","10000","10000","11110","10000","10000","10000"],
    'G': ["01110","10001","10000","10111","10001","10001","01110"],
    'H': ["10001","10001","10001","11111","10001","10001","10001"],
    'I': ["01110","00100","00100","00100","00100","00100","01110"],
    'J': ["00111","00010","00010","00010","00010","10010","01100"],
    'K': ["10001","10010","10100","11000","10100","10010","10001"],
    'L': ["10000","10000","10000","10000","10000","10000","11111"],
    'M': ["10001","11011","10101","10101","10001","10001","10001"],
    'N': ["10001","11001","10101","10011","10001","10001","10001"],
    'O': ["01110","10001","10001","10001","10001","10001","01110"],
    'P': ["11110","10001","10001","11110","10000","10000","10000"],
    'Q': ["01110","10001","10001","10001","10101","10010","01101"],
    'R': ["11110","10001","10001","11110","10100","10010","10001"],
    'S': ["01111","10000","10000","01110","00001","00001","11110"],
    'T': ["11111","00100","00100","00100","00100","00100","00100"],
    'U': ["10001","10001","10001","10001","10001","10001","01110"],
    'V': ["10001","10001","10001","10001","10001","01010","00100"],
    'W': ["10001","10001","10001","10101","10101","11011","10001"],
    'X': ["10001","10001","01010","00100","01010","10001","10001"],
    'Y': ["10001","10001","01010","00100","00100","00100","00100"],
    'Z': ["11111","00001","00010","00100","01000","10000","11111"],
    'a': ["00000","00000","01110","00001","01111","10001","01111"],
    'b': ["10000","10000","11110","10001","10001","10001","11110"],
    'c': ["00000","00000","01110","10000","10000","10001","01110"],
    'd': ["00001","00001","01111","10001","10001","10001","01111"],
    'e': ["00000","00000","01110","10001","11111","10000","01110"],
    'f': ["00110","01001","01000","11100","01000","01000","01000"],
    # g with 2px descender (rows 5-6 rendered lower)
    'g': ["01110","10001","10001","01111","00001","00001","01110"],
    'h': ["10000","10000","11110","10001","10001","10001","10001"],
    'i': ["00100","00000","01100","00100","00100","00100","01110"],
    # j with 2px descender tail
    'j': ["00000","00000","00110","00010","00010","00010","01100"],
    'k': ["10000","10000","10010","10100","11000","10100","10010"],
    'l': ["01100","00100","00100","00100","00100","00100","01110"],
    'm': ["00000","00000","11010","10101","10101","10101","10101"],
    'n': ["00000","00000","11110","10001","10001","10001","10001"],
    'o': ["00000","00000","01110","10001","10001","10001","01110"],
    # p with 2px descender (full-height bowl before shift)
    'p': ["11110","10001","10001","11110","10000","10000","10000"],
    # q with 2px descender
    'q': ["01110","10001","10001","01111","00001","00001","00001"],
    'r': ["00000","00000","10110","11001","10000","10000","10000"],
    's': ["00000","00000","01111","10000","01110","00001","11110"],
    't': ["00100","00100","11111","00100","00100","00100","00110"],
    'u': ["00000","00000","10001","10001","10001","10001","01111"],
    'v': ["00000","00000","10001","10001","10001","01010","00100"],
    'w': ["00000","00000","10001","10101","10101","11011","10001"],
    'x': ["00000","00000","10001","01010","00100","01010","10001"],
    # y with 2px descender
    'y': ["10001","10001","10001","01111","00001","00001","01110"],
    'z': ["00000","00000","11111","00010","00100","01000","11111"],
    # Narrow dash (only first 3 columns used -> advance overridden to 3) centered vertically
    '-': ["00000","00000","00000","11100","00000","00000","00000"],
    '/': ["00001","00010","00100","00100","01000","10000","10000"],
    # Apostrophe: single leading column (advance overridden to 1)
    "'": ["10000","10000","10000","00000","00000","00000","00000"],
    # Colon (two vertically separated dots centered). We'll use first and fifth rows for dots.
    ':': ["00000","01000","00000","00000","01000","00000","00000"],
    # Comma: draw head at baseline; runtime adds +1 offset so it hangs 1px below line
    ',': ["00000","00000","00000","00000","00000","00000","01000"],
    'Ä': ["01110","10001","10001","11111","10001","10001","10001"],
    'Ö': ["01110","10001","10001","10001","10001","10001","01110"],
    'Ü': ["10001","10001","10001","10001","10001","10001","01110"],
    # Lowercase umlauts (use top row for dots, keep second row blank like other lowercase forms)
    'ä': ["01010","00000","01110","00001","01111","10001","01111"],
    'ö': ["01010","00000","01110","10001","10001","10001","01110"],
    'ü': ["01010","00000","10001","10001","10001","10001","01111"],
}

# Precompute bitmap (list of 7 lists of 5 ints)
BITMAP: Dict[str, List[List[int]]] = {
    ch: [[1 if c == '1' else 0 for c in row] for row in rows]
    for ch, rows in FONT_5x7.items()
}

CHAR_W = 5
CHAR_H = 7



def rows_capacity(available_height: int | None = None) -> int:
    """How many text rows fit in given height (defaults whole board)."""
    if available_height is None:
        available_height = BOARD_HEIGHT_PX
    line_height = CHAR_H + VERT_SPACING
    full = available_height // line_height
    leftover = available_height - full * line_height
    # If there's enough leftover space to draw another glyph (even without the trailing
    # inter-line spacing), allow one more row. We require room for the 7px glyph box
    # plus up to 2px descender extension. Being slightly permissive avoids dropping
    # the final departure line when only the *spacing* doesn't fit.
    if leftover >= CHAR_H + 1:  # 7 (glyph) + 1 (at least part of descender)
        full += 1
    return full

# Constants (updated board size 128x64)
BOARD_WIDTH_PX = 128
BOARD_HEIGHT_PX = 64
CHAR_SPACING = 1  # pixel gap after each glyph (except after final glyph in a run)
LINE_ID_DEST_GAP = 5  # pixels between line id and destination (increased from 2)
DEST_MINS_GAP = 4     # pixels between destination and minutes
# Increase vertical spacing to allow room for descenders (requested 3-4px -> choose 4)
VERT_SPACING = 5
SCALE = 6
ON_COLOR = '#ff8c00'
OFF_COLOR = '#1b1200'
BG_COLOR = '#000000'

class DepartureBoard(tk.Canvas):
    def __init__(self, master: tk.Widget):
        super().__init__(master, width=BOARD_WIDTH_PX * SCALE, height=BOARD_HEIGHT_PX * SCALE,
                         bg=BG_COLOR, highlightthickness=0)
        # Create LED circle items once for performance
        self._pixels: List[int] = []  # store shape ids row-major
        inset = 0.6  # smaller circle inside pixel square
        for y in range(BOARD_HEIGHT_PX):
            for x in range(BOARD_WIDTH_PX):
                x0 = x * SCALE
                y0 = y * SCALE
                x1 = (x + 1) * SCALE
                y1 = (y + 1) * SCALE
                # Shrink for circular LED look
                pid = self.create_oval(
                    x0 + inset,
                    y0 + inset,
                    x1 - inset,
                    y1 - inset,
                    outline='', fill=OFF_COLOR,
                )
                self._pixels.append(pid)

    def clear(self):
        for pid in self._pixels:
            self.itemconfig(pid, fill=OFF_COLOR)

    def set_pixel(self, x: int, y: int, on: bool):
        if 0 <= x < BOARD_WIDTH_PX and 0 <= y < BOARD_HEIGHT_PX:
            pid = self._pixels[y * BOARD_WIDTH_PX + x]
            self.itemconfig(pid, fill=ON_COLOR if on else OFF_COLOR)

    # Variable advance widths for selected glyphs (visual width, not bitmap column count)
    _ADV_WIDTH: Dict[str, int] = {
        ' ': 2,   # word gap target => 2 + 1 spacing = 3px
        '-': 3,
        "'": 1,
        ',': 1,
        ':': 3,
    }

    def glyph_width(self, ch: str) -> int:
        return self._ADV_WIDTH.get(ch, CHAR_W)

    def draw_glyph(self, ch: str, x_start: int, row_index: int) -> int:
        """Draw glyph at pixel x_start; return advance width.

        Descender strategy:
          - Base line for regular letters is bottom (row 6 of bitmap).
          - For descenders (p,g,q,y,j) only the last two bitmap rows (dy >=5)
            are shifted downward by 2px so the main bowl/body height matches
            other lowercase letters while the tail extends 2px below baseline.
          - Comma rows are shifted downward by 1px (hang below line slightly).
        """
        bitmap = BITMAP.get(ch, BITMAP[' '])
        w = self.glyph_width(ch)
        line_height = CHAR_H + VERT_SPACING
        base_offset = getattr(self, '_extra_y_offset', 0)
        y0 = base_offset + row_index * line_height
        descenders = {'p', 'g', 'q', 'y', 'j'}
        # Compute whole-glyph offset: descenders drop by 2; comma drops by 1
        whole_offset = 2 if ch in descenders else (1 if ch == ',' else 0)
        for dy, brow in enumerate(bitmap):
            for dx, bit in enumerate(brow[:w]):
                if bit:
                    self.set_pixel(x_start + dx, y0 + dy + whole_offset, True)
        return w

    def draw_text(self, text: str, x_start: int, row_index: int) -> int:
        x = x_start
        for i, ch in enumerate(text):
            aw = self.draw_glyph(ch, x, row_index)
            x += aw
            if i != len(text) - 1:
                x += CHAR_SPACING
        return x - x_start  # total advance

    def render_rows(self, rows: List[Dict[str, object]], origin: str):
        self.clear()
        # Header layout constants
        top_margin = 2            # 2px space at very top
        header_line_height = CHAR_H  # using glyph box height
        space_after_header = 3 
        rule_height = 1
        space_after_rule = 5
        # Compute base offset for departure rows
        header_block_px = (top_margin + header_line_height + space_after_header +
                           rule_height + space_after_rule)

        # Prepare header content
        station_city = fd._station_city(origin)
        # Expect origin like "Basel, Aeschenplatz"; want just stop (after first comma)
        if ',' in origin:
            parts = [p.strip() for p in origin.split(',')]
            if len(parts) >= 2:
                # City may be first or last; choose longest non-city segment after first
                stop_name = parts[1] or parts[0]
            else:
                stop_name = parts[0]
        else:
            stop_name = origin.strip()
        # If the chosen stop equals the city name, attempt alternative part
        if station_city and stop_name.lower() == station_city.lower():
            # Look for any other comma-separated piece not matching city
            alts = [p.strip() for p in origin.split(',') if p.strip().lower() != station_city.lower()]
            if alts:
                stop_name = alts[-1]
        current_time = datetime.now().strftime('%H:%M')

        # Temporarily set extra offset to draw header text
        prev_extra = getattr(self, '_extra_y_offset', 0)
        self._extra_y_offset = top_margin  # header text baseline start
        # Header horizontal padding (1px on both sides)
        left_pad = 1
        right_pad = 1
        # Right aligned time (reserve right_pad after time)
        # measure time width
        tw = 0
        for i, ch in enumerate(current_time):
            tw += self.glyph_width(ch)
            if i != len(current_time) - 1:
                tw += CHAR_SPACING
        time_x = BOARD_WIDTH_PX - right_pad - tw
        self.draw_text(current_time, time_x, 0)
        # Available width for stop name
        available_w = time_x - left_pad - CHAR_SPACING  # leave at least 1 spacing pixel before time
        # Truncate stop_name if needed
        def measure_run(txt: str) -> int:
            total = 0
            for i, ch in enumerate(txt):
                total += self.glyph_width(ch)
                if i != len(txt) - 1:
                    total += CHAR_SPACING
            return total
        if measure_run(stop_name) > available_w:
            # Trim until fits
            trimmed = []
            cur = 0
            for i, ch in enumerate(stop_name):
                w = self.glyph_width(ch)
                add = w if not trimmed else (CHAR_SPACING + w)
                if cur + add > available_w:
                    break
                trimmed.append(ch)
                cur += add
            stop_name = ''.join(trimmed)
        self.draw_text(stop_name, left_pad, 0)

        # Draw rule line
        rule_y = top_margin + header_line_height + space_after_header
        for x in range(BOARD_WIDTH_PX):
            self.set_pixel(x, rule_y, True)

        # Set offset for departures
        self._extra_y_offset = header_block_px + prev_extra
        remaining_height = BOARD_HEIGHT_PX - header_block_px
        cap = rows_capacity(remaining_height)
        for row_idx, data in enumerate(rows[:cap]):
            self._render_single_row(data, origin, row_idx)
        self._extra_y_offset = prev_extra

    def _render_single_row(self, data: Dict[str, object], origin: str, row_idx: int):
        # Helper accessors with type safety (inner functions bound to this call)
        def _get_str(key: str) -> str:
            v = data.get(key)
            return v if isinstance(v, str) else ''

        def _get_int(key: str) -> int:
            v = data.get(key)
            if isinstance(v, (int, float)):
                return int(v)
            if isinstance(v, str):
                try:
                    return int(float(v))
                except ValueError:
                    return 0
            return 0

        # Build line id (ensure fixed width column so destinations align)
        cat = _get_str('category').strip().upper()
        num = _get_str('number').strip()
        if cat in {'T', 'TRAM'} and num:
            ident = num
        else:
            line_val = _get_str('line')
            ident = (line_val or f"{cat}{num}" or '?').strip()

        MIN_IDENT_CHARS = 2  # reserve space for up to two-digit tram numbers
        if len(ident) <= MIN_IDENT_CHARS:
            # Keep fixed 2-char column; we'll draw right-aligned during rendering
            ident_display = ident
            ident_col_chars = MIN_IDENT_CHARS
        else:
            ident_display = ident
            ident_col_chars = len(ident)

        # Destination formatting: preserve original capitalization from API (except abbreviation below)
        station_city = fd._station_city(origin)
        dest_raw = _get_str('dest').replace('\n', ' ')
        dest = fd._strip_same_city(dest_raw, station_city)
        dest = fd.BAHNHOF_PATTERN.sub('Bhf', dest)
        dest_preserved = dest  # already stripped/abbreviated
        mins = _get_int('mins')
        mins_text = f"{mins}'"

        # Width helper (variable advance)
        def measure(text: str) -> int:
            if not text:
                return 0
            total = 0
            for i, ch in enumerate(text):
                total += self.glyph_width(ch)
                if i != len(text) - 1:
                    total += CHAR_SPACING
            return total

        ident_w = measure('X' * ident_col_chars)  # fixed column width
        RIGHT_MARGIN = 1  # single pixel margin between apostrophe and board edge
        # Compute minutes block positions with units digit column aligned across rows.
        digits = str(mins)
        # Width of digits block (variable width font but digits are 5px each here)
        digits_w = 0
        for i, dch in enumerate(digits):
            digits_w += self.glyph_width(dch)
            if i != len(digits) - 1:
                digits_w += CHAR_SPACING
        apostrophe_w = self.glyph_width("'")
        # Pattern: digits + (spacing) + apostrophe + RIGHT_MARGIN
        total_minutes_w = digits_w + CHAR_SPACING + apostrophe_w + RIGHT_MARGIN
        # Left edge where digits start
        digits_start_x = BOARD_WIDTH_PX - total_minutes_w
        # Apostrophe x start
        apostrophe_x = BOARD_WIDTH_PX - RIGHT_MARGIN - apostrophe_w
        # Start x for full minutes string when using generic drawing (not used, but for width budget)
        start_mins_x = digits_start_x
        dest_start_x = ident_w + LINE_ID_DEST_GAP
        max_dest_w = digits_start_x - DEST_MINS_GAP - dest_start_x
        if max_dest_w < 0:
            dest_start_x = min(dest_start_x, digits_start_x - DEST_MINS_GAP)
            max_dest_w = digits_start_x - DEST_MINS_GAP - dest_start_x

        # Truncate destination to available width
        dest_draw_chars: List[str] = []
        cur_w = 0
        for ch in dest_preserved:
            ch_w = self.glyph_width(ch)
            add = ch_w if not dest_draw_chars else CHAR_SPACING + ch_w
            if cur_w + add > max_dest_w:
                break
            dest_draw_chars.append(ch)
            cur_w += add
        dest_draw = ''.join(dest_draw_chars)

        # Draw segments
        # Draw line id right-aligned within its fixed column width (ident_col_chars)
        if ident_col_chars == MIN_IDENT_CHARS and len(ident_display) == 1:
            # Measure single char width
            gw = self.glyph_width(ident_display)
            # Available width in pixels for 2-char column: measure('XX')
            col_w = measure('X' * MIN_IDENT_CHARS)
            x_offset = col_w - gw
            self.draw_text(ident_display, x_offset, row_idx)
        else:
            self.draw_text(ident_display, 0, row_idx)
        self.draw_text(dest_draw, dest_start_x, row_idx)
        # Draw minutes digits right-aligned with fixed units column
        x = digits_start_x
        for i, dch in enumerate(digits):
            self.draw_glyph(dch, x, row_idx)
            adv = self.glyph_width(dch)
            x += adv
            if i != len(digits) - 1:
                x += CHAR_SPACING
        # Space between last digit and apostrophe
        x += CHAR_SPACING
        self.draw_glyph("'", apostrophe_x, row_idx)

# Formatting utilities -------------------------------------------------------

# build_line_fields now unused but kept for backward compatibility (returns simple textual summary)
def build_line_fields(rows: List[Dict[str, object]], origin: str) -> List[str]:
    out: List[str] = []
    cap = rows_capacity()
    for r in rows[:cap]:
        line = r.get('line') if isinstance(r.get('line'), str) else ''
        dest = r.get('dest') if isinstance(r.get('dest'), str) else ''
        mins_val = r.get('mins')
        if isinstance(mins_val, (int, float)):
            mins = int(mins_val)
        elif isinstance(mins_val, str):
            try:
                mins = int(float(mins_val))
            except ValueError:
                mins = 0
        else:
            mins = 0
        out.append(f"{line} {dest} {mins}'")
    while len(out) < cap:
        out.append('')
    return out

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Departure Board Demo (128x64)')
        self.configure(bg='#111')
        # Inputs
        frm = ttk.Frame(self)
        frm.pack(padx=8, pady=4, fill='x')
        ttk.Label(frm, text='Origin:').grid(row=0, column=0, sticky='w')
        self.origin_var = tk.StringVar(value='Basel, Aeschenplatz')
        self.dest_var = tk.StringVar(value='')  # optional destination filter
        origin_entry = ttk.Entry(frm, textvariable=self.origin_var, width=24)
        origin_entry.grid(row=0, column=1, sticky='we')
        ttk.Label(frm, text='Destination:').grid(row=0, column=2, padx=(8,0))
        dest_entry = ttk.Entry(frm, textvariable=self.dest_var, width=20)
        dest_entry.grid(row=0, column=3, sticky='we')
        ttk.Label(frm, text='Limit:').grid(row=0, column=4, padx=(8,0))
        self.limit_var = tk.StringVar(value='4')
        limit_entry = ttk.Entry(frm, textvariable=self.limit_var, width=4)
        limit_entry.grid(row=0, column=5)
        self.refresh_btn = ttk.Button(frm, text='Fetch', command=self.fetch_and_render)
        self.refresh_btn.grid(row=0, column=6, padx=(8,0))
    # Font selector removed (single 5x7 font)
        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(3, weight=1)

        self.status_var = tk.StringVar(value='Ready')
        status_lbl = ttk.Label(self, textvariable=self.status_var, anchor='w', foreground='#ccc', background='#111')
        status_lbl.pack(fill='x', padx=8)

        self.board = DepartureBoard(self)  # type: ignore[arg-type]
        self.board.pack(padx=8, pady=8)

        origin_entry.bind('<Return>', lambda e: self.fetch_and_render())
        dest_entry.bind('<Return>', lambda e: self.fetch_and_render())
        limit_entry.bind('<Return>', lambda e: self.fetch_and_render())

        # Auto refresh every 60s after first fetch
        self.after(100, self.fetch_and_render)

    def fetch_and_render(self):
        try:
            limit = int(self.limit_var.get())
        except ValueError:
            limit = 4
            self.limit_var.set('4')
        origin = self.origin_var.get().strip() or 'Basel SBB'
        dest_filter = self.dest_var.get().strip()

        def task():
            self.set_status('Fetching...')
            try:
                rows = fd.fetch_stationboard(origin, max(limit * 6, 60), transportations=['tram','train'])
                if dest_filter:
                    nf = fd._normalize(dest_filter)
                    rows = [r for r in rows if fd._normalize(r.get('dest') or '') == nf]
                # Ensure ordering by planned + delay (mins+delay) before slicing
                rows.sort(key=lambda r: (r.get('mins',0) + (r.get('delay') or 0)))
                rows = rows[:limit]
                self.after(0, lambda rows=rows: self.board.render_rows(rows, origin))
                status_extra = f" -> {dest_filter}" if dest_filter else ''
                self.set_status(f"Updated ({origin}{status_extra})")
            except Exception as e:  # noqa: BLE001
                self.set_status(f"Error: {e}")
            finally:
                # schedule next auto refresh
                self.after(60000, self.fetch_and_render)
        threading.Thread(target=task, daemon=True).start()

    def set_status(self, msg: str):
        self.status_var.set(msg)

    # Font change method removed


def main():  # pragma: no cover
    app = App()
    app.mainloop()

if __name__ == '__main__':  # pragma: no cover
    main()
