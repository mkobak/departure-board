"""Breakout / DX-Ball game: rendering and logic helpers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..font import CHAR_H, LINE_SPACING
from ..constants import BOARD_MARGIN
from ..renderer import Renderer, make_draw_helpers
from ..drawing import _normalize_for_display


# Layout constants (right-side play area is 84x64, matching Snake)
PLAY_X = 44
PLAY_W = 84
PLAY_H = 64

BRICK_ROWS = 5
BRICK_COLS = 6
BRICK_W = 12
BRICK_H = 3
BRICK_TOP = 8          # first brick row y offset (top wall gap for ball tunneling)
BRICK_SIDE_MARGIN = 6  # gap between play-area edge and outermost brick column
BRICK_GAP_X = 0        # bricks sit flush horizontally; row colors give separation
BRICK_GAP_Y = 0

PADDLE_W = 14
PADDLE_H = 2
PADDLE_Y = 60          # top row of paddle

BALL_SIZE = 2

# Row tier -> (color_rgb, score_value). Tier 1 is top row, 5 is bottom.
ROW_TIERS: List[Tuple[Tuple[int, int, int], int]] = [
    ((255, 60, 0),    50),   # red
    ((255, 140, 0),   30),   # orange
    ((220, 180, 0),   20),   # yellow
    ((80, 200, 80),   10),   # green
    ((80, 120, 255),  10),   # blue
]


def draw_pregame_frame(off, matrix, renderer: Renderer, high_scores: List[Dict[str, Any]]):
    """Pre-game screen with '> Play' and top 3 high scores (identical to Snake)."""
    off.Fill(0, 0, 0)
    _, draw_text, _ = make_draw_helpers(off, renderer)
    line_h = CHAR_H + LINE_SPACING
    y = BOARD_MARGIN + 2

    draw_text(BOARD_MARGIN + 1, y, _normalize_for_display("> Play"))
    y += line_h + 3

    top3 = high_scores[:3]
    for i, entry in enumerate(top3):
        hs_name = _normalize_for_display(entry['name'])
        hs_text = f"{i + 1}. {hs_name} {entry['score']}"
        draw_text(BOARD_MARGIN + 1, y, _normalize_for_display(hs_text))
        y += line_h
        if y + CHAR_H > renderer.rows - BOARD_MARGIN:
            break

    return matrix.SwapOnVSync(off)


def draw_game_over_frame(off, matrix, renderer: Renderer, score: int, sel: int, is_new_high_score: bool):
    """Game over screen identical in shape to Snake's."""
    off.Fill(0, 0, 0)
    _, draw_text, _ = make_draw_helpers(off, renderer)
    line_h = CHAR_H + LINE_SPACING
    y = BOARD_MARGIN + 2

    draw_text(BOARD_MARGIN + 1, y, _normalize_for_display("Game over"))
    y += line_h

    score_line = f"New high score: {score}" if is_new_high_score else f"Score: {score}"
    draw_text(BOARD_MARGIN + 1, y, _normalize_for_display(score_line))
    y += line_h

    draw_text(BOARD_MARGIN + 1, y, _normalize_for_display(">Play again" if sel == 0 else " Play again"))
    y += line_h

    draw_text(BOARD_MARGIN + 1, y, _normalize_for_display(">Exit" if sel == 1 else " Exit"))

    return matrix.SwapOnVSync(off)


def _draw_rect(off, x: int, y: int, w: int, h: int, color: Tuple[int, int, int], bounds_w: int, bounds_h: int) -> None:
    r, g, b = color
    for py in range(y, y + h):
        if py < 0 or py >= bounds_h:
            continue
        for px in range(x, x + w):
            if px < 0 or px >= bounds_w:
                continue
            off.SetPixel(px, py, r, g, b)


def draw_breakout_frame(off, matrix, renderer: Renderer,
                        ball_xy: Tuple[float, float],
                        paddle_x: int,
                        bricks: List[List[int]],
                        lives: int = 3,
                        score: int = 0,
                        username: str = "Anonymous",
                        high_scores: Optional[List[Dict[str, Any]]] = None,
                        game_over: bool = False,
                        **_kw):
    """Draw the active Breakout game: left score panel, right play area."""
    off.Fill(0, 0, 0)

    panel_width = PLAY_X - 2
    separator_x = PLAY_X - 1

    # --- Score Panel (left side) ---
    _, draw_text, measure = make_draw_helpers(off, renderer)
    line_h = CHAR_H + LINE_SPACING
    y = BOARD_MARGIN + 1

    # Player name (truncated to fit)
    name_display = _normalize_for_display(username)
    truncated = ""
    for ch in name_display:
        if measure(truncated + ch) > panel_width:
            break
        truncated += ch
    draw_text(BOARD_MARGIN, y, truncated)
    y += line_h

    # Score
    draw_text(BOARD_MARGIN, y, _normalize_for_display(str(score)))
    y += line_h

    # Lives
    draw_text(BOARD_MARGIN, y, _normalize_for_display(f"Lives {lives}"))
    y += line_h + 2

    # Top 3 high scores (numbers only)
    top3 = (high_scores or [])[:3]
    for i, entry in enumerate(top3):
        hs_text = _normalize_for_display(f"{i + 1}. {entry['score']}")
        draw_text(BOARD_MARGIN, y, hs_text)
        y += line_h
        if y + CHAR_H > renderer.rows - BOARD_MARGIN:
            break

    # Separator line (dim amber)
    for py in range(renderer.rows):
        off.SetPixel(separator_x, py, 80, 40, 0)

    # --- Play area (right side) ---
    cols, rows = renderer.cols, renderer.rows

    # Bricks
    for row_idx, row in enumerate(bricks):
        color, _pts = ROW_TIERS[row_idx] if row_idx < len(ROW_TIERS) else ROW_TIERS[-1]
        if game_over:
            color = (255, 0, 0)
        by = BRICK_TOP + row_idx * (BRICK_H + BRICK_GAP_Y)
        for col_idx, alive in enumerate(row):
            if not alive:
                continue
            bx = PLAY_X + BRICK_SIDE_MARGIN + col_idx * (BRICK_W + BRICK_GAP_X)
            _draw_rect(off, bx, by, BRICK_W, BRICK_H, color, cols, rows)

    # Paddle (amber)
    paddle_color = (255, 0, 0) if game_over else (255, 140, 0)
    _draw_rect(off, PLAY_X + paddle_x, PADDLE_Y, PADDLE_W, PADDLE_H, paddle_color, cols, rows)

    # Ball (bright amber)
    bx = PLAY_X + int(ball_xy[0])
    by = int(ball_xy[1])
    ball_color = (255, 0, 0) if game_over else (255, 220, 100)
    _draw_rect(off, bx, by, BALL_SIZE, BALL_SIZE, ball_color, cols, rows)

    return matrix.SwapOnVSync(off)
