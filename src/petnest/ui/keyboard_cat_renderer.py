"""One production renderer for every platform: approved geometry, shared motion.

Global input is handled by platform adapters; this module has no OS dispatch.
"""

from time import monotonic

from petnest.core.cat_motion import CatMotion, Point
from petnest.core.keyboard_cat import CatState, cat_preferences
from petnest.ui.cat_scene import CatScene


def render_cat(
    state: CatState, preferences: object, *, cursor=None, action="idle", dt=1 / 30
):
    options = cat_preferences(preferences)
    if state.motion is None:
        state.motion = CatMotion()
    motion = state.motion
    for key, down in state.events:
        motion.key_event(key, down)
    state.events.clear()
    # Recover releases and presses missed while a paused window's bounded queue filled.
    for key in set(motion.keys) - state.keys:
        motion.key_event(key, False)
    for key in sorted(state.keys - set(motion.keys) - {"MouseLeft", "MouseRight"}):
        motion.key_event(key, True)
    for key, held in (
        ("MouseLeft", motion.leftMouse),
        ("MouseRight", motion.rightMouse),
    ):
        if held != (key in state.keys):
            motion.key_event(key, key in state.keys)
    point = Point(cursor.x(), cursor.y()) if cursor is not None else None
    if state.keys or (point is not None and point != motion.previousCursor):
        state.last_activity = monotonic()
    age = max(0, monotonic() - state.last_activity)
    idle = (
        max(0, age - options["sleep_seconds"] + 45) if options["sleep_enabled"] else 0
    )
    if action == "sleep" and options["sleep_enabled"]:
        idle = max(idle, 80)
    motion.step(
        dt,
        point,
        look=options["look"],
        petting=options["petting"],
        idle=idle,
    )
    return CatScene(options).draw(motion)
