import asyncio

from server.datahub import DataHub, Subscriber, TopicPolicy, topic_allowed


class CountingProducer:
    patterns = ["test:*"]

    def __init__(self, fail=False):
        self.calls: list[list[str]] = []
        self.fail = fail

    async def refresh(self, hub, topics):
        self.calls.append(list(topics))
        for t in topics:
            if self.fail:
                await hub.publish_error(t, "boom")
            else:
                await hub.publish(t, {"n": len(self.calls)})


def collector():
    got: list[dict] = []

    async def cb(msg):
        got.append(msg)
    return Subscriber(cb), got


def run(coro):
    return asyncio.run(coro)


def test_one_fetch_many_subscribers_and_batching():
    async def go():
        hub = DataHub()
        prod = CountingProducer()
        hub.register_producer(prod)
        hub.set_policy_pattern("test:*", TopicPolicy(ttl_ms=60_000, min_interval_ms=0))
        subs = [collector() for _ in range(5)]
        for s, _ in subs:
            await hub.subscribe("test:a", s)
        await asyncio.sleep(0.05)
        assert len(prod.calls) == 1  # 5 suscriptores, 1 sola descarga
        assert all(got[-1]["data"] == {"n": 1} for _, got in subs)
        late, got = collector()
        await hub.subscribe("test:a", late)  # valor fresco en caché → entrega inmediata sin refresh
        assert got[0]["type"] == "update" and len(prod.calls) == 1
    run(go())


def test_scheduler_batches_stale_topics_and_respects_min_interval():
    async def go():
        hub = DataHub()
        hub.tick_s = 0.01
        prod = CountingProducer()
        hub.register_producer(prod)
        hub.set_policy_pattern("test:*", TopicPolicy(ttl_ms=10, min_interval_ms=200))
        s, _ = collector()
        for t in ("test:a", "test:b", "test:c"):
            hub.topics.setdefault(t, __import__("server.datahub", fromlist=["TopicState"]).TopicState())
            hub.topics[t].subscribers.add(s)
        hub.start()
        await asyncio.sleep(0.1)
        await hub.stop()
        assert prod.calls[0] == ["test:a", "test:b", "test:c"]  # un refresh por productor con todo el lote
        assert len(prod.calls) == 1  # min_interval 200 ms impide más refrescos en 100 ms
    run(go())


def test_last_known_good_on_error():
    async def go():
        hub = DataHub()
        hub.set_policy_pattern("test:*", TopicPolicy(min_interval_ms=0))
        await hub.publish("test:x", {"v": 1})
        hub.register_producer(CountingProducer(fail=True))
        s, got = collector()
        await hub.subscribe("test:x", s)
        hub.topics["test:x"].updated_at = 0  # forzar caducidad
        hub._kick(["test:x"])
        await asyncio.sleep(0.05)
        assert hub.peek("test:x") == {"v": 1}
        assert got[-1] == {"type": "error", "topic": "test:x", "error": "boom", "stale": True}
    run(go())


def test_coalesce_delivers_only_latest_value():
    async def go():
        hub = DataHub()
        hub.set_policy_pattern("feed:*", TopicPolicy(push_only=True, coalesce_within_ms=50))
        s, got = collector()
        await hub.subscribe("feed:x", s)
        for i in range(10):
            await hub.publish("feed:x", i)
        await asyncio.sleep(0.1)
        assert [m["data"] for m in got] == [9]
    run(go())


def test_drop_on_idle_and_topic_ownership():
    async def go():
        hub = DataHub()
        hub.set_policy_pattern("chat:*", TopicPolicy(push_only=True, drop_on_idle=True))
        s, _ = collector()
        await hub.subscribe("chat:1:abc", s)
        await hub.publish("chat:1:abc", "hi")
        hub.unsubscribe("chat:1:abc", s)
        assert "chat:1:abc" not in hub.topics
    run(go())
    assert topic_allowed("market:quote:AAPL", 7)
    assert topic_allowed("paper:7:account", 7)
    assert not topic_allowed("paper:71:account", 7)
    assert not topic_allowed("mcp:1:activity", 7)
