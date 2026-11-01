import json
import threading
import time

import pytest

from server.config import settings


@pytest.fixture
def mcp(client, user):
    data = client.get("/api/mcp/connect", headers=user["headers"]).json()["data"]
    token = data["token"]

    def rpc(method, params=None, id_=1, headers=None, raw=None):
        h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", **(headers or {})}
        body = raw if raw is not None else json.dumps({"jsonrpc": "2.0", "id": id_, "method": method,
                                                       "params": params or {}})
        return client.post("/mcp", content=body, headers=h)

    def call(name, args=None):
        r = rpc("tools/call", {"name": name, "arguments": args or {}}).json()
        res = r["result"]
        return res, json.loads(res["content"][0]["text"]) if not res["isError"] else res["content"][0]["text"]

    return {"rpc": rpc, "call": call, "token": token, "user": user, "snippets": data}


def test_connect_snippets_match_terminal_format(mcp):
    s = mcp["snippets"]
    assert s["url"].endswith("/mcp") and s["token"].startswith("fmcp_")
    assert s["claude_code"].startswith("claude mcp add --transport http fincept ")
    assert 'bearer_token_env_var = "FINCEPT_MCP_TOKEN"' in s["codex_toml"]


def test_auth_and_guards(client, mcp):
    assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
    bad = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                      headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401 and bad.headers["www-authenticate"].startswith("Bearer")
    # DNS rebinding: Host de un dominio ajeno
    assert mcp["rpc"]("ping", headers={"Host": "evil.example.com"}).status_code == 403
    # Origin no loopback
    assert mcp["rpc"]("ping", headers={"Origin": "https://evil.example.com"}).status_code == 403
    # petición cross-site de navegador (fetch/img), no navegación
    assert mcp["rpc"]("ping", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"}).status_code == 403
    assert mcp["rpc"]("ping", headers={"Host": "127.0.0.1:41720"}).status_code == 200
    assert client.get("/mcp").status_code == 405


def test_initialize_negotiates_protocol(mcp):
    r = mcp["rpc"]("initialize", {"protocolVersion": "2025-03-26", "clientInfo": {"name": "claude-code"}}).json()
    assert r["result"]["protocolVersion"] == "2025-03-26"
    assert r["result"]["serverInfo"]["name"] == "fincept-terminal"
    assert "tool_list" in r["result"]["instructions"]
    r2 = mcp["rpc"]("initialize", {"protocolVersion": "1999-01-01"}).json()
    assert r2["result"]["protocolVersion"] == "2025-06-18"


def test_jsonrpc_edge_cases(mcp):
    note = mcp["rpc"](None, raw=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    assert note.status_code == 202 and note.content == b""
    assert mcp["rpc"](None, raw="{not json").json()["error"]["code"] == -32700
    assert mcp["rpc"]("does/not/exist").json()["error"]["code"] == -32601
    assert mcp["rpc"]("tools/call", {"name": "nope", "arguments": {}}).json()["error"]["code"] == -32602
    batch = mcp["rpc"](None, raw=json.dumps([
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ])).json()
    assert [m["id"] for m in batch] == [1, 2]


def test_essentials_toolset_hides_destructive_tools(client, mcp):
    names = {t["name"] for t in mcp["rpc"]("tools/list").json()["result"]["tools"]}
    assert {"tool_list", "tool_invoke", "job_status", "get_quote"} <= names
    assert "pt_place_order" not in names
    client.put("/api/mcp/settings", headers=mcp["user"]["headers"], json={"toolset": "full"})
    full = {t["name"] for t in mcp["rpc"]("tools/list").json()["result"]["tools"]}
    assert "pt_place_order" in full


def test_read_tool_and_discovery(mcp):
    res, data = mcp["call"]("get_quote", {"symbol": "AAPL"})
    assert res["isError"] is False and data["symbol"] == "AAPL"
    _, found = mcp["call"]("tool_list", {"query": "option pricing black scholes"})
    assert found[0]["name"] == "bs_option_price"
    _, desc = mcp["call"]("tool_describe", {"name": "get_history"})
    assert desc["inputSchema"]["required"] == ["symbol"]
    _, via = mcp["call"]("tool_invoke", {"tool": "get_quote", "arguments": {"symbol": "MSFT"}})
    assert via["symbol"] == "MSFT"
    res, err = mcp["call"]("get_quote", {"symbol": "AAPL", "extra": 1})
    assert res["isError"] and "unknown argument" in err


def test_destructive_tools_need_permission_and_approval(client, mcp):
    h = mcp["user"]["headers"]
    res, msg = mcp["call"]("watchlist_add", {"name": "IA", "symbols": ["AAPL"]})
    assert res["isError"] and "not allowed to take actions" in msg
    # tool_invoke no permite saltarse la política
    res, msg = mcp["call"]("tool_invoke", {"tool": "watchlist_add", "arguments": {"name": "IA", "symbols": ["AAPL"]}})
    assert res["isError"] and "not allowed to take actions" in msg
    client.put("/api/mcp/settings", headers=h, json={"allow_actions": True})
    res, data = mcp["call"]("watchlist_add", {"name": "IA", "symbols": ["AAPL"]})
    assert not res["isError"] and data["symbols"] == ["AAPL"]
    # pt_place_order exige además aprobación en la UI; sin ventana abierta se rechaza
    res, msg = mcp["call"]("pt_place_order", {"symbol": "AAPL", "side": "buy", "qty": 1})
    assert res["isError"] and "no terminal window is open" in msg
    acts = client.get("/api/mcp/connect", headers=h).json()["data"]["activity"]
    assert acts[0]["denied"] is True and "arguments" not in acts[0]


def test_approval_flow_with_ui_subscribed(client, mcp):
    h = mcp["user"]["headers"]
    uid = mcp["user"]["id"]
    client.put("/api/mcp/settings", headers=h, json={"allow_actions": True})
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"op": "auth", "api_key": mcp["user"]["api_key"]})
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"op": "sub", "topics": [f"mcp:{uid}:approvals"]})
        out = {}
        t = threading.Thread(target=lambda: out.update(r=mcp["call"]("pt_place_order",
                                                                      {"symbol": "MSFT", "side": "buy", "qty": 1})))
        t.start()
        msg = ws.receive_json()
        while not (msg.get("data") or {}).get("pending"):
            msg = ws.receive_json()
        aid = msg["data"]["pending"][0]["id"]
        assert msg["data"]["pending"][0]["tool"] == "pt_place_order"
        assert client.post(f"/api/mcp/approvals/{aid}", headers=h, json={"approve": True}).json()["success"]
        t.join(10)
    res, order = out["r"]
    assert not res["isError"] and order["status"] == "filled" and order["source"] == "mcp"


