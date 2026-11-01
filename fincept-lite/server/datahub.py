"""DataHub: réplica asyncio de fincept-qt/src/datahub (DataHub + Producer + TopicPolicy).

Idea central del terminal: **una sola descarga por tópico, muchos suscriptores**.
Las pantallas no hacen HTTP: se suscriben a tópicos con formato
`dominio:subdominio:id[:modificador]` (p. ej. `market:quote:AAPL`).

* subscribe()  → si hay valor en caché se entrega al instante (peek); si está
  caducado (TTL) se pide al Producer que lo refresque.
* El scheduler nunca refresca un tópico más a menudo que `min_interval_ms`
  aunque haya 50 suscriptores, y agrupa los tópicos por productor (batch).
* Si un productor falla se conserva el **último valor bueno** y se notifica el
  error; si no responde en `refresh_timeout_ms` se libera el flag in_flight.
* `push_only` = feeds que empujan solos (websockets, eventos de órdenes).
* `coalesce_within_ms` = backpressure: solo se entrega el último valor de la ventana.
* `drop_on_idle` = el estado se descarta al irse el último suscriptor.
"""

from __future__ import annotations

import asyncio
import fnmatch
import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol


@dataclass
class TopicPolicy:
    ttl_ms: int = 30_000
    min_interval_ms: int = 5_000
    refresh_timeout_ms: int = 30_000
    push_only: bool = False
    coalesce_within_ms: int = 0
    drop_on_idle: bool = False


class Producer(Protocol):
    patterns: list[str]

    async def refresh(self, hub: "DataHub", topics: list[str]) -> None: ...


Callback = Callable[[dict], Awaitable[None]]

# Tópicos privados: el segundo segmento es el id de usuario (paper:<uid>:account, mcp:<uid>:activity...).
USER_TOPIC_PREFIXES = ("paper:", "mcp:", "chat:")


def topic_allowed(topic: str, uid: int) -> bool:
    """Un usuario solo ve los tópicos públicos y los privados que llevan su id."""
    if not topic.startswith(USER_TOPIC_PREFIXES):
        return True
    parts = topic.split(":")
    return len(parts) >= 3 and parts[1] == str(uid)


@dataclass(eq=False)
class Subscriber:
    callback: Callback
    label: str = "anon"
    id: int = field(default_factory=lambda: next(_ids))


_ids = itertools.count(1)


@dataclass
class TopicState:
    value: Any = None
    updated_at: float = 0.0
    error: str | None = None
    in_flight: bool = False
    in_flight_since: float = 0.0
    last_refresh: float = 0.0
    publishes: int = 0
    refreshes: int = 0
    subscribers: set = field(default_factory=set)
    coalesce_task: asyncio.Task | None = None
    pending: Any = None


