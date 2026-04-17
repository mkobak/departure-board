"""Main event loop, argument parsing, and entry point."""
from __future__ import annotations

import argparse
import os
import queue
import random
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import fetch_departures as fd

try:
    from rotary_encoder import RotaryEncoder  # type: ignore
    _HAVE_ENCODER = True
except Exception:  # noqa: BLE001
    RotaryEncoder = None  # type: ignore
    _HAVE_ENCODER = False

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions  # type: ignore
    MATRIX_AVAILABLE = True
except Exception:  # noqa: BLE001
    MATRIX_AVAILABLE = False

from .font import CHAR_H, LINE_SPACING
from .constants import BOARD_MARGIN, DEFAULT_COLS, DEFAULT_ROWS
from .renderer import Renderer
from .weather import WEATHER_CITIES, WeatherData, fetch_weather
from .scores import load_high_scores, save_high_score
from .games import GAME_LIST
from .games.snake import draw_pregame_frame, draw_snake_frame, draw_game_over_frame
from .games import breakout as bo
from .games.breakout import (
    draw_pregame_frame as draw_breakout_pregame_frame,
    draw_game_over_frame as draw_breakout_game_over_frame,
    draw_breakout_frame,
)
from .drawing import (
    draw_frame, draw_weather_frame, draw_screensaver_frame,
    draw_telegram_frame, draw_menu_frame,
    screensaver_random_pos, _start_telegram_poller,
)


