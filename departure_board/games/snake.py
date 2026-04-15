"""Snake game: rendering and logic."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..font import BITMAP, CHAR_H, CHAR_SPACING, DESCENDERS, LINE_SPACING
from ..constants import BOARD_MARGIN
from ..renderer import Renderer, make_draw_helpers
from ..drawing import _normalize_for_display
from ..scores import load_high_scores


def draw_pregame_frame(off, matrix, renderer: Renderer, high_scores: List[Dict[str, Any]]):
    """Draw the pre-game screen with > Play and top 3 high scores."""
    off.Fill(0, 0, 0)
    _, draw_text, measure = make_draw_helpers(off, renderer)
    line_h = CHAR_H + LINE_SPACING
    y = BOARD_MARGIN + 2

    # Play button
    draw_text(BOARD_MARGIN + 1, y, _normalize_for_display("> Play"))
    y += line_h + 3

    # Top 3 high scores
    top3 = high_scores[:3]
    if top3:
        for i, entry in enumerate(top3):
            hs_name = _normalize_for_display(entry['name'])
            hs_text = f"{i + 1}. {hs_name} {entry['score']}"
            draw_text(BOARD_MARGIN + 1, y, _normalize_for_display(hs_text))
            y += line_h
            if y + CHAR_H > renderer.rows - BOARD_MARGIN:
                break

    return matrix.SwapOnVSync(off)


def draw_snake_frame(off, matrix, renderer: Renderer,
                     snake_body: List[Tuple[int, int]], snake_food: Optional[Tuple[int, int]],
                     game_over: bool = False, cell: int = 2,
                     game_x_offset: int = 44,
                     username: str = "Anonymous", score: int = 0,
                     high_scores: Optional[List[Dict[str, Any]]] = None, **_kw):
    """Draw the snake game with left score panel and right play area."""
    off.Fill(0, 0, 0)

    panel_width = game_x_offset - 2  # usable panel content width
    separator_x = game_x_offset - 1  # vertical divider line

    # --- Score Panel (left side) ---
    _, draw_text, measure = make_draw_helpers(off, renderer)
    line_h = CHAR_H + LINE_SPACING
    y = BOARD_MARGIN + 1

    # Player name (truncate to fit panel)
    name_display = _normalize_for_display(username)
    truncated = ""
    for ch in name_display:
        if measure(truncated + ch) > panel_width:
            break
        truncated += ch
    draw_text(BOARD_MARGIN, y, truncated)
    y += line_h

    # Score
    score_text = _normalize_for_display(str(score))
    draw_text(BOARD_MARGIN, y, score_text)
    y += line_h + 3  # gap before high scores

    # Top 3 high scores (numbers only)
    top3 = (high_scores or [])[:3]
    if top3:
        for i, entry in enumerate(top3):
            hs_text = _normalize_for_display(f"{i + 1}. {entry['score']}")
            draw_text(BOARD_MARGIN, y, hs_text)
            y += line_h

    # Separator line (dim amber)
    for py in range(renderer.rows):
        off.SetPixel(separator_x, py, 80, 40, 0)

    # --- Game Area (right side) ---
    def fill_cell(gx: int, gy: int, r: int, g: int, b: int) -> None:
        for dy in range(cell):
            for dx in range(cell):
                px = game_x_offset + gx * cell + dx
                py = gy * cell + dy
                if px < renderer.cols and py < renderer.rows:
                    off.SetPixel(px, py, r, g, b)

    if game_over:
        for gx, gy in snake_body:
            fill_cell(gx, gy, 255, 0, 0)  # flash red on death
    else:
        if snake_food:
            fill_cell(snake_food[0], snake_food[1], 255, 255, 0)  # yellow food
        for i, (gx, gy) in enumerate(snake_body):
            if i == 0:
                fill_cell(gx, gy, 255, 140, 0)   # head: full amber
            else:
                fill_cell(gx, gy, 160, 80, 0)    # body: dimmer amber
    return matrix.SwapOnVSync(off)
