"""Cliente mínimo de la Client Portal Web API de Interactive Brokers.

El gateway de IBKR (clientportal.gw o IBeam) corre en la máquina del usuario y es quien tiene la
sesión iniciada: este servidor nunca ve el usuario ni la contraseña de IBKR. Por seguridad:

* Solo se acepta un gateway en loopback (127.0.0.1 / localhost / ::1). La URL viene de la variable
  FINCEPT_IBKR_URL y no se puede cambiar desde la interfaz.
* El gateway usa un certificado autofirmado: si no se indica FINCEPT_IBKR_CA, la verificación TLS
  se omite SOLO para loopback (el tráfico no sale de la máquina).
* Las órdenes son limitadas (LMT, DAY), nunca a mercado.

Endpoints usados: /iserver/auth/status, /iserver/accounts, /iserver/secdef/search,
/iserver/account/{acct}/orders, /iserver/reply/{id}, /iserver/account/orders,
/iserver/account/{acct}/order/{id} (DELETE) y /portfolio/{acct}/positions/0.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from ..config import settings

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class IBKRError(Exception):
    pass


class IBKRClient:
    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = (base_url or settings.ibkr_url).rstrip("/")
        host = urlparse(self.base_url).hostname or ""
        if host not in LOOPBACK:
            raise IBKRError(f"El gateway de IBKR debe estar en esta máquina (loopback); '{host}' no está permitido.")
        verify: bool | str = settings.ibkr_ca or False
        self._client = httpx.AsyncClient(base_url=self.base_url, verify=verify, timeout=15.0, transport=transport,
                                         headers={"User-Agent": "fincept-lite"})
        self._conids: dict[str, int] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def _req(self, method: str, path: str, **kw):
        try:
            r = await self._client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise IBKRError(f"No se pudo hablar con el gateway de IBKR en {self.base_url} "
                            f"({e.__class__.__name__}). ¿Está arrancado y con la sesión iniciada?") from e
        if r.status_code == 401:
            raise IBKRError("El gateway de IBKR no tiene sesión iniciada: entra en él desde el navegador.")
        if r.status_code >= 400:
            raise IBKRError(f"IBKR respondió {r.status_code} en {path}: {r.text[:200]}")
        return r.json() if r.content else {}

    async def status(self) -> dict:
        s = await self._req("GET", "/iserver/auth/status")
        return {"authenticated": bool(s.get("authenticated")), "connected": bool(s.get("connected")),
                "competing": bool(s.get("competing"))}

    async def accounts(self) -> list[str]:
        return list((await self._req("GET", "/iserver/accounts")).get("accounts") or [])

    async def conid(self, symbol: str) -> int:
        """conid del ETF/acción en bolsa de EE. UU. (secType STK)."""
        if symbol in self._conids:
            return self._conids[symbol]
        res = await self._req("GET", "/iserver/secdef/search", params={"symbol": symbol})
        for item in res if isinstance(res, list) else []:
            secs = {s.get("secType") for s in item.get("sections") or []}
            if "STK" in secs and item.get("conid"):
                self._conids[symbol] = int(item["conid"])
                return self._conids[symbol]
        raise IBKRError(f"IBKR no encuentra {symbol} como acción/ETF.")

    async def positions(self, account: str) -> dict[int, dict]:
        rows = await self._req("GET", f"/portfolio/{account}/positions/0")
        return {int(r["conid"]): {"qty": float(r.get("position") or 0), "price": r.get("mktPrice")}
                for r in rows if isinstance(rows, list) and r.get("conid")}

    def _order_or_question(self, res) -> dict:
        item = res[0] if isinstance(res, list) and res else res
        if not isinstance(item, dict):
            raise IBKRError(f"Respuesta inesperada de IBKR: {str(res)[:200]}")
        if item.get("order_id"):
            return {"order_id": str(item["order_id"]), "status": item.get("order_status", "Submitted")}
        if item.get("id") and item.get("message"):  # IBKR pide confirmar avisos: decide la persona, no el código
            return {"reply_id": str(item["id"]), "messages": [str(m) for m in item["message"]]}
        raise IBKRError(f"IBKR rechazó la orden: {item.get('error') or str(item)[:200]}")

    async def place_limit(self, account: str, conid: int, side: str, qty: int, limit: float, coid: str) -> dict:
        """Envía UNA orden limitada DAY. Devuelve {order_id, status} o, si IBKR pide confirmar avisos,
        {reply_id, messages}: la orden no existe hasta que la persona los confirme con `reply`."""
        body = {"orders": [{"conid": conid, "orderType": "LMT", "price": round(limit, 2), "side": side.upper(),
                            "quantity": int(qty), "tif": "DAY", "cOID": coid}]}
        return self._order_or_question(await self._req("POST", f"/iserver/account/{account}/orders", json=body))

    async def reply(self, reply_id: str) -> dict:
        return self._order_or_question(await self._req("POST", f"/iserver/reply/{reply_id}", json={"confirmed": True}))

    async def orders(self) -> dict[str, dict]:
        res = await self._req("GET", "/iserver/account/orders")
        return {str(o.get("orderId")): {"status": o.get("status"), "filled": float(o.get("filledQuantity") or 0),
                                        "avg_price": float(o.get("avgPrice") or 0) or None}
                for o in (res.get("orders") or []) if o.get("orderId") is not None}

    async def cancel(self, account: str, order_id: str) -> None:
        await self._req("DELETE", f"/iserver/account/{account}/order/{order_id}")