def run_loop(opts: argparse.Namespace):
    if not MATRIX_AVAILABLE:
        print("rgbmatrix library not available. Falling back to plain text output (developer mode).", file=sys.stderr)
        while True:
            rows = fd.fetch_stationboard(opts.stop, opts.limit * 4, transportations=None if opts.all else ['tram','train'])
            if opts.dest:
                nf = fd._normalize(opts.dest)
                rows = [r for r in rows if fd._normalize(r.get('dest') or '') == nf]
            # Sort strictly by current minutes-to-departure to avoid inversions
            rows.sort(key=lambda r: r.get('mins', 0))
            rows = rows[:opts.limit]
            for r in rows:
                print(fd.format_departure(r, opts.stop))
            print('-' * 40)
            time.sleep(opts.refresh)
        return
    # Build screen list (two existing tram stops + third: Basel SBB -> Zurich HB, trains only)
    def _make_stop_screen(name: str) -> Dict[str, Any]:
        return {
            'origin': name,
            'header': name,
            'city_ref': name,
            'transportations': None if opts.all else ['tram','train'],
            'dest_filter': None,
        }
    screens: List[Dict[str, Any]] = []
    default_stops = ["Basel, Aeschenplatz", "Basel, Denkmal"]
    if opts.stop not in default_stops:
        screens.append(_make_stop_screen(opts.stop))
    for s in default_stops:
        screens.append(_make_stop_screen(s))
    # Third screen: trains Basel SBB -> Zurich HB only
    screens.append({
        'origin': 'Basel SBB',
        'header': 'Basel \u2192 Z\u00fcrich',
        'city_ref': 'Basel SBB',
        'transportations': ['train'],
        'dest_filter': 'Z\u00fcrich HB',
    })

    # Add two weather screens (Basel & Zurich)
    for w in WEATHER_CITIES:
        screens.append({
            'type': 'weather',
            'header': w['header'],
            'city': w['city'],
            'lat': w['lat'],
            'lon': w['lon'],
        })

    # --- Simplified State Machine --------------------------------------------------
    # Initial active screen index (prefer the one matching --stop without dest filter)
    try:
        current_index = next(i for i, sc in enumerate(screens) if sc['origin'] == opts.stop and sc['dest_filter'] is None)
    except StopIteration:
        current_index = 0
    active_screen = screens[current_index]
    # Display rows currently shown (page slice) and the full fetched list for current screen
    departures: List[Dict[str, Any]] = []          # current page slice to render
    departures_all: List[Dict[str, Any]] = []      # full list from last fetch for current screen
    page_toggle: int = 0                           # 0 = first 4, 1 = next 4
    force_first_page: bool = False                 # after a stop change, hold page 0 until next rotation
    rotation_alternate: int = 0                    # (legacy, unused with directional mode)
    last_fetch_time = 0.0                          # timestamp of last successful fetch
    next_scheduled_fetch = 0.0                     # when to fetch (rotation delay, periodic refresh)
    fetch_interval = max(15.0, float(opts.refresh))  # periodic refresh (>=15s)
    rotate_fetch_delay = max(0.05, getattr(opts, 'rotate_fetch_delay', 0.5))
    encoder = None
    encoder_started_early = False
    last_rotation_accept = 0.0                     # low-level debounce between pulses
    last_rotation_action = 0.0                     # high-level action cooldown to merge bouncy pulses
    rotation_action_cooldown = float(getattr(opts, 'rotate_action_cooldown', 0.3))
    last_button_event = 0.0                        # last button press time (to guard rotations after click)
    rotate_guard_after_button = 0.25               # seconds to ignore rotation after a click
    rotation_min_interval = float(getattr(opts, 'rotate_min_interval', 0.08))

    rotation_queue: List[int] = []                 # accumulate raw deltas (optional future use)
    display_dirty: bool = True                       # redraw only when content changes
    last_rendered_minute: str = ''                   # track clock minute to detect changes
    screensaver_active: bool = False                 # whether screensaver is currently on
    last_interaction: float = time.time()            # last button/rotation time for screensaver timeout
    screensaver_timeout: float = float(getattr(opts, 'screensaver_timeout', 600))  # seconds of inactivity
    screensaver_brightness: int = int(getattr(opts, 'screensaver_brightness', 40))  # dim brightness (0-100)
    screensaver_pos: Optional[Tuple[int, int]] = None  # current clock position on screen

    # Game system state
    game_mode: str = "normal"  # "normal" | "menu" | "pregame" | "snake" | "breakout"
    menu_selection: int = 0    # index into GAME_LIST
    menu_username: str = "User"
    cached_high_scores: List[Dict[str, Any]] = []
    pregame_game: str = "Snake"  # which game the current pregame screen represents

    # Snake easter egg state
    snake_body: List[Tuple[int, int]] = []
    snake_dir: Tuple[int, int] = (1, 0)
    snake_food: Optional[Tuple[int, int]] = None
    snake_last_move: float = 0.0
    snake_move_interval: float = 0.125     # seconds per step
    snake_base_interval: float = 0.125     # starting interval
    snake_min_interval: float = 0.05      # fastest interval (reached at score 50)
    snake_max_score_for_speed: int = 50   # score at which max speed is reached
    snake_speed_step: float = 0.0         # per-food interval decrease (computed at game start)
    snake_game_over: bool = False
    snake_game_over_ts: float = 0.0
    snake_game_over_screen: bool = False  # True after red flash: showing Play again/Exit menu
    snake_game_over_sel: int = 0          # 0 = Play again, 1 = Exit
    snake_is_new_high_score: bool = False

    # Snake game grid dimensions (right 2/3 of screen)
    SNAKE_GAME_X_OFFSET = 44
    SNAKE_GAME_COLS = opts.cols - SNAKE_GAME_X_OFFSET  # 84
    SNAKE_GRID_COLS = SNAKE_GAME_COLS // 2  # 42
    SNAKE_GRID_ROWS = opts.rows // 2        # 32

    # Breakout easter egg state
    breakout_ball_x: float = 0.0        # top-left of 2x2 ball within play area (0..PLAY_W-2)
    breakout_ball_y: float = 0.0
    breakout_ball_vx: float = 0.0       # pixels per second
    breakout_ball_vy: float = 0.0
    breakout_paddle_x: int = 0          # left edge within play area (0..PLAY_W-PADDLE_W)
    breakout_bricks: List[List[int]] = []  # 2D grid: 1 = alive, 0 = broken
    breakout_lives: int = 3
    breakout_score: int = 0
    breakout_level: int = 1
    breakout_ball_stuck: bool = True    # glued to paddle; button launches
    breakout_last_tick: float = 0.0
    breakout_tick_interval: float = 0.02  # 50 Hz physics
    breakout_base_speed: float = 30.0     # pixels per second at level 1
    breakout_level_speed_bump: float = 5.0
    breakout_max_speed: float = 60.0
    breakout_game_over: bool = False
    breakout_game_over_ts: float = 0.0
    breakout_game_over_screen: bool = False
    breakout_game_over_sel: int = 0
    breakout_is_new_high_score: bool = False
    BREAKOUT_PADDLE_STEP_PX: int = 3

    # Telegram message overlay
    telegram_queue: queue.Queue = queue.Queue(maxsize=10)
    telegram_msg: Optional[str] = None     # currently displayed message
    telegram_expires: float = 0.0          # epoch time when overlay ends

    def schedule_fetch(delay: float = 0.0):
        nonlocal next_scheduled_fetch
        t = time.time() + delay
        if next_scheduled_fetch == 0.0 or t < next_scheduled_fetch:
            next_scheduled_fetch = t

    # Weather cache
    weather_cache: Dict[str, Dict[str, Any]] = {}
    # keys -> {'data': WeatherData|None, 'ts': float}

    def _wake_from_screensaver():
        """Wake from screensaver without performing any action."""
        nonlocal screensaver_active, last_interaction, display_dirty
        last_interaction = time.time()
        if screensaver_active:
            screensaver_active = False
            display_dirty = True
            schedule_fetch(0.0)  # refresh departures immediately on wake

    # --- Snake game helpers ---

    def _snake_new_food() -> Tuple[int, int]:
        while True:
            x = random.randint(0, SNAKE_GRID_COLS - 1)
            y = random.randint(0, SNAKE_GRID_ROWS - 1)
            if (x, y) not in snake_body:
                return (x, y)

    def _snake_turn(direction: int):
        nonlocal snake_dir
        dx, dy = snake_dir
        if direction > 0:   # clockwise: right -> down -> left -> up
            snake_dir = (-dy, dx)
        else:               # counter-clockwise
            snake_dir = (dy, -dx)

    def _snake_step() -> bool:
        nonlocal snake_body, snake_food, snake_move_interval, display_dirty
        hx, hy = snake_body[0]
        dx, dy = snake_dir
        nx = (hx + dx) % SNAKE_GRID_COLS
        ny = (hy + dy) % SNAKE_GRID_ROWS
        # Self-collision: ignore tail (it moves away this tick)
        if (nx, ny) in snake_body[:-1]:
            return False
        ate = (nx, ny) == snake_food
        snake_body.insert(0, (nx, ny))
        if not ate:
            snake_body.pop()
        else:
            snake_food = _snake_new_food()
            # Smooth speed progression: constant decrease per food eaten, capped at min interval
            current_score = len(snake_body) - 3
            snake_move_interval = max(snake_min_interval, snake_base_interval - current_score * snake_speed_step)
        display_dirty = True
        return True

    def _enter_snake():
        nonlocal game_mode, snake_body, snake_dir, snake_food, snake_move_interval, snake_speed_step
        nonlocal snake_last_move, snake_game_over, snake_game_over_ts, display_dirty, cached_high_scores
        nonlocal snake_game_over_screen, snake_game_over_sel, snake_is_new_high_score
        game_mode = "snake"
        snake_game_over = False
        snake_game_over_ts = 0.0
        snake_game_over_screen = False
        snake_game_over_sel = 0
        snake_is_new_high_score = False
        snake_move_interval = snake_base_interval
        snake_speed_step = (snake_base_interval - snake_min_interval) / snake_max_score_for_speed
        cx, cy = SNAKE_GRID_COLS // 2, SNAKE_GRID_ROWS // 2
        snake_body = [(cx, cy), (cx - 1, cy), (cx - 2, cy)]
        snake_dir = (1, 0)  # start moving right
        snake_food = _snake_new_food()
        snake_last_move = time.time()
        cached_high_scores = load_high_scores("snake")
        display_dirty = True

    def _exit_snake():
        nonlocal game_mode, display_dirty
        game_mode = "pregame"
        display_dirty = True

    # --- Breakout game helpers ---

    def _breakout_current_speed() -> float:
        spd = breakout_base_speed + (breakout_level - 1) * breakout_level_speed_bump
        return min(spd, breakout_max_speed)

    def _breakout_reset_ball():
        """Glue ball to paddle top-center, clear velocity."""
        nonlocal breakout_ball_x, breakout_ball_y, breakout_ball_vx, breakout_ball_vy, breakout_ball_stuck
        breakout_ball_x = float(breakout_paddle_x + (bo.PADDLE_W - bo.BALL_SIZE) // 2)
        breakout_ball_y = float(bo.PADDLE_Y - bo.BALL_SIZE)
        breakout_ball_vx = 0.0
        breakout_ball_vy = 0.0
        breakout_ball_stuck = True

    def _breakout_launch():
        """Launch ball upward with a slight random horizontal angle."""
        nonlocal breakout_ball_vx, breakout_ball_vy, breakout_ball_stuck
        speed = _breakout_current_speed()
        # Angle in radians measured from straight up: pick within +/- 30 degrees
        import math
        angle = random.uniform(-math.pi / 6, math.pi / 6)
        breakout_ball_vx = speed * math.sin(angle)
        breakout_ball_vy = -speed * math.cos(angle)
        breakout_ball_stuck = False

    def _breakout_new_level(bump_level: bool):
        """Populate bricks, reset ball position. Optionally bump level for speed ramp."""
        nonlocal breakout_bricks, breakout_level
        if bump_level:
            breakout_level += 1
        breakout_bricks = [[1] * bo.BRICK_COLS for _ in range(bo.BRICK_ROWS)]
        _breakout_reset_ball()

    def _breakout_center_paddle():
        nonlocal breakout_paddle_x
        breakout_paddle_x = (bo.PLAY_W - bo.PADDLE_W) // 2

    def _breakout_reflect_off_paddle():
        """Redirect ball based on where it hit the paddle: edges -> steep angles."""
        nonlocal breakout_ball_vx, breakout_ball_vy
        import math
        ball_center = breakout_ball_x + bo.BALL_SIZE / 2.0
        paddle_center = breakout_paddle_x + bo.PADDLE_W / 2.0
        offset = ball_center - paddle_center
        half = bo.PADDLE_W / 2.0
        # Normalize to [-1, 1], then map to max 60-degree angle from vertical
        norm = max(-1.0, min(1.0, offset / half))
        max_angle = math.radians(60)
        angle = norm * max_angle
        speed = math.hypot(breakout_ball_vx, breakout_ball_vy) or _breakout_current_speed()
        breakout_ball_vx = speed * math.sin(angle)
        breakout_ball_vy = -abs(speed * math.cos(angle))

    def _breakout_brick_rect(col: int, row: int) -> Tuple[int, int, int, int]:
        x = col * (bo.BRICK_W + bo.BRICK_GAP_X)
        y = bo.BRICK_TOP + row * (bo.BRICK_H + bo.BRICK_GAP_Y)
        return x, y, bo.BRICK_W, bo.BRICK_H

    def _breakout_all_cleared() -> bool:
        for row in breakout_bricks:
            if any(row):
                return False
        return True

    def _breakout_advance_substep(dx: float, dy: float) -> bool:
        """Move the ball by (dx, dy) with collision resolution.

        Returns False if the ball fell past the paddle (life lost).
        """
        nonlocal breakout_ball_x, breakout_ball_y, breakout_ball_vx, breakout_ball_vy, breakout_score

        prev_x = breakout_ball_x
        prev_y = breakout_ball_y
        new_x = prev_x + dx
        new_y = prev_y + dy

        # --- Wall collisions (left/right/top) ---
        if new_x < 0:
            new_x = -new_x
            breakout_ball_vx = -breakout_ball_vx
        elif new_x > bo.PLAY_W - bo.BALL_SIZE:
            over = new_x - (bo.PLAY_W - bo.BALL_SIZE)
            new_x = (bo.PLAY_W - bo.BALL_SIZE) - over
            breakout_ball_vx = -breakout_ball_vx
        if new_y < 0:
            new_y = -new_y
            breakout_ball_vy = -breakout_ball_vy

        # --- Paddle collision (only when descending) ---
        if breakout_ball_vy > 0:
            ball_bottom_prev = prev_y + bo.BALL_SIZE
            ball_bottom_new = new_y + bo.BALL_SIZE
            paddle_top = bo.PADDLE_Y
            if ball_bottom_prev <= paddle_top <= ball_bottom_new:
                # Check horizontal overlap at the moment of crossing
                if (new_x + bo.BALL_SIZE > breakout_paddle_x) and (new_x < breakout_paddle_x + bo.PADDLE_W):
                    new_y = paddle_top - bo.BALL_SIZE
                    breakout_ball_x = new_x
                    breakout_ball_y = new_y
                    _breakout_reflect_off_paddle()
                    return True

        # --- Ball fell past paddle (bottom of play area) ---
        if new_y >= bo.PLAY_H:
            breakout_ball_x = new_x
            breakout_ball_y = new_y
            return False

        # --- Brick collision ---
        # Find the first brick whose rect overlaps the ball's new AABB.
        ball_rect = (new_x, new_y, bo.BALL_SIZE, bo.BALL_SIZE)
        hit_brick = None
        for row_idx, row in enumerate(breakout_bricks):
            for col_idx, alive in enumerate(row):
                if not alive:
                    continue
                bx, by, bw, bh = _breakout_brick_rect(col_idx, row_idx)
                if (ball_rect[0] < bx + bw and ball_rect[0] + ball_rect[2] > bx and
                        ball_rect[1] < by + bh and ball_rect[1] + ball_rect[3] > by):
                    hit_brick = (col_idx, row_idx, bx, by, bw, bh)
                    break
            if hit_brick is not None:
                break

        if hit_brick is not None:
            col_idx, row_idx, bx, by, bw, bh = hit_brick
            # Decide axis of reflection by comparing prior overlap on each axis
            prev_overlap_x = (prev_x < bx + bw) and (prev_x + bo.BALL_SIZE > bx)
            prev_overlap_y = (prev_y < by + bh) and (prev_y + bo.BALL_SIZE > by)
            if prev_overlap_x and not prev_overlap_y:
                # Came vertically into the brick
                breakout_ball_vy = -breakout_ball_vy
                if dy > 0:
                    new_y = by - bo.BALL_SIZE
                else:
                    new_y = by + bh
            elif prev_overlap_y and not prev_overlap_x:
                breakout_ball_vx = -breakout_ball_vx
                if dx > 0:
                    new_x = bx - bo.BALL_SIZE
                else:
                    new_x = bx + bw
            else:
                # Corner hit: flip both
                breakout_ball_vx = -breakout_ball_vx
                breakout_ball_vy = -breakout_ball_vy
                if dx > 0:
                    new_x = bx - bo.BALL_SIZE
                elif dx < 0:
                    new_x = bx + bw
                if dy > 0:
                    new_y = by - bo.BALL_SIZE
                elif dy < 0:
                    new_y = by + bh
            breakout_bricks[row_idx][col_idx] = 0
            tier_idx = row_idx if row_idx < len(bo.ROW_TIERS) else len(bo.ROW_TIERS) - 1
            breakout_score += bo.ROW_TIERS[tier_idx][1]

        breakout_ball_x = new_x
        breakout_ball_y = new_y
        return True

    def _breakout_step(now: float) -> bool:
        """Advance physics by tick_interval. Returns False if game over (lives exhausted)."""
        nonlocal breakout_last_tick, breakout_lives, display_dirty
        breakout_last_tick = now
        if breakout_ball_stuck:
            # Ball follows paddle while stuck
            _breakout_reset_ball_on_paddle_only()
            display_dirty = True
            return True

        dt = breakout_tick_interval
        total_dx = breakout_ball_vx * dt
        total_dy = breakout_ball_vy * dt
        # Substep to cap motion per substep at 0.5 px
        import math
        max_per_step = 0.5
        dist = math.hypot(total_dx, total_dy)
        substeps = max(1, int(math.ceil(dist / max_per_step)))
        step_dx = total_dx / substeps
        step_dy = total_dy / substeps

        for _ in range(substeps):
            alive = _breakout_advance_substep(step_dx, step_dy)
            if not alive:
                breakout_lives -= 1
                if breakout_lives <= 0:
                    display_dirty = True
                    return False
                _breakout_reset_ball()
                display_dirty = True
                return True

        if _breakout_all_cleared():
            _breakout_new_level(bump_level=True)

        display_dirty = True
        return True

    def _breakout_reset_ball_on_paddle_only():
        """While ball is stuck, keep it glued to the paddle's current position."""
        nonlocal breakout_ball_x, breakout_ball_y
        breakout_ball_x = float(breakout_paddle_x + (bo.PADDLE_W - bo.BALL_SIZE) // 2)
        breakout_ball_y = float(bo.PADDLE_Y - bo.BALL_SIZE)

    def _enter_breakout():
        nonlocal game_mode, breakout_lives, breakout_score, breakout_level
        nonlocal breakout_game_over, breakout_game_over_ts, breakout_game_over_screen
        nonlocal breakout_game_over_sel, breakout_is_new_high_score
        nonlocal breakout_last_tick, display_dirty, cached_high_scores
        game_mode = "breakout"
        breakout_lives = 3
        breakout_score = 0
        breakout_level = 1
        breakout_game_over = False
        breakout_game_over_ts = 0.0
        breakout_game_over_screen = False
        breakout_game_over_sel = 0
        breakout_is_new_high_score = False
        breakout_last_tick = time.time()
        _breakout_center_paddle()
        _breakout_new_level(bump_level=False)
        cached_high_scores = load_high_scores("breakout")
        display_dirty = True

    def _exit_breakout():
        nonlocal game_mode, display_dirty
        game_mode = "pregame"
        display_dirty = True

    def _accept_rotation(direction: int):
        nonlocal current_index, active_screen, departures, departures_all, page_toggle, force_first_page, display_dirty
        current_index = (current_index + (1 if direction > 0 else -1)) % len(screens)
        active_screen = screens[current_index]
        # Blank departures immediately - display will show empty area for half second
        departures = []
        departures_all = []
        page_toggle = 0  # reset to first page on stop change
        force_first_page = True  # ensure the new stop displays page 0 until next rotation
        display_dirty = True
        schedule_fetch(rotate_fetch_delay)

    def _on_rotate(raw_delta: int):  # noqa: D401
        nonlocal last_rotation_accept, last_rotation_action, menu_selection, display_dirty
        nonlocal snake_game_over_sel, last_interaction
        nonlocal breakout_game_over_sel, breakout_paddle_x, breakout_ball_x, breakout_ball_y
        now = time.time()
        # Guard: ignore rotation shortly after a button press (mechanical press can jiggle encoder)
        if (now - last_button_event) < rotate_guard_after_button:
            return
        if now - last_rotation_accept < rotation_min_interval:
            return  # debounce / noise filter
        last_rotation_accept = now
        last_interaction = now  # any real rotation resets the screensaver idle timer
        # Screensaver: any rotation wakes it, regardless of current mode
        if screensaver_active:
            _wake_from_screensaver()
            last_rotation_action = now
            return
        # Breakout live paddle: every detent counts — bypass the action cooldown
        if game_mode == "breakout" and not breakout_game_over:
            direction = 1 if raw_delta > 0 else -1
            max_x = bo.PLAY_W - bo.PADDLE_W
            breakout_paddle_x = max(0, min(max_x, breakout_paddle_x + direction * BREAKOUT_PADDLE_STEP_PX))
            if breakout_ball_stuck:
                breakout_ball_x = float(breakout_paddle_x + (bo.PADDLE_W - bo.BALL_SIZE) // 2)
                breakout_ball_y = float(bo.PADDLE_Y - bo.BALL_SIZE)
            display_dirty = True
            return
        # All other modes: coalesce multiple pulses from one physical twist
        if now - last_rotation_action < rotation_action_cooldown:
            return
        # Menu mode: dial scrolls the game selection
        if game_mode == "menu":
            direction = 1 if raw_delta > 0 else -1
            menu_selection = (menu_selection + direction) % len(GAME_LIST)
            display_dirty = True
            last_rotation_action = now
            return
        # Pregame: ignore rotation
        if game_mode == "pregame":
            return
        # Snake game over screen: dial switches between Play again / Exit
        if game_mode == "snake" and snake_game_over_screen:
            direction = 1 if raw_delta > 0 else -1
            snake_game_over_sel = (snake_game_over_sel + direction) % 2
            display_dirty = True
            last_rotation_action = now
            return
        # Snake mode: dial steers the snake
        if game_mode == "snake":
            direction = 1 if raw_delta > 0 else -1
            _snake_turn(direction)
            last_rotation_action = now
            return
        # Breakout game over screen: dial switches between Play again / Exit
        if game_mode == "breakout" and breakout_game_over_screen:
            direction = 1 if raw_delta > 0 else -1
            breakout_game_over_sel = (breakout_game_over_sel + direction) % 2
            display_dirty = True
            last_rotation_action = now
            return
        _wake_from_screensaver()  # reset inactivity timer
        direction = 1 if raw_delta > 0 else -1
        if getattr(opts, 'encoder_debug', False):
            print(f"[encoder] detent delta={direction} at {now:.3f}", file=sys.stderr)
        # Directional: CW (+1) = next stop, CCW (-1) = previous stop
        _accept_rotation(direction)
        last_rotation_action = now

    def _update_display_rows_from_page():
        nonlocal departures, display_dirty
        effective_page = 0 if force_first_page else page_toggle
        start = effective_page * opts.limit
        end = start + opts.limit
        departures = departures_all[start:end]
        display_dirty = True

    def _toggle_page():
        nonlocal page_toggle, force_first_page
        # Once user toggles, we no longer force page 0
        if force_first_page:
            force_first_page = False
        page_toggle = 0 if page_toggle == 1 else 1
        if getattr(opts, 'encoder_debug', False):
            print(f"[encoder] page toggle -> page {page_toggle}", file=sys.stderr)
        if page_toggle == 1 and len(departures_all) <= opts.limit:
            schedule_fetch(0.0)
        _update_display_rows_from_page()

    def _on_button():
        """Toggle page, wake screensaver, or double-click to enter/exit game menu."""
        nonlocal game_mode, menu_selection, menu_username, page_toggle, last_button_event
        nonlocal telegram_msg, telegram_expires, display_dirty, cached_high_scores
        nonlocal snake_game_over_sel, last_interaction, pregame_game
        nowb = time.time()
        # Noise filter: ignore presses <100ms apart
        if (nowb - last_button_event) < 0.1:
            return
        prev_button_time = last_button_event
        last_button_event = nowb
        last_interaction = nowb  # any real button press resets the screensaver idle timer
        # Dismiss telegram overlay on any button press
        if telegram_msg is not None:
            telegram_msg = None
            telegram_expires = 0.0
            display_dirty = True
            return
        # Screensaver: any button wakes it, regardless of current mode
        if screensaver_active:
            _wake_from_screensaver()
            return
        # Double-click: second press within 100-400ms window
        if (nowb - prev_button_time) < 0.4:
            if game_mode in ("snake", "breakout", "menu", "pregame"):
                # Double-click from any game screen -> back to departures
                if game_mode == "snake":
                    score = len(snake_body) - 3
                    save_high_score("snake", menu_username, score)
                    cached_high_scores = load_high_scores("snake")
                elif game_mode == "breakout":
                    save_high_score("breakout", menu_username, breakout_score)
                    cached_high_scores = load_high_scores("breakout")
                game_mode = "normal"
                menu_username = "User"
                display_dirty = True
                schedule_fetch(0.0)
            else:
                # Enter menu from normal mode
                game_mode = "menu"
                menu_selection = 0
                display_dirty = True
            return
        # Single click in menu: go to pregame screen for the selected game
        if game_mode == "menu":
            selected = GAME_LIST[menu_selection]
            if selected == "Snake":
                cached_high_scores = load_high_scores("snake")
                pregame_game = "Snake"
                game_mode = "pregame"
                display_dirty = True
            elif selected == "Breakout":
                cached_high_scores = load_high_scores("breakout")
                pregame_game = "Breakout"
                game_mode = "pregame"
                display_dirty = True
            return
        # Single click in pregame: start the selected game
        if game_mode == "pregame":
            if pregame_game == "Breakout":
                _enter_breakout()
            else:
                _enter_snake()
            return
        # Single click while snake game over screen active: confirm selection
        if game_mode == "snake" and snake_game_over_screen:
            if snake_game_over_sel == 0:
                _enter_snake()
            else:
                _exit_snake()
            return
        # Single click while snake active: ignored
        if game_mode == "snake":
            return
        # Single click while breakout game over screen active: confirm selection
        if game_mode == "breakout" and breakout_game_over_screen:
            if breakout_game_over_sel == 0:
                _enter_breakout()
            else:
                _exit_breakout()
            return
        # Single click while breakout active: launch the ball if stuck, otherwise ignored
        if game_mode == "breakout":
            if breakout_ball_stuck:
                _breakout_launch()
                display_dirty = True
            return
        _wake_from_screensaver()  # reset inactivity timer
        _toggle_page()

    # Early encoder init (before RGBMatrix) if requested
    if _HAVE_ENCODER and RotaryEncoder is not None and not getattr(opts, 'no_encoder', False) and getattr(opts, 'encoder_early', False):
        if opts.encoder_debug:
            print("[encoder] Early init requested before RGBMatrix", file=sys.stderr)
        try:
            if opts.encoder_delay > 0:
                if opts.encoder_debug:
                    print(f"[encoder] Sleeping {opts.encoder_delay:.3f}s before early init", file=sys.stderr)
                time.sleep(opts.encoder_delay)
            encoder = RotaryEncoder(
                pin_clk=opts.enc_clk,
                pin_dt=opts.enc_dt,
                pin_sw=opts.enc_sw,
                on_rotate=_on_rotate,
                on_button=_on_button,
                force_polling=opts.enc_poll,
                debug=opts.encoder_debug,
                steps_per_detent=max(1, int(getattr(opts, 'enc_steps_per_detent', 2))),
                directionless=False,
            )
            encoder.start()
            encoder_started_early = True
            print("Rotary encoder active (early)", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"[encoder] Early init failed: {e}", file=sys.stderr)

    # Matrix path
    options = RGBMatrixOptions()
    options.rows = opts.rows
    options.cols = opts.cols
    # The rgbmatrix library uses 'hardware_mapping' (older docs sometimes refer to gpio-mapping)
    # Accept --gpio-mapping CLI for user familiarity but map to hardware_mapping attribute.
    try:
        options.hardware_mapping = opts.gpio_mapping  # type: ignore[attr-defined]
    except AttributeError:  # Fallback if attribute name differs in older lib
        # Some very old versions used 'gpio_mapping'; if present, set it dynamically.
        if hasattr(options, 'gpio_mapping'):
            setattr(options, 'gpio_mapping', opts.gpio_mapping)
    options.brightness = opts.brightness
    # Allow user override of PWM / refresh tuning.
    if opts.pwm_lsb_ns is not None:
        options.pwm_lsb_nanoseconds = opts.pwm_lsb_ns
    else:
        options.pwm_lsb_nanoseconds = 130
    if opts.dither_bits is not None:
        options.pwm_dither_bits = opts.dither_bits
    else:
        options.pwm_dither_bits = 1
    # Only set explicit refresh limit if the user asked; letting the library pick often yields less flicker
    if opts.limit_refresh_hz is not None:
        options.limit_refresh_rate_hz = opts.limit_refresh_hz
    # Optional: PWM bit depth (lower can reduce LSB flicker at very low brightness)
    if getattr(opts, 'pwm_bits', None) is not None:
        options.pwm_bits = int(opts.pwm_bits)
    if opts.slowdown_gpio is not None:
        options.gpio_slowdown = opts.slowdown_gpio
    # Only set multiplexing/scan parameters if provided; defaults vary by panel generation
    if getattr(opts, 'multiplexing', None) is not None:
        options.multiplexing = int(opts.multiplexing)
    if getattr(opts, 'scan_mode', None) is not None:
        options.scan_mode = int(opts.scan_mode)
    if getattr(opts, 'row_addr_type', None) is not None:
        options.row_address_type = int(opts.row_addr_type)
    # Panel/controller specific tweaks
    if getattr(opts, 'panel_type', None):
        options.panel_type = opts.panel_type
    if getattr(opts, 'led_rgb_sequence', None):
        options.led_rgb_sequence = opts.led_rgb_sequence
    if getattr(opts, 'disable_hardware_pulsing', False):
        options.disable_hardware_pulsing = True
    options.pixel_mapper_config = ""
    if opts.chain > 1:
        options.chain_length = opts.chain
    if opts.parallel > 1:
        options.parallel = opts.parallel

    matrix = RGBMatrix(options = options)

    renderer = Renderer(opts.cols * opts.chain, opts.rows * opts.parallel)

    # Rotary encoder integration (post-matrix init if not early) ----------------------
    if _HAVE_ENCODER and RotaryEncoder is not None and not getattr(opts, 'no_encoder', False) and not encoder_started_early:
        def _start_encoder():
            nonlocal encoder
            if opts.encoder_debug:
                print("[encoder] Delayed post-matrix init start", file=sys.stderr)
            time.sleep(0.25 if opts.encoder_delay is None else opts.encoder_delay)
            try:
                # Many pins are used by the RGB matrix HAT. Avoid common conflicts.
                conflict_pins = {4,5,6,12,13,16,17,18,19,20,21,22,23,24,25,26,27}
                user_pins = {opts.enc_clk, opts.enc_dt, opts.enc_sw}
                if conflict_pins & user_pins:
                    print(f"[encoder] Warning: chosen pins {user_pins & conflict_pins} likely conflict with the RGB matrix HAT. Try different GPIOs (e.g., 7, 14, 15) and reboot.", file=sys.stderr)
                # Warn about UART pins - GPIO14/15 are TXD/RXD and may toggle due to serial console
                uart_pins = {14, 15}
                if uart_pins & user_pins:
                    print("[encoder] Warning: using UART pins (GPIO14/15). They can show activity/noise unless serial console/UART is disabled. Prefer other GPIOs for CLK/DT or disable serial.", file=sys.stderr)
                encoder = RotaryEncoder(
                    pin_clk=opts.enc_clk,
                    pin_dt=opts.enc_dt,
                    pin_sw=opts.enc_sw,
                    on_rotate=_on_rotate,  # type: ignore[operator]
                    on_button=_on_button,
                    force_polling=opts.enc_poll,
                    debug=opts.encoder_debug,
                    steps_per_detent=max(1, int(getattr(opts, 'enc_steps_per_detent', 2))),
                    directionless=False,
                )
                encoder.start()
                print("Rotary encoder active (events or polling)", file=sys.stderr)
            except RuntimeError as e:
                print(f"Rotary encoder event init failed ({e}); continuing without encoder.", file=sys.stderr)
                encoder = None
            except Exception as e:  # noqa: BLE001
                print(f"Failed to init rotary encoder: {e}", file=sys.stderr)
                encoder = None
        threading.Thread(target=_start_encoder, daemon=True).start()

    # Telegram bot poller
    _telegram_token = getattr(opts, 'telegram_token', '')
    if _telegram_token:
        threading.Thread(
            target=_start_telegram_poller,
            args=(_telegram_token, getattr(opts, 'telegram_chat_id', ''), telegram_queue),
            daemon=True,
        ).start()
        print('[telegram] bot poller started', file=sys.stderr)

    # Fetch helpers
    def fetch_rows(screen: Dict[str, Any], timeout: float = 10.0) -> List[Dict[str, Any]]:
        # Increase fetch size to ensure enough items for two pages even after filtering
        base_fetch = max(opts.limit * 6, 40)
        fetch_size = max(base_fetch, 60) if screen.get('dest_filter') else base_fetch
        # Use a short connect timeout and a moderate read timeout to avoid long stalls on boot
        connect_timeout = min(1.0, max(0.2, timeout / 3.0))
        read_timeout = max(2.5, timeout)
        rows = fd.fetch_stationboard(
            screen['origin'],
            fetch_size,
            transportations=screen.get('transportations'),
            timeout=(connect_timeout, read_timeout),
        )
        dest_filter = screen.get('dest_filter')
        if dest_filter:
            nf = fd._normalize(dest_filter)
            filtered: List[Dict[str, Any]] = []
            for r in rows:
                if (r.get('category') or '').upper() in {'T','TRAM'}:
                    continue
                if fd._normalize(r.get('dest') or '') != nf:
                    continue
                # Override destination text to show platform label if available
                plat = (r.get('plat') or '').strip()
                if plat:
                    r = dict(r)
                    r['_dest_override'] = f"Gleis {plat}"
                filtered.append(r)
            rows = filtered
        # Apply global CLI destination filter as an additional constraint if provided
        if getattr(opts, 'dest', ''):
            nf_cli = fd._normalize(opts.dest)
            rows = [r for r in rows if fd._normalize(r.get('dest') or '') == nf_cli]
        # Sort strictly by minutes-to-departure for stable ordering across pages
        rows.sort(key=lambda r: r.get('mins', 0))
        # Return enough rows for two pages (and a small safety buffer)
        return rows[: max(int(opts.limit * 2.5), 10)]

    def fetch_weather_for_screen(screen: Dict[str, Any], timeout: float = 6.0) -> WeatherData:
        return fetch_weather(float(screen['lat']), float(screen['lon']), timeout=timeout)

    # Detect whether system time is synchronized; in 'auto' mode trust RTC/plausible clock
    _sync_cached: Optional[bool] = None
    _sync_ts: float = 0.0
    _sync_locked_true: bool = False  # once true, don't spawn subprocesses again
    _sync_min_interval: float = 15.0  # seconds between checks while not yet true

    ntp_wait_mode = getattr(opts, 'ntp_wait_mode', 'auto')  # 'auto' | 'strict' | 'skip'

    def _rtc_present() -> bool:
        try:
            return os.path.exists('/sys/class/rtc/rtc0')
        except Exception:
            return False

    def _time_looks_sane() -> bool:
        try:
            year = datetime.now().year
            return year >= 2023
        except Exception:
            return False

    def time_is_synchronized() -> bool:
        nonlocal _sync_cached, _sync_ts, _sync_locked_true
        # Mode shortcuts
        if ntp_wait_mode == 'skip':
            return True
        if ntp_wait_mode == 'auto':
            # If RTC present or clock looks sane, treat as synced immediately
            if _rtc_present() or _time_looks_sane():
                _sync_locked_true = True
                _sync_cached = True
                _sync_ts = time.time()
                return True
        # 'strict' or didn't pass auto heuristics: actually query NTP status
        now = time.time()
        if _sync_locked_true:
            return True
        if _sync_cached is not None and (now - _sync_ts) < _sync_min_interval:
            return _sync_cached
        result = False
        try:
            out = subprocess.check_output(
                ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1.2,
            ).strip().lower()
            if out in {"yes", "true", "1"}:
                result = True
        except Exception:
            # Fallback heuristic
            result = _time_looks_sane()
        _sync_cached = result
        _sync_ts = now
        if result:
            _sync_locked_true = True
        return result

    # Compute next :00 or :30 boundary timestamp (epoch seconds)
    def next_half_minute_boundary(ts: float) -> float:
        dt = datetime.fromtimestamp(ts)
        sec = dt.second
        if sec < 30:
            target_sec = 30
            target_min = dt.minute
            target_hr = dt.hour
        else:
            target_sec = 0
            # advance minute
            target_min = (dt.minute + 1) % 60
            target_hr = dt.hour + 1 if target_min == 0 else dt.hour
        future = dt.replace(hour=target_hr % 24, minute=target_min, second=target_sec, microsecond=0)
        # If hour rolled beyond day, let datetime handle day rollover by adding difference
        return future.timestamp()

    # --- Initial fetch scheduling --------------------------------------------------
    schedule_fetch(0.0)  # fetch immediately on start
    next_periodic_refresh = time.time() + fetch_interval
    process_start_time = time.time()
    fetch_backoff = 1.0  # start very small on boot; ramp up with failures
    last_time_sync_state = time_is_synchronized()
    # Background fetch control
    fetch_in_flight = False
    current_fetch_timeout = 2.5  # short initial timeout to avoid long stalls at boot

    def start_fetch():
        nonlocal fetch_in_flight, departures, last_fetch_time, fetch_backoff, next_periodic_refresh, current_fetch_timeout
        if fetch_in_flight:
            return
        # Snapshot the active screen at start to fetch a consistent target
        screen_snapshot = dict(active_screen)
        fetch_in_flight = True
        def _worker():
            nonlocal fetch_in_flight, departures, last_fetch_time, fetch_backoff, next_periodic_refresh, current_fetch_timeout, display_dirty
            try:
                if screen_snapshot.get('type') == 'weather':
                    # Fetch and cache weather
                    key = f"{screen_snapshot.get('city','')}"
                    try:
                        w_new = fetch_weather_for_screen(screen_snapshot)
                        weather_cache[key] = {'data': w_new, 'ts': time.time()}
                        display_dirty = True
                    except Exception as we:  # noqa: BLE001
                        print(f"[weather] fetch error for {key}: {we}", file=sys.stderr)
                    # Keep departures untouched
                    last_fetch_time = time.time()
                    fetch_backoff = 5.0
                else:
                    rows_local = fetch_rows(screen_snapshot, timeout=current_fetch_timeout)
                    # Only apply if still on the same screen
                    if screen_snapshot is active_screen or screen_snapshot.get('header') == active_screen.get('header'):
                        departures_all[:] = rows_local
                        _update_display_rows_from_page()
                        last_fetch_time = time.time()
                        fetch_backoff = 5.0
                        next_periodic_refresh = last_fetch_time + fetch_interval
                        # Gradually increase timeout after a success (cap at 10s)
                        current_fetch_timeout = min(10.0, max(current_fetch_timeout, 3.0))
            except Exception as e:  # noqa: BLE001
                print(f"[fetch] Error fetching departures for '{screen_snapshot.get('header','?')}': {e}", file=sys.stderr)
                # Quick retry with exponential backoff (cap 60s); also slightly increase timeout
                elapsed = time.time() - process_start_time
                # During the first 20s after boot, keep retries snappy (<= 2s)
                if elapsed < 20.0:
                    fetch_backoff = min(2.0, max(0.5, fetch_backoff * 1.5))
                else:
                    fetch_backoff = min(60.0, max(2.0, fetch_backoff * 1.5))
                current_fetch_timeout = min(10.0, current_fetch_timeout + 1.0)
                schedule_fetch(fetch_backoff)
            finally:
                fetch_in_flight = False
        threading.Thread(target=_worker, daemon=True).start()

    # Single off-screen canvas reused (fix for CreateFrameCanvas spam)
    offscreen = matrix.CreateFrameCanvas()
    # On very early boot, show real clock immediately in auto/skip modes; placeholder only in strict mode without sync
    initial_now = None if time_is_synchronized() else ("--:--" if ntp_wait_mode == 'strict' else None)
    offscreen = draw_frame(offscreen, matrix, renderer, departures, active_screen['header'], active_screen['city_ref'], now_text=initial_now)  # blank first frame, clears stale panel content
    # Kick off the first fetch immediately if clock is usable
    if time_is_synchronized():
        start_fetch()

    running = True
    def _sig_handler(signum, frame):  # noqa: D401, ANN001
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    try:
        # Dirty-flag rendering: only redraw when content actually changes.
        # The rpi-rgb-led-matrix library continuously refreshes the last-swapped
        # buffer via DMA, so skipping redraws does NOT make the panel go dark.
        poll_interval = 0.05  # 50ms poll - responsive enough for encoder + clock
        while running:
            now = time.time()
            # --- Telegram queue drain (needed by both menu and normal modes) ---
            try:
                while True:
                    new_msg = telegram_queue.get_nowait()
                    if game_mode in ("menu", "pregame"):
                        # Capture username from telegram message
                        menu_username = new_msg.strip()[:6] or "User"
                        display_dirty = True
                    else:
                        telegram_msg = new_msg
                        telegram_expires = now + 30.0
                        # Wake screensaver so the message is visible
                        if screensaver_active:
                            screensaver_active = False
                        display_dirty = True
            except queue.Empty:
                pass
            # --- Screensaver activation check (runs from any mode) ---
            if not screensaver_active and screensaver_timeout > 0 and (now - last_interaction) >= screensaver_timeout:
                screensaver_active = True
                display_dirty = True
                last_rendered_minute = ''  # force redraw
                screensaver_pos = screensaver_random_pos(renderer, datetime.now().strftime('%H:%M'))
                print(f"[screensaver] activated (dim={screensaver_brightness})", file=sys.stderr)
            # --- Screensaver mode: show the time at a drifting random position ---
            if screensaver_active:
                now_txt_override = None if time_is_synchronized() else ("--:--" if ntp_wait_mode == 'strict' else None)
                current_minute = now_txt_override or datetime.now().strftime('%H:%M')
                if current_minute != last_rendered_minute:
                    display_dirty = True
                    screensaver_pos = screensaver_random_pos(renderer, current_minute)
                if display_dirty:
                    try:
                        offscreen = draw_screensaver_frame(offscreen, matrix, renderer, now_text=now_txt_override, pos=screensaver_pos, dim=screensaver_brightness)
                        print(f"[screensaver] drew {current_minute} at {screensaver_pos}", file=sys.stderr)
                    except Exception as _ss_err:  # noqa: BLE001
                        import traceback
                        print(f"[screensaver] draw error: {_ss_err}", file=sys.stderr)
                        traceback.print_exc(file=sys.stderr)
                    last_rendered_minute = current_minute
                    display_dirty = False
                time.sleep(poll_interval)
                continue
            # --- Snake game mode ---
            if game_mode == "snake":
                if snake_game_over:
                    if snake_game_over_screen:
                        # Interactive game over menu — wait for player input
                        if display_dirty:
                            score = len(snake_body) - 3
                            offscreen = draw_game_over_frame(offscreen, matrix, renderer,
                                score, snake_game_over_sel, snake_is_new_high_score)
                            display_dirty = False
                    else:
                        # Red flash phase: show for 0.5s then transition to game over menu
                        if now - snake_game_over_ts >= 0.5:
                            snake_game_over_screen = True
                            display_dirty = True
                    time.sleep(poll_interval)
                    continue
                if now >= snake_last_move + snake_move_interval:
                    # Deterministic timing: advance by interval (avoids drift accumulation)
                    if snake_last_move < now - snake_move_interval:
                        snake_last_move = now - snake_move_interval
                    snake_last_move += snake_move_interval
                    alive = _snake_step()
                    if not alive:
                        score = len(snake_body) - 3
                        prev_best = cached_high_scores[0]['score'] if cached_high_scores else -1
                        snake_is_new_high_score = score > prev_best
                        save_high_score("snake", menu_username, score)
                        cached_high_scores = load_high_scores("snake")
                        snake_game_over = True
                        snake_game_over_ts = now
                        snake_game_over_screen = False
                        offscreen = draw_snake_frame(offscreen, matrix, renderer,
                            snake_body, snake_food, game_over=True,
                            game_x_offset=SNAKE_GAME_X_OFFSET, game_cols=SNAKE_GAME_COLS,
                            username=menu_username, score=score,
                            high_scores=cached_high_scores)
                        time.sleep(poll_interval)
                        continue
                if display_dirty:
                    offscreen = draw_snake_frame(offscreen, matrix, renderer,
                        snake_body, snake_food,
                        game_x_offset=SNAKE_GAME_X_OFFSET, game_cols=SNAKE_GAME_COLS,
                        username=menu_username, score=len(snake_body) - 3,
                        high_scores=cached_high_scores)
                    display_dirty = False
                # Sleep only until next move is due (not a fixed poll_interval),
                # so move timing stays accurate at high speeds
                time_until_move = max(0.005, (snake_last_move + snake_move_interval) - time.time())
                time.sleep(min(time_until_move, poll_interval))
                continue
            # --- Game menu mode ---
            if game_mode == "menu":
                if display_dirty:
                    offscreen = draw_menu_frame(offscreen, matrix, renderer,
                        menu_username, GAME_LIST, menu_selection)
                    display_dirty = False
                time.sleep(poll_interval)
                continue
            # --- Pre-game screen (high scores + Play) ---
            if game_mode == "pregame":
                if display_dirty:
                    if pregame_game == "Breakout":
                        offscreen = draw_breakout_pregame_frame(offscreen, matrix, renderer,
                            cached_high_scores)
                    else:
                        offscreen = draw_pregame_frame(offscreen, matrix, renderer,
                            cached_high_scores)
                    display_dirty = False
                time.sleep(poll_interval)
                continue
            # --- Breakout game mode ---
            if game_mode == "breakout":
                if breakout_game_over:
                    if breakout_game_over_screen:
                        if display_dirty:
                            offscreen = draw_breakout_game_over_frame(offscreen, matrix, renderer,
                                breakout_score, breakout_game_over_sel, breakout_is_new_high_score)
                            display_dirty = False
                    else:
                        # Red flash phase: show for 0.5s then transition to game over menu
                        if now - breakout_game_over_ts >= 0.5:
                            breakout_game_over_screen = True
                            display_dirty = True
                    time.sleep(poll_interval)
                    continue
                # Physics tick
                if now >= breakout_last_tick + breakout_tick_interval:
                    alive = _breakout_step(now)
                    if not alive:
                        prev_best = cached_high_scores[0]['score'] if cached_high_scores else -1
                        breakout_is_new_high_score = breakout_score > prev_best
                        save_high_score("breakout", menu_username, breakout_score)
                        cached_high_scores = load_high_scores("breakout")
                        breakout_game_over = True
                        breakout_game_over_ts = now
                        breakout_game_over_screen = False
                        offscreen = draw_breakout_frame(offscreen, matrix, renderer,
                            (breakout_ball_x, breakout_ball_y), breakout_paddle_x,
                            breakout_bricks, lives=breakout_lives, score=breakout_score,
                            username=menu_username, high_scores=cached_high_scores,
                            game_over=True)
                        time.sleep(poll_interval)
                        continue
                if display_dirty:
                    offscreen = draw_breakout_frame(offscreen, matrix, renderer,
                        (breakout_ball_x, breakout_ball_y), breakout_paddle_x,
                        breakout_bricks, lives=breakout_lives, score=breakout_score,
                        username=menu_username, high_scores=cached_high_scores)
                    display_dirty = False
                time_until_tick = max(0.005, (breakout_last_tick + breakout_tick_interval) - time.time())
                time.sleep(min(time_until_tick, poll_interval))
                continue
            # --- Telegram message overlay ---
            # Expire the overlay once 30 seconds are up
            if telegram_msg is not None and now >= telegram_expires:
                telegram_msg = None
                display_dirty = True
            # While a telegram message is active, show only that
            if telegram_msg is not None:
                if display_dirty:
                    offscreen = draw_telegram_frame(offscreen, matrix, renderer, telegram_msg)
                    display_dirty = False
                time.sleep(poll_interval)
                continue

            # --- Normal mode ---
            # Fetch if scheduled
            if next_scheduled_fetch and now >= next_scheduled_fetch:
                if not time_is_synchronized():
                    schedule_fetch(min(5.0, fetch_backoff))
                    last_time_sync_state = False
                    next_scheduled_fetch = 0.0
                else:
                    start_fetch()
                    next_scheduled_fetch = 0.0
            # Periodic refresh if stale (even without rotation)
            if departures and now >= next_periodic_refresh and not fetch_in_flight:
                schedule_fetch(0.0)
                next_periodic_refresh = now + fetch_interval
            # Check if the clock minute changed (triggers redraw for header time)
            now_txt_override = None if time_is_synchronized() else ("--:--" if ntp_wait_mode == 'strict' else None)
            current_minute = now_txt_override or datetime.now().strftime('%H:%M')
            if current_minute != last_rendered_minute:
                display_dirty = True
            # Only redraw when something changed
            if display_dirty:
                if active_screen.get('type') == 'weather':
                    key = f"{active_screen['city']}"
                    w_entry = weather_cache.get(key)
                    w_data = w_entry['data'] if (w_entry and (now - w_entry['ts'] < 600)) else None
                    if w_data is None and not fetch_in_flight and time_is_synchronized():
                        try:
                            w_new = fetch_weather_for_screen(active_screen)
                            weather_cache[key] = {'data': w_new, 'ts': time.time()}
                            w_data = w_new
                        except Exception as e:  # noqa: BLE001
                            print(f"[weather] fetch error for {key}: {e}", file=sys.stderr)
                    offscreen = draw_weather_frame(offscreen, matrix, renderer, active_screen['header'], w_data, now_text=now_txt_override)
                else:
                    offscreen = draw_frame(offscreen, matrix, renderer, departures, active_screen['header'], active_screen['city_ref'], now_text=now_txt_override)
                last_rendered_minute = current_minute
                display_dirty = False
            # If time just became synchronized and we have no departures yet, force a fetch asap
            if (now_txt_override is None) and not departures and not next_scheduled_fetch and not fetch_in_flight:
                schedule_fetch(0.0)
            # Sleep until the next interesting event
            t_until_fetch = max(0.0, (next_scheduled_fetch - time.time()) if next_scheduled_fetch else 1.0)
            time.sleep(min(t_until_fetch, poll_interval))
    finally:
        if encoder:
            try:
                encoder.stop()
            except Exception:  # noqa: BLE001
                pass


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Show departures on RGB LED matrix')
    p.add_argument('--stop', default=fd.STOP, help='Origin stop name')
    p.add_argument('--dest', default='', help='Optional exact destination filter')
    p.add_argument('--limit', type=int, default=fd.LIMIT, help='Number of departures to display')
    p.add_argument('--refresh', type=int, default=30, help='Refresh interval seconds')
    p.add_argument('--brightness', type=int, default=40, help='Panel brightness (0-100)')
    p.add_argument('--rows', type=int, default=DEFAULT_ROWS, help='Panel rows (height)')
    p.add_argument('--cols', type=int, default=DEFAULT_COLS, help='Panel columns (width)')
    p.add_argument('--gpio-mapping', default='adafruit-hat', help='GPIO mapping (e.g. adafruit-hat)')
    p.add_argument('--chain', type=int, default=1, help='Number of daisy-chained panels')
    p.add_argument('--parallel', type=int, default=1, help='Parallel chains')
    p.add_argument('--all', action='store_true', help='Include all transport types (ignore default tram/train)')
    # Advanced tuning flags (optional)
    p.add_argument('--slowdown-gpio', type=int, choices=[0,1,2,3,4], default=None,
                   help='GPIO slowdown (increase if you see flicker/noise)')
    p.add_argument('--pwm-lsb-ns', type=int, default=None,
                   help='Override pwm_lsb_nanoseconds (timing of LSB pulse)')
    p.add_argument('--limit-refresh-hz', type=int, default=None,
                   help='Hard limit on refresh rate Hz (lower to reduce CPU/flicker)')
    p.add_argument('--dither-bits', type=int, default=None,
                   help='Override pwm dither bits (0 to disable, higher = smoother dims)')
    p.add_argument('--pwm-bits', type=int, default=None,
                   help='PWM bit depth (default panel-specific). Try 8-11 to reduce low-brightness flicker')
    p.add_argument('--multiplexing', type=int, default=None,
                   help='Forced multiplexing scheme (e.g., 0/8/16/32/64). Only set if you know your panel spec')
    p.add_argument('--scan-mode', type=int, choices=[0,1], default=None,
                   help='Scan mode: 0 = progressive, 1 = interlaced. Some panels flicker less with 1')
    p.add_argument('--row-addr-type', type=int, choices=[0,1,2,3,4], default=None,
                   help='Row address type (A/B/C/... lines). Matches panel controller generation')
    p.add_argument('--panel-type', default=None,
                   help='Panel type hint (e.g., FM6126A, ICN2038S). Enables panel-specific init sequences')
    p.add_argument('--led-rgb-sequence', default=None,
                   help='Override LED color sequence (e.g., RGB, RBG, GBR). Can affect ghosting/flicker')
    p.add_argument('--disable-hardware-pulsing', action='store_true',
                   help='Disable HAT hardware pulsing; may help on some clones at the cost of CPU')
    # Rotary encoder options
    p.add_argument('--no-encoder', action='store_true', help='Disable rotary encoder even if library present')
    p.add_argument('--enc-clk', type=int, default=10, help='Rotary encoder CLK (A) GPIO (BCM numbering)')
    p.add_argument('--enc-dt', type=int, default=9, help='Rotary encoder DT (B) GPIO (BCM numbering)')
    p.add_argument('--enc-sw', type=int, default=11, help='Rotary encoder switch GPIO (BCM numbering)')
    p.add_argument('--enc-poll', action='store_true', help='Force polling mode instead of interrupt events')
    p.add_argument('--encoder-early', action='store_true', help='Initialize rotary encoder before RGBMatrix (try if normal init fails)')
    p.add_argument('--encoder-delay', type=float, default=0.0, help='Delay seconds before encoder init (early or delayed)')
    p.add_argument('--encoder-debug', action='store_true', help='Verbose encoder debug messages')
    p.add_argument('--rotate-fetch-delay', type=float, default=0.5,
                   help='Delay seconds after rotation before fetching new departures (immediate header update)')
    p.add_argument('--rotate-min-interval', type=float, default=0.08,
                   help='Minimum seconds between accepted detents (debounce at app level)')
    p.add_argument('--enc-steps-per-detent', type=int, default=1,
                   help='Steps per detent: 1 for directionless (CLK only), 2/4 if using full quadrature')
    p.add_argument('--ntp-wait-mode', choices=['auto','strict','skip'], default='auto',
                   help="Time sync strategy at boot: 'auto' (default) trusts RTC or plausible clock, 'strict' waits for NTP, 'skip' never waits")
    # Screensaver options
    p.add_argument('--screensaver-timeout', type=int, default=600,
                   help='Seconds of inactivity before screensaver activates (0 to disable, default 600 = 10min)')
    p.add_argument('--screensaver-brightness', type=int, default=15,
                   help='Panel brightness during screensaver (0-100, default 15)')
    # Telegram bot options
    p.add_argument('--telegram-token', default='',
                   help='Telegram Bot API token (enables message overlay feature)')
    p.add_argument('--telegram-chat-id', default='',
                   help='Comma-separated Telegram chat IDs to accept messages from (leave empty to allow all)')
    return p.parse_args(argv)


def _load_dotenv(path: str = '.env') -> Dict[str, str]:
    """Parse a simple KEY=VALUE .env file, ignoring comments and blank lines."""
    env: Dict[str, str] = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, _, value = line.partition('=')
                env[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover
    opts = parse_args(argv)
    # Fall back to .env for Telegram credentials if not supplied via CLI
    env = _load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
    if not opts.telegram_token and env.get('TELEGRAM_TOKEN'):
        opts.telegram_token = env['TELEGRAM_TOKEN']
    if not opts.telegram_chat_id and env.get('TELEGRAM_CHAT_ID'):
        opts.telegram_chat_id = env['TELEGRAM_CHAT_ID']
    run_loop(opts)
    return 0
