"""Pure state for verified LAN endpoints and bounded candidate probing."""

from __future__ import annotations

from dataclasses import dataclass

from petnest.core.lan_interaction import LAN_INTERACTION_PORT
from petnest.core.lan_peer_discovery_protocol import (
    PeerEndpointRecord,
    _identity,
    _private_ipv4,
)

DIRECT_ENDPOINT_TTL_SECONDS = 24.0
ASSISTED_ENDPOINT_TTL_SECONDS = 90.0
CANDIDATE_TTL_SECONDS = 60.0
NEGATIVE_CACHE_TTL_SECONDS = 3_600.0
DEFAULT_NEGATIVE_CACHE_MAXIMUM = 512


@dataclass(frozen=True, slots=True)
class CandidateKey:
    device_id: str
    ip_address: str
    port: int = LAN_INTERACTION_PORT

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", _identity(self.device_id))
        object.__setattr__(self, "ip_address", _private_ipv4(self.ip_address))
        if isinstance(self.port, bool) or self.port != LAN_INTERACTION_PORT:
            raise ValueError("automatic discovery port must be 18487")


@dataclass(frozen=True, slots=True)
class DirectEndpoint:
    key: CandidateKey
    extensions: frozenset[str]
    verified_at: float
    assisted: bool


@dataclass(frozen=True, slots=True)
class _CandidateOffer:
    referrer_device_id: str
    offered_at: float


class DirectEndpointBook:
    def __init__(self, *, local_device_id: str, maximum_per_device: int = 4) -> None:
        self.local_device_id = _identity(local_device_id)
        if (
            isinstance(maximum_per_device, bool)
            or not isinstance(maximum_per_device, int)
            or maximum_per_device < 1
        ):
            raise ValueError("maximum_per_device must be a positive integer")
        self.maximum_per_device = maximum_per_device
        self._endpoints: dict[CandidateKey, DirectEndpoint] = {}

    def observe(
        self,
        device_id: str,
        ip_address: str,
        port: int,
        extensions: tuple[str, ...],
        verified_at: float,
        assisted: bool,
    ) -> DirectEndpoint:
        key = CandidateKey(device_id, ip_address, port)
        if key.device_id == self.local_device_id:
            raise ValueError("cannot observe the local device as a peer")
        if not isinstance(assisted, bool):
            raise ValueError("assisted must be a boolean")
        previous = self._endpoints.get(key)
        endpoint = DirectEndpoint(
            key=key,
            extensions=frozenset(extensions) | (previous.extensions if previous else frozenset()),
            verified_at=float(verified_at),
            assisted=assisted or bool(previous and previous.assisted),
        )
        self._endpoints[key] = endpoint
        same_device = sorted(
            (item for item in self._endpoints.values() if item.key.device_id == key.device_id),
            key=lambda item: (item.verified_at, item.key.ip_address, item.key.port),
        )
        for oldest in same_device[: -self.maximum_per_device]:
            self._endpoints.pop(oldest.key, None)
        return endpoint

    def preferred(self, device_id: str) -> DirectEndpoint | None:
        normalized = _identity(device_id)
        matches = [
            endpoint
            for endpoint in self._endpoints.values()
            if endpoint.key.device_id == normalized
        ]
        if not matches:
            return None
        return max(
            matches,
            key=lambda item: (item.verified_at, item.key.ip_address, item.key.port),
        )

    def endpoints(self) -> tuple[DirectEndpoint, ...]:
        return tuple(
            sorted(
                self._endpoints.values(),
                key=lambda item: (item.key.device_id, item.key.ip_address, item.key.port),
            )
        )

    def contains(self, key: CandidateKey) -> bool:
        return key in self._endpoints

    def shareable_records(self, *, now: float) -> tuple[PeerEndpointRecord, ...]:
        records = [
            PeerEndpointRecord(
                endpoint.key.device_id,
                endpoint.key.ip_address,
                endpoint.key.port,
                max(0, min(24, int(float(now) - endpoint.verified_at))),
            )
            for endpoint in self._endpoints.values()
            if 0 <= float(now) - endpoint.verified_at <= DIRECT_ENDPOINT_TTL_SECONDS
            and "probe_token_v1" in endpoint.extensions
        ]
        return tuple(sorted(records, key=lambda item: (item.device_id, item.ip_address, item.port)))

    def assisted_keys(self, *, now: float) -> tuple[CandidateKey, ...]:
        current = float(now)
        return tuple(
            sorted(
                (
                    endpoint.key
                    for endpoint in self._endpoints.values()
                    if endpoint.assisted
                    and 0 <= current - endpoint.verified_at <= ASSISTED_ENDPOINT_TTL_SECONDS
                ),
                key=lambda key: (key.device_id, key.ip_address, key.port),
            )
        )

    def expire(self, *, now: float) -> tuple[CandidateKey, ...]:
        current = float(now)
        expired = tuple(
            sorted(
                (
                    endpoint.key
                    for endpoint in self._endpoints.values()
                    if current - endpoint.verified_at
                    > (
                        ASSISTED_ENDPOINT_TTL_SECONDS
                        if endpoint.assisted
                        else DIRECT_ENDPOINT_TTL_SECONDS
                    )
                ),
                key=lambda key: (key.device_id, key.ip_address, key.port),
            )
        )
        for key in expired:
            self._endpoints.pop(key, None)
        return expired

    def clear(self) -> None:
        self._endpoints.clear()


