"""按住拖拽陪玩模式的纯逻辑状态控制器。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import hypot

from petnest.models.pet_package import (
    HoldPlayDefinition,
    HoldPlayDirection,
    HoldPlayTargetDefinition,
)


class HoldPlayPhase(StrEnum):
    INACTIVE = "inactive"
    READY = "ready"
    ATTACKING = "attacking"
    COOLDOWN = "cooldown"
    PENDING_DROP = "pending_drop"
    SUSPENDED = "suspended"


@dataclass(frozen=True, slots=True)
class HoldPlayUpdate:
    phase: HoldPlayPhase
    action: str | None = None
    deadline_ms: int | None = None
    finish_drop: bool = False


class HoldPlayController:
    """根据目标、时间和释放位置推进一次按住陪玩会话。"""

    jitter_radius = 18

    def __init__(self, definition: HoldPlayDefinition) -> None:
        self.definition = definition
        self.phase = HoldPlayPhase.INACTIVE
        self.candidate_target: tuple[int, int] | None = None
        self.current_direction: HoldPlayDirection | None = None
        self._stable_since_ms: int | None = None
        self._cooldown_until_ms: int | None = None
        self._last_attack_target: tuple[int, int] | None = None
        self._attack_target: tuple[int, int] | None = None
        self._attack_definition: HoldPlayTargetDefinition | None = None
        self._release_after_attack = False

    def enter(self, *, now_ms: int) -> HoldPlayUpdate:
        del now_ms
        self._reset_transient()
        self.phase = HoldPlayPhase.READY
        return HoldPlayUpdate(self.phase, action=self.definition.ready_action)

    def resolve_direction(self, point: tuple[int, int]) -> HoldPlayDirection:
        dx = point[0] - self.definition.attack_origin[0]
        dy = point[1] - self.definition.attack_origin[1]
        if dy < -60:
            return "up_left" if dx < 0 else "up_right"
        if abs(dx) <= 60:
            return "center"
        return "left" if dx < 0 else "right"

    def move(self, point: tuple[int, int], *, now_ms: int) -> HoldPlayUpdate:
        if self.phase in {HoldPlayPhase.INACTIVE, HoldPlayPhase.SUSPENDED}:
            return HoldPlayUpdate(self.phase)
        if self.phase in {HoldPlayPhase.ATTACKING, HoldPlayPhase.PENDING_DROP}:
            self.candidate_target = point
            return HoldPlayUpdate(self.phase)
        if self.phase is HoldPlayPhase.COOLDOWN:
            self.candidate_target = point
            return HoldPlayUpdate(self.phase, deadline_ms=self._cooldown_until_ms)

        if self._last_attack_target is not None and self._distance(
            point, self._last_attack_target
        ) < self.definition.rearm_distance:
            self.candidate_target = point
            self._stable_since_ms = None
            return HoldPlayUpdate(self.phase)

        if self.candidate_target is None or self._distance(
            point, self.candidate_target
        ) > self.jitter_radius:
            self.candidate_target = point
            self._stable_since_ms = now_ms
        deadline = (
            self._stable_since_ms + self.definition.settle_ms
            if self._stable_since_ms is not None
            else None
        )
        return HoldPlayUpdate(self.phase, deadline_ms=deadline)

    def tick(self, *, now_ms: int) -> HoldPlayUpdate:
        if self.phase is HoldPlayPhase.COOLDOWN:
            if self._cooldown_until_ms is not None and now_ms < self._cooldown_until_ms:
                return HoldPlayUpdate(self.phase, deadline_ms=self._cooldown_until_ms)
            self.phase = HoldPlayPhase.READY
            self._stable_since_ms = None
            if (
                self.candidate_target is not None
                and self._last_attack_target is not None
                and self._distance(self.candidate_target, self._last_attack_target)
                >= self.definition.rearm_distance
            ):
                self._stable_since_ms = now_ms
                return HoldPlayUpdate(
                    self.phase,
                    deadline_ms=now_ms + self.definition.settle_ms,
                )
            return HoldPlayUpdate(self.phase)

        if (
            self.phase is not HoldPlayPhase.READY
            or self.candidate_target is None
            or self._stable_since_ms is None
        ):
            return HoldPlayUpdate(self.phase)
        deadline = self._stable_since_ms + self.definition.settle_ms
        if now_ms < deadline:
            return HoldPlayUpdate(self.phase, deadline_ms=deadline)

        direction = self.resolve_direction(self.candidate_target)
        target = self._target_for(direction)
        self.phase = HoldPlayPhase.ATTACKING
        self.current_direction = direction
        self._attack_target = self.candidate_target
        self._attack_definition = target
        self._stable_since_ms = None
        return HoldPlayUpdate(self.phase, action=target.action)

    def attack_completed(self, *, now_ms: int) -> HoldPlayUpdate:
        if self.phase is HoldPlayPhase.PENDING_DROP:
            self._set_inactive()
            return HoldPlayUpdate(self.phase, finish_drop=True)
        if self.phase is not HoldPlayPhase.ATTACKING:
            return HoldPlayUpdate(self.phase)
        if self._release_after_attack:
            self._set_inactive()
            return HoldPlayUpdate(self.phase)

        return_action = (
            self._attack_definition.return_action
            if self._attack_definition is not None
            else None
        )
        self._last_attack_target = self._attack_target
        self._attack_target = None
        self._attack_definition = None
        self.current_direction = None
        self.phase = HoldPlayPhase.COOLDOWN
        self._cooldown_until_ms = now_ms + self.definition.cooldown_ms
        return HoldPlayUpdate(
            self.phase,
            action=return_action or self.definition.ready_action,
            deadline_ms=self._cooldown_until_ms,
        )

    def leave(self) -> HoldPlayUpdate:
        self.phase = HoldPlayPhase.SUSPENDED
        self._reset_transient()
        return HoldPlayUpdate(self.phase)

    def release_inside(self, *, has_drop_action: bool) -> HoldPlayUpdate:
        if self.phase is HoldPlayPhase.ATTACKING:
            if has_drop_action:
                self.phase = HoldPlayPhase.PENDING_DROP
            else:
                self._release_after_attack = True
            return HoldPlayUpdate(self.phase)
        if self.phase is HoldPlayPhase.PENDING_DROP:
            return HoldPlayUpdate(self.phase)
        self._set_inactive()
        return HoldPlayUpdate(self.phase, finish_drop=has_drop_action)

    def release_outside(self) -> HoldPlayUpdate:
        self._set_inactive()
        return HoldPlayUpdate(self.phase)

    def cancel(self) -> HoldPlayUpdate:
        self._set_inactive()
        return HoldPlayUpdate(self.phase)

    def correction_for_frame(self, frame_number: int) -> tuple[int, int]:
        target = self._attack_definition
        point = self._attack_target
        if target is None or point is None:
            return 0, 0
        distance = abs(frame_number - target.contact_frame)
        if distance > 2:
            return 0, 0
        weight = (3 - distance) / 3
        dx = max(-target.max_correction[0], min(target.max_correction[0], point[0] - target.contact_point[0]))
        dy = max(-target.max_correction[1], min(target.max_correction[1], point[1] - target.contact_point[1]))
        return round(dx * weight), round(dy * weight)

    def _target_for(self, direction: HoldPlayDirection) -> HoldPlayTargetDefinition:
        targets = self.definition.targets
        center = targets["center"]
        if direction == "up_left":
            return targets.get("up_left", targets.get("left", center))
        if direction == "up_right":
            return targets.get("up_right", targets.get("right", center))
        return targets.get(direction, center)

    @staticmethod
    def _distance(first: tuple[int, int], second: tuple[int, int]) -> float:
        return hypot(first[0] - second[0], first[1] - second[1])

    def _reset_transient(self) -> None:
        self.candidate_target = None
        self.current_direction = None
        self._stable_since_ms = None
        self._cooldown_until_ms = None
        self._attack_target = None
        self._attack_definition = None
        self._release_after_attack = False
        self._last_attack_target = None

    def _set_inactive(self) -> None:
        self.phase = HoldPlayPhase.INACTIVE
        self._reset_transient()


__all__ = ["HoldPlayController", "HoldPlayPhase", "HoldPlayUpdate"]
