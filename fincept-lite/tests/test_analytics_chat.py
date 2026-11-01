import math

import pytest

from server import analytics
from server.ai_chat import extract_symbols


def test_black_scholes_reference_value_and_parity():
    c = analytics.bs_price(100, 100, 1, 0.05, 0.2, "call")
    p = analytics.bs_price(100, 100, 1, 0.05, 0.2, "put")
    assert c == pytest.approx(10.4506, abs=1e-4)
    assert c - p == pytest.approx(100 - 100 * math.exp(-0.05), abs=1e-9)  # paridad put-call


def test_greeks_signs_and_implied_vol_roundtrip():
    g = analytics.bs_greeks(100, 110, 0.5, 0.03, 0.3, "put")
    assert -1 < g["delta"] < 0 and g["gamma"] > 0 and g["vega"] > 0
    iv = analytics.implied_vol(g["price"], 100, 110, 0.5, 0.03, "put")
    assert iv == pytest.approx(0.3, abs=1e-6)
    with pytest.raises(ValueError):
        analytics.implied_vol(0.01, 100, 50, 1, 0.0, "call")  # por debajo del valor intrínseco


def test_risk_metrics_on_known_series():
    closes = [100 * (1.01 ** i) for i in range(60)]
    m = analytics.risk_metrics(closes)
    assert m["max_drawdown"] == 0 and m["total_return"] == pytest.approx(1.01 ** 59 - 1)
    zig = [100, 110, 99, 120, 60, 80, 90, 95, 100, 70, 75]
    assert analytics.max_drawdown(zig) == pytest.approx(60 / 120 - 1)


def test_extract_symbols_spanish_and_tickers():
    assert extract_symbols("¿Cómo van Apple y NVDA hoy?") == ["AAPL", "NVDA"]
    assert extract_symbols("precio del bitcoin y del oro") == ["BTC-USD", "GC=F"]
    assert "SAN.MC" in extract_symbols("Noticias de SAN.MC")
    assert extract_symbols("qué es el VaR de la FED") == []


def test_offline_chat_uses_tools(client, user):
    r = client.post("/research/chat", headers=user["headers"], json={"message": "¿Cómo van AAPL y MSFT?"}).json()
    d = r["data"]
    assert d["mode"] == "offline" and d["credits_charged"] == 0
    assert d["tool_calls"][0]["tool"] == "get_quotes" and d["tool_calls"][0]["ok"]
    assert "AAPL" in d["reply"] and "MSFT" in d["reply"]
    risk = client.post("/research/chat", headers=user["headers"],
                       json={"message": "riesgo de TSLA", "session_id": d["session_id"]}).json()["data"]
    assert risk["tool_calls"][0]["tool"] == "compute_risk" and "Sharpe" in risk["reply"]
    hist = client.get(f"/chat/sessions/{d['session_id']}", headers=user["headers"]).json()["data"]["messages"]
    assert [m["role"] for m in hist] == ["user", "assistant", "user", "assistant"]


class _FakeMessages:
    """Imita client.beta.messages.create: 1ª respuesta pide una tool, 2ª responde texto."""

    def __init__(self):
        from types import SimpleNamespace as NS
        self.calls = []
        self.responses = [
            NS(stop_reason="tool_use", content=[
                NS(type="thinking", thinking="", signature="sig"),
                NS(type="tool_use", id="tu_1", name="get_quote", input={"symbol": "AAPL"})]),
            NS(stop_reason="end_turn", content=[NS(type="text", text="AAPL cotiza según la tool.")]),
        ]

    async def create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})
        return self.responses[len(self.calls) - 1]


def test_claude_mode_tool_loop(client, user, monkeypatch):
    from types import SimpleNamespace as NS

    from server import ai_chat
    fake = _FakeMessages()
    monkeypatch.setattr(ai_chat, "claude_available", lambda: True)
    monkeypatch.setattr(ai_chat, "client", lambda: NS(beta=NS(messages=fake)))
    r = client.post("/research/chat", headers=user["headers"], json={"message": "precio de Apple"}).json()["data"]
    assert r["mode"] == "claude" and r["reply"] == "AAPL cotiza según la tool." and r["credits_charged"] == 5
    first, second = fake.calls
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert first["betas"] == ["server-side-fallback-2026-07-01"]
    assert first["thinking"] == {"type": "adaptive"} and first["output_config"] == {"effort": "medium"}
    names = {t["name"] for t in first["tools"]}
    assert "get_quote" in names and "pt_place_order" not in names  # el chat no puede operar
    # 2ª petición: historial append-only → user, assistant(con thinking + tool_use), user(tool_result)
    roles = [m["role"] for m in second["messages"]]
    assert roles == ["user", "assistant", "user"]
    tr = second["messages"][2]["content"][0]
    assert tr["type"] == "tool_result" and tr["tool_use_id"] == "tu_1" and not tr["is_error"]
    assert '"symbol": "AAPL"' in tr["content"]
    bal = client.get("/user/profile", headers=user["headers"]).json()["data"]["credit_balance"]
    assert bal == 345