class CandidateQueue:
    BACKOFF_SECONDS = (120.0, 240.0, 480.0, 600.0)

    def __init__(
        self,
        *,
        local_device_id: str,
        maximum: int = 128,
        negative_cache_maximum: int = DEFAULT_NEGATIVE_CACHE_MAXIMUM,
    ) -> None:
        self.local_device_id = _identity(local_device_id)
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
            raise ValueError("maximum must be a positive integer")
        if (
            isinstance(negative_cache_maximum, bool)
            or not isinstance(negative_cache_maximum, int)
            or negative_cache_maximum < 1
        ):
            raise ValueError("negative_cache_maximum must be a positive integer")
        self.maximum = maximum
        self.negative_cache_maximum = negative_cache_maximum
        self._queued: dict[CandidateKey, _CandidateOffer] = {}
        self._active: dict[CandidateKey, str] = {}
        self._failure_counts: dict[CandidateKey, int] = {}
        self._backoff_until: dict[CandidateKey, float] = {}
        self._failure_expires_at: dict[CandidateKey, float] = {}

    def offer(
        self,
        key: CandidateKey,
        referrer_device_id: str,
        now: float,
        *,
        already_verified: bool = False,
    ) -> bool:
        if not isinstance(key, CandidateKey):
            return False
        referrer = _identity(referrer_device_id)
        current = float(now)
        self._expire_queued(current)
        self._prune_negative_cache(current)
        if (
            key.device_id == self.local_device_id
            or already_verified
            or key in self._queued
            or key in self._active
            or current < self._backoff_until.get(key, 0.0)
            or len(self._queued) + len(self._active) >= self.maximum
        ):
            return False
        self._queued[key] = _CandidateOffer(referrer, current)
        return True

    def take_ready(
        self,
        *,
        now: float,
        limit: int,
        blocked_referrers: frozenset[str] = frozenset(),
    ) -> tuple[CandidateKey, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            return ()
        current = float(now)
        self._expire_queued(current)
        self._prune_negative_cache(current)
        selected = tuple(
            key
            for key, offer in self._queued.items()
            if offer.referrer_device_id not in blocked_referrers
        )[:limit]
        for key in selected:
            self._active[key] = self._queued.pop(key).referrer_device_id
        return selected

    def referrer(self, key: CandidateKey) -> str | None:
        active = self._active.get(key)
        if active is not None:
            return active
        queued = self._queued.get(key)
        return queued.referrer_device_id if queued is not None else None

    def mark_failed(self, key: CandidateKey, *, now: float) -> None:
        self._queued.pop(key, None)
        self._active.pop(key, None)
        failures = self._failure_counts.get(key, 0) + 1
        self._drop_failure(key)
        self._failure_counts[key] = failures
        delay = self.BACKOFF_SECONDS[min(failures - 1, len(self.BACKOFF_SECONDS) - 1)]
        self._backoff_until[key] = float(now) + delay
        self._failure_expires_at[key] = float(now) + NEGATIVE_CACHE_TTL_SECONDS
        self._prune_negative_cache(float(now))

    def mark_verified(self, key: CandidateKey) -> None:
        self._queued.pop(key, None)
        self._active.pop(key, None)
        self._drop_failure(key)

    def backoff_until(self, key: CandidateKey) -> float | None:
        return self._backoff_until.get(key)

    def queued_keys(self) -> tuple[CandidateKey, ...]:
        return tuple(self._queued)

    def active_keys(self) -> tuple[CandidateKey, ...]:
        return tuple(self._active)

    def clear(self) -> None:
        self._queued.clear()
        self._active.clear()
        self._failure_counts.clear()
        self._backoff_until.clear()
        self._failure_expires_at.clear()

    def _expire_queued(self, now: float) -> None:
        expired = tuple(
            key
            for key, offer in self._queued.items()
            if now - offer.offered_at > CANDIDATE_TTL_SECONDS
        )
        for key in expired:
            self._queued.pop(key, None)

    def _prune_negative_cache(self, now: float) -> None:
        expired = tuple(
            key
            for key, expires_at in self._failure_expires_at.items()
            if now >= expires_at and key not in self._queued and key not in self._active
        )
        for key in expired:
            self._drop_failure(key)
        overflow = len(self._failure_counts) - self.negative_cache_maximum
        if overflow <= 0:
            return
        for key in tuple(self._failure_counts):
            if key in self._queued or key in self._active:
                continue
            self._drop_failure(key)
            overflow -= 1
            if overflow <= 0:
                break

    def _drop_failure(self, key: CandidateKey) -> None:
        self._failure_counts.pop(key, None)
        self._backoff_until.pop(key, None)
        self._failure_expires_at.pop(key, None)