class DataHub:
    def __init__(self) -> None:
        self.topics: dict[str, TopicState] = {}
        self.producers: list[Producer] = []
        self.policies: list[tuple[str, TopicPolicy]] = []
        self.listeners: list[tuple[str, Callable[[str, Any], Awaitable[None]]]] = []
        self._task: asyncio.Task | None = None
        self.tick_s = 0.25

    # ── configuración ───────────────────────────────────────────────────────
    def register_producer(self, producer: Producer) -> None:
        self.producers.append(producer)

    def set_policy_pattern(self, pattern: str, policy: TopicPolicy) -> None:
        self.policies.insert(0, (pattern, policy))  # el último registrado gana

    def policy(self, topic: str) -> TopicPolicy:
        for pat, pol in self.policies:
            if fnmatch.fnmatchcase(topic, pat):
                return pol
        return TopicPolicy()

    def on_publish(self, pattern: str, fn: Callable[[str, Any], Awaitable[None]]) -> None:
        """Hook interno (p. ej. el OrderMatcher escucha market:quote:*)."""
        self.listeners.append((pattern, fn))

    def producer_for(self, topic: str) -> Producer | None:
        for p in self.producers:
            if any(fnmatch.fnmatchcase(topic, pat) for pat in p.patterns):
                return p
        return None

    # ── suscripción ─────────────────────────────────────────────────────────
    async def subscribe(self, topic: str, sub: Subscriber) -> None:
        st = self.topics.setdefault(topic, TopicState())
        st.subscribers.add(sub)
        if st.value is not None:
            await self._deliver(sub, topic, st)
        pol = self.policy(topic)
        if not pol.push_only and self._stale(st, pol):
            self._kick([topic])

    def unsubscribe(self, topic: str, sub: Subscriber) -> None:
        st = self.topics.get(topic)
        if not st:
            return
        st.subscribers.discard(sub)
        if not st.subscribers and self.policy(topic).drop_on_idle:
            self.topics.pop(topic, None)

    def unsubscribe_all(self, sub: Subscriber) -> None:
        for topic in list(self.topics):
            self.unsubscribe(topic, sub)

    def peek(self, topic: str) -> Any:
        st = self.topics.get(topic)
        return st.value if st else None

    # ── publicación ─────────────────────────────────────────────────────────
    async def publish(self, topic: str, value: Any) -> None:
        st = self.topics.setdefault(topic, TopicState())
        st.in_flight = False
        st.error = None
        pol = self.policy(topic)
        if pol.coalesce_within_ms > 0:
            st.pending = value
            if st.coalesce_task is None or st.coalesce_task.done():
                st.coalesce_task = asyncio.create_task(self._flush_coalesced(topic, pol.coalesce_within_ms))
            return
        await self._commit(topic, st, value)

    async def _flush_coalesced(self, topic: str, window_ms: int) -> None:
        await asyncio.sleep(window_ms / 1000)
        st = self.topics.get(topic)
        if st is not None:
            await self._commit(topic, st, st.pending)

    async def _commit(self, topic: str, st: TopicState, value: Any) -> None:
        st.value, st.updated_at = value, time.time()
        st.publishes += 1
        await asyncio.gather(*(self._deliver(s, topic, st) for s in list(st.subscribers)))
        for pat, fn in self.listeners:
            if fnmatch.fnmatchcase(topic, pat):
                try:
                    await fn(topic, value)
                except Exception as e:  # un listener roto no tumba el hub
                    print(f"[datahub] listener error on {topic}: {e!r}", flush=True)

    async def publish_error(self, topic: str, error: str) -> None:
        st = self.topics.setdefault(topic, TopicState())
        st.in_flight = False
        st.error = error
        st.last_refresh = time.time()
        msg = {"type": "error", "topic": topic, "error": error, "stale": st.value is not None}
        await asyncio.gather(*(self._safe(s, msg) for s in list(st.subscribers)))

    async def _deliver(self, sub: Subscriber, topic: str, st: TopicState) -> None:
        await self._safe(sub, {"type": "update", "topic": topic, "data": st.value, "ts": st.updated_at})

    @staticmethod
    async def _safe(sub: Subscriber, msg: dict) -> None:
        try:
            await sub.callback(msg)
        except Exception as e:
            print(f"[datahub] subscriber {sub.label} failed: {e!r}", flush=True)

    # ── scheduler ───────────────────────────────────────────────────────────
    @staticmethod
    def _stale(st: TopicState, pol: TopicPolicy) -> bool:
        return st.value is None or (time.time() - st.updated_at) * 1000 >= pol.ttl_ms

    def _due(self, topic: str, st: TopicState) -> bool:
        pol = self.policy(topic)
        now = time.time()
        if pol.push_only or not st.subscribers:
            return False
        if st.in_flight:
            if (now - st.in_flight_since) * 1000 > pol.refresh_timeout_ms:
                print(f"[datahub] refresh timeout on {topic}; clearing in_flight", flush=True)
                st.in_flight = False
            return False
        if (now - st.last_refresh) * 1000 < pol.min_interval_ms:
            return False
        return self._stale(st, pol)

    def _kick(self, topics: list[str]) -> None:
        by_producer: dict[int, tuple[Producer, list[str]]] = {}
        now = time.time()
        for t in topics:
            st = self.topics.get(t)
            prod = self.producer_for(t)
            if st is None or prod is None or st.in_flight:
                continue
            if (now - st.last_refresh) * 1000 < self.policy(t).min_interval_ms:
                continue
            st.in_flight, st.in_flight_since, st.last_refresh = True, now, now
            st.refreshes += 1
            by_producer.setdefault(id(prod), (prod, []))[1].append(t)
        for prod, ts in by_producer.values():
            asyncio.create_task(self._run_refresh(prod, ts))

    async def _run_refresh(self, prod: Producer, topics: list[str]) -> None:
        try:
            await prod.refresh(self, topics)
        except Exception as e:
            for t in topics:
                await self.publish_error(t, f"{e.__class__.__name__}: {e}")
        for t in topics:  # el productor terminó sin publicar → no dejar in_flight colgado
            st = self.topics.get(t)
            if st:
                st.in_flight = False

    async def _loop(self) -> None:
        while True:
            due = [t for t, st in list(self.topics.items()) if self._due(t, st)]
            if due:
                self._kick(due)
            await asyncio.sleep(self.tick_s)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    # ── inspección (pantalla DataHub / tool datahub_topics) ────────────────
    def stats(self) -> list[dict]:
        now = time.time()
        out = []
        for t, st in sorted(self.topics.items()):
            pol = self.policy(t)
            out.append({
                "topic": t, "subscribers": len(st.subscribers),
                "age_ms": int((now - st.updated_at) * 1000) if st.updated_at else None,
                "ttl_ms": pol.ttl_ms, "min_interval_ms": pol.min_interval_ms, "push_only": pol.push_only,
                "coalesce_ms": pol.coalesce_within_ms, "in_flight": st.in_flight, "error": st.error,
                "publishes": st.publishes, "refreshes": st.refreshes,
            })
        return out


hub = DataHub()