def test_job_protocol_and_result_paging(client, mcp, monkeypatch):
    monkeypatch.setattr(settings, "mcp_grace_seconds", 0.0)
    res, receipt = mcp["call"]("optimize_sma_cross", {"symbol": "SPY"})
    assert receipt["status"] == "running" and receipt["job_id"].startswith("job_")
    deadline = time.time() + 60
    while True:
        _, st = mcp["call"]("job_status", {"job_id": receipt["job_id"], "wait_ms": 5000})
        if st["status"] != "running" or time.time() > deadline:
            break
    assert st["status"] == "completed"
    _, result = mcp["call"]("job_result", {"job_id": receipt["job_id"]})
    assert result["tested"] > 50 and len(result["top10"]) == 10
    monkeypatch.setattr(settings, "mcp_grace_seconds", 8.0)
    monkeypatch.setattr(settings, "mcp_result_budget", 2000)
    r = mcp["rpc"]("tools/call", {"name": "get_history", "arguments": {"symbol": "AAPL", "period": "1y"}}).json()
    note = json.loads(r["result"]["content"][1]["text"])
    assert note["truncated"] and note["result_id"]
    _, page = mcp["call"]("result_fetch", {"result_id": note["result_id"], "offset": 0, "limit": 500})
    assert page["returned"] == 500 and page["total_chars"] == note["total_chars"]


def test_websocket_requires_auth_message(client, user):
    from starlette.websockets import WebSocketDisconnect
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"op": "auth", "api_key": "wrong"})
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 4401
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"op": "auth", "api_key": user["api_key"]})
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"op": "sub", "topics": ["paper:999999:account", "market:quote:AAPL"]})
        msgs = [ws.receive_json() for _ in range(2)]
        assert {"type": "error", "topic": "paper:999999:account", "error": "topic not allowed"} in msgs
        assert any(m.get("topic") == "market:quote:AAPL" and m["type"] == "update" for m in msgs)
