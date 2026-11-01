"""Calidad del servidor MCP según la skill mcp-builder."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from server import mcp_server, tools
from server.mcp_server import advertised_tools


@pytest.fixture
def mcp(client, user):
    token = client.get("/api/mcp/connect", headers=user["headers"]).json()["data"]["token"]
    client.put("/api/mcp/settings", headers=user["headers"], json={"toolset": "full"})

    def call(name, args=None):
        r = client.post("/mcp", headers={"Authorization": f"Bearer {token}"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": name, "arguments": args or {}}}).json()
        return r.get("result") or r

    return {"call": call, "user": user, "token": token}


def test_every_tool_has_full_annotations_and_documented_params(mcp):
    listed = advertised_tools(mcp["user"]["id"])
    assert len(listed) == len(tools.REGISTRY) + len(mcp_server.META_TOOLS)
    for t in listed:
        ann = t["annotations"]
        assert ann["title"] and {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"} <= set(ann), t
        for pname, p in t["inputSchema"].get("properties", {}).items():
            assert p.get("description"), f"{t['name']}.{pname} has no description"
    by = {t["name"]: t for t in listed}
    assert by["pt_place_order"]["annotations"]["idempotentHint"] is False
    assert by["watchlist_add"]["annotations"]["destructiveHint"] is False  # añade, no borra
    assert by["get_quote"]["annotations"]["openWorldHint"] is True
    assert by["bs_option_price"]["annotations"]["openWorldHint"] is False
    assert "response_format" in by["get_quote"]["inputSchema"]["properties"]


def test_structured_content_mirrors_text(mcp):
    r = mcp["call"]("get_quote", {"symbol": "AAPL"})
    assert r["structuredContent"] == json.loads(r["content"][0]["text"])
    r = mcp["call"]("get_quotes", {"symbols": ["AAPL", "MSFT"]})
    assert r["structuredContent"]["count"] == 2 and len(r["structuredContent"]["items"]) == 2


def test_markdown_format_and_pagination(mcp):
    p1 = mcp["call"]("get_top_news", {"limit": 2})["structuredContent"]
    assert p1["count"] == 2 and p1["has_more"] and p1["next_offset"] == 2
    p2 = mcp["call"]("get_top_news", {"limit": 2, "offset": 2})["structuredContent"]
    assert p2["offset"] == 2 and p2["items"][0] != p1["items"][0]
    md = mcp["call"]("get_top_news", {"limit": 2, "response_format": "markdown"})
    text = md["content"][0]["text"]
    assert text.startswith("## Get top market news") and "| title |" in text and "offset=2" in text
    assert md["structuredContent"]["count"] == 2  # el JSON estructurado sigue disponible
    big = mcp["call"]("get_history", {"symbol": "AAPL", "period": "1y", "response_format": "markdown"})
    assert "points from" in big["content"][0]["text"]  # las velas se resumen, no se vuelcan
    bad = mcp["call"]("get_quote", {"symbol": "AAPL", "response_format": "xml"})
    assert bad["isError"]


def test_errors_are_actionable(mcp):
    e = mcp["call"]("get_quote", {"symbol": "NOT A TICKER!"})
    assert e["isError"] and "lookup_symbol" in e["content"][0]["text"]
    e = mcp["call"]("get_top_news", {"limit": 500})
    assert e["isError"] and "must be <= 50" in e["content"][0]["text"]
    e = mcp["call"]("get_quote", {})
    assert "tool_describe(name='get_quote')" in e["content"][0]["text"]
    e = mcp["call"]("nope_tool", {})
    assert e["error"]["code"] == -32602 and "tool_list" in e["error"]["message"]


def test_internal_errors_are_not_leaked(mcp, monkeypatch):
    async def boom(ctx, a):
        raise RuntimeError("secret /home/user/.ssh/id_rsa")
    monkeypatch.setattr(tools.REGISTRY["get_time"], "handler", boom)
    r = mcp["call"]("get_time")
    text = r["content"][0]["text"]
    assert r["isError"] and "internal error" in text and "secret" not in text and "RuntimeError" not in text


def test_rate_limit(mcp, monkeypatch):
    monkeypatch.setattr(mcp_server, "RATE_LIMIT_CALLS", 3)
    mcp_server.state(mcp["user"]["id"]).calls.clear()
    results = [mcp["call"]("get_time") for _ in range(4)]
    assert not any(r["isError"] for r in results[:3])
    assert results[3]["isError"] and "rate limit" in results[3]["content"][0]["text"]
    mcp_server.state(mcp["user"]["id"]).calls.clear()


# ── interoperabilidad con el cliente oficial del SDK de MCP ─────────────────

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    port = _free_port()
    env = {**os.environ, "FINCEPT_DATA_MODE": "sim", "FINCEPT_PORT": str(port), "FINCEPT_AI": "offline",
           "FINCEPT_DB": str(tmp_path_factory.mktemp("db") / "live.db")}
    proc = subprocess.Popen([sys.executable, "-m", "server.main"], cwd=Path(__file__).parent.parent, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(base + "/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail("server did not start")
    login = httpx.post(base + "/user/login", json={"email": "demo@example.com", "password": "demo12345",
                                                    "force_login": True}).json()["data"]
    token = httpx.get(base + "/api/mcp/connect", headers={"X-API-Key": login["api_key"]}).json()["data"]["token"]
    yield base + "/mcp", token
    proc.terminate()
    proc.wait(10)


def test_official_mcp_sdk_client_interop(live_server):
    sdk = pytest.importorskip("mcp")
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    url, token = live_server

    async def go():
        http = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
        async with streamable_http_client(url, http_client=http) as streams:
            async with sdk.ClientSession(streams[0], streams[1]) as s:
                init = await s.initialize()
                listed = await s.list_tools()
                quote = await s.call_tool("get_quote", {"symbol": "AAPL"})
                refused = await s.call_tool("pt_place_order", {"symbol": "AAPL", "side": "buy", "qty": 1})
                return init, listed, quote, refused

    init, listed, quote, refused = asyncio.run(go())
    assert init.server_info.name == "fincept-terminal"
    names = {t.name for t in listed.tools}
    assert {"tool_list", "get_quote"} <= names and "walk_forward_sma" not in names  # toolset essentials
    assert all(t.annotations and t.annotations.title for t in listed.tools)
    assert not quote.is_error and quote.structured_content["symbol"] == "AAPL"
    assert refused.is_error  # no está en essentials ni hay permiso de acciones


def test_period_window_filter():
    from server.macro import in_range
    assert in_range("2019-07-31", "2019-07", "2019-07")
    assert not in_range("2019-08-31", "2019-07", "2019-07")
    assert in_range("2020-Q2", "2020", "2020") and not in_range("2021-Q1", "2020", "2020")
    assert in_range("2022-09-14", "2022-09-01", None) and not in_range("2022-08-31", "2022-09-01", None)
