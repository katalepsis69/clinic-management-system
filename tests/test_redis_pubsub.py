import pytest
from app.redis_pubsub import BroadcastBus

@pytest.mark.asyncio
async def test_broadcast_bus_fallback():
    bus = BroadcastBus(redis_url=None)
    messages = []
    
    async def listener(msg):
        messages.append(msg)

    bus.subscribe("queue", listener)
    await bus.publish("queue", {"event": "PATIENT_CALLED", "ticket": "Q-105"})
    assert len(messages) == 1
    assert messages[0]["ticket"] == "Q-105"

@pytest.mark.asyncio
async def test_broadcast_bus_multiple_subscribers():
    bus = BroadcastBus(redis_url=None)
    received_a = []
    received_b = []

    bus.subscribe("chat:room1", lambda msg: received_a.append(msg))
    bus.subscribe("chat:room1", lambda msg: received_b.append(msg))

    await bus.publish("chat:room1", {"text": "hello room1"})
    assert len(received_a) == 1
    assert len(received_b) == 1
    assert received_a[0]["text"] == "hello room1"
