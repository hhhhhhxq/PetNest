from __future__ import annotations

from petnest.core.event_bus import EventBus
from petnest.models.event import PetEvent


def test_event_bus_delivers_events_and_can_unsubscribe() -> None:
    bus = EventBus()
    received: list[str] = []
    unsubscribe = bus.subscribe(lambda event: received.append(event.event_name))
    bus.publish(PetEvent("app.start", source="test"))
    unsubscribe()
    bus.publish(PetEvent("app.quit", source="test"))
    assert received == ["app.start"]
