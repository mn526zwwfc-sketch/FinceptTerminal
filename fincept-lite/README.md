# Fincept Lite — réplica educativa de Fincept Terminal

Terminal financiera web al estilo de **Fincept Terminal** (y de Bloomberg): cotizaciones en vivo, gráficos, noticias, macro, paper trading, backtesting, opciones, chat IA y un **servidor MCP** para que agentes como Claude Code operen con el terminal.

Fincept Lite **no es** software oficial de Fincept. Reconstruye su arquitectura a partir de dos fuentes: el código del cliente de este repositorio (`fincept-qt/`) y la especificación OpenAPI pública del backend (`https://api.fincept.in/openapi.json`). Todo corre en un solo proceso Python, sin compilar Qt.

```
./run.sh            # abre http://127.0.0.1:41800  ·  demo: demo@example.com / demo12345
```

---

## 1. Cómo funciona "el servidor" de Fincept

En realidad Fincept no tiene un único servidor, sino **tres capas**. La aplicación de escritorio (C++20/Qt6) habla con un backend en la nube y, a la vez, actúa ella misma de servidor local.

```
┌──────────────────────── TERMINAL DE ESCRITORIO (C++/Qt6) ───────────────────────┐
│  Pantallas ──sub──▶ DataHub (pub/sub por tópicos, caché TTL) ◀──publish── Producers │
│                          ▲                                       │  HttpClient / PythonRunner
│  Paper trading + OrderMatcher ◀─ market:quote:*                   │  (yfinance, FRED, DBnomics…)
│  Servidor MCP local  127.0.0.1:41720/mcp  ◀── Claude Code / Codex / Cursor          │
└──────────────────────────────────┬───────────────────────────────────────────────┘
                                   │ HTTPS  X-API-Key + X-Session-Token  /  Bearer
┌──────────────────────────────────▼───────────────────────────────────────────────┐
│  api.fincept.in   FastAPI "Fincept API" v3.0.0 (751 rutas)  +  finceptgo (Go) en /v1 │
│  identidad · créditos · pagos · LLM · macro · marine · 590 rutas QuantLib            │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 1.1 Backend en la nube: `api.fincept.in`

Es una API **FastAPI** con OpenAPI 3.1 público. Por familias de rutas:

| Prefijo | Rutas | Para qué |
|---|---:|---|
| `/quantlib/*` | 590 | Librería cuantitativa expuesta como REST: pricing (Black-Scholes, Black-76, Bachelier, binomial…), curvas, riesgo, estocástico, ML… |
| `/user/*` | 39 | Registro, OTP, login, MFA, Google OAuth, sesión, perfil, API key, uso, notificaciones |
| `/admin/*` | 28 | Administración interna |
| `/macro/*` | 16 | CEIC, calendario económico, tipos de bancos centrales, CDS, curvas (World Government Bonds) |
| `/research/*` | 15 | LLM propio (`/research/llm`, 5 créditos), búsqueda web, papers, lectura de PDF |
| `/chat/*` | 12 | Sesiones de chat guardadas en la nube |
| `/cashfree/*` | 12 | Planes y pagos (pasarela Cashfree) |
| `/market/*` | 9 | `search`, `price`, `info`, `snapshot`, `history`, `financials`, `news`, `batch/prices`, `batch/history` |
| `/marine/*`, `/portfolio/*`, `/support/*`… | | Tracking de buques, monitor de cartera, soporte |

**Autenticación** (se ve en `auth/AuthApi.cpp`, `auth/AuthManager.cpp` y `network/http/HttpClient.cpp`):

1. `POST /user/register` → el servidor envía un **OTP de 6 dígitos** por email → `POST /user/verify-otp` devuelve `api_key` + `session_token`.
2. `POST /user/login` puede devolver tres cosas: credenciales; `{"active_session": true}` si hay otra sesión abierta (el cliente ofrece `force_login`); o `{"mfa_required": true}`, que lleva a `/user/verify-mfa`.
3. Cada petición autenticada lleva `X-API-Key` y `X-Session-Token`. Si otro dispositivo hace `force_login`, la sesión vieja recibe **401** y el `SessionGuard` del terminal cierra la sesión. `GET /user/session-pulse` hace de latido.
4. Formato de respuestas: `{"success", "message", "data"}`. Los fallos de negocio **viajan con HTTP 200 y `success:false`**, con mensajes que el cliente muestra tal cual ("Incorrect password. You have 2 attempt(s) remaining."). Los errores de validación son 422 de Pydantic (`{"detail":[{loc,msg}]}`).
5. **Créditos**: los endpoints de pago descuentan saldo (LLM 5, análisis de noticias 10, marine 1–8, batch de precios 0…). Sin saldo, el error es `insufficient_credits`.

Bajo `/v1` hay un segundo servicio, **finceptgo** (Go), al que el cliente llama con `network/cloud/CloudClient`. Usa `Authorization: Bearer <api_key>` y un sobre ampliado `{success, message, data, error, hint}`. Sirve para la sincronización en la nube.

### 1.2 El terminal como servidor interno: DataHub

La pieza central del escritorio es `src/datahub/`. Las pantallas **no hacen HTTP**: se suscriben a tópicos con el formato `dominio:subdominio:id` (por ejemplo `market:quote:AAPL`, `news:top` o `paper:<uid>:account`).

- **Una descarga por tópico, muchos suscriptores.** Si 5 paneles miran AAPL, se descarga una sola vez.
- `TopicPolicy` fija para cada tópico `ttl_ms`, `min_interval_ms`, `refresh_timeout_ms`, `push_only` (feeds que empujan solos), `coalesce_within_ms` (contrapresión) y `drop_on_idle`.
- Un *scheduler* pide a cada `Producer` que refresque **en lote** los tópicos caducados. Si falla, conserva el **último valor bueno** y notifica el error.
- El `PythonRunner` ejecuta ~1.400 scripts Python (yfinance, agentes, analítica) como subprocesos que devuelven JSON por stdout.
- El paper trading y el `OrderMatcher` escuchan `market:quote:*` para ejecutar órdenes limit/stop.

### 1.3 Servidor MCP local: `127.0.0.1:41720/mcp`

Está en `src/mcp/server/McpHttpServer*.cpp` y expone las ~900 tools internas a agentes externos:

- Transporte **Streamable HTTP sin estado** con JSON-RPC 2.0. Cada `POST /mcp` se responde con JSON; si solo llegan notificaciones, la respuesta es `202` sin cuerpo; `GET` devuelve 405. Métodos: `initialize`, `ping`, `tools/list` (páginas de 100), `tools/call`, `resources/*`, `prompts/list`.
- `Authorization: Bearer <token>` es obligatorio. El token es estable entre reinicios y regenerarlo revoca a todos los clientes.
- **Solo loopback**, con defensa contra DNS rebinding: el `Host` y el `Origin` deben ser loopback, y se rechaza un `fetch`/`<img>` cross-site de un navegador (`Sec-Fetch-*`).
- Hay dos *toolsets*. **Essentials** son las meta-tools (`tool_list` con BM25, `tool_describe`, `tool_invoke`, `job_*`, `result_fetch`) más lecturas clave. **Full** son todas.
- Las tools que cambian estado se rechazan salvo que el usuario active "allow actions". Las de trading real piden además **aprobación en la UI en cada llamada**.
- **Protocolo de jobs**: si una tool tarda más que la ventana de gracia, devuelve `{job_id, status:"running"}` y el cliente consulta `job_status`/`job_result`. Los resultados de más de 24 KB se truncan y el resto se pagina con `result_fetch`.
- `scripts/mcp/fincept_mcp_stdio.py` es un puente stdio↔HTTP para clientes que solo hablan stdio, como Claude Desktop.

---

## 2. Qué replica Fincept Lite y dónde

| Componente de Fincept | Réplica | Fichero |
|---|---|---|
| `/user/*` (registro, OTP, login, force_login, MFA, bloqueo tras 3 fallos, session-pulse, API key, uso) | ✅ mismos paths, campos y mensajes | `server/auth.py` |
| finceptgo `/v1` (Bearer + sobre `{success,message,data,error,hint}`) | ✅ `/v1/me` y sincronización de watchlists | `server/watchlists.py` |
| `/market/search|price|info|snapshot|history|news|batch/prices` | ✅ Yahoo Finance; simulador GBM como respaldo | `server/market/providers.py`, `server/routes.py` |
| Créditos y `insufficient_credits` | ✅ el chat con Claude cuesta 5, como `/research/llm` | `server/auth.py` |
| `/quantlib/pricing/bs/*` | ✅ precio, griegas y volatilidad implícita (3 de 590 rutas) | `server/analytics.py` |
| DataHub + TopicPolicy + Producers | ✅ asyncio, expuesto por WebSocket `/ws` | `server/datahub.py`, `server/main.py` |
| NewsService (RSS, dedupe, sentimiento) | ✅ Yahoo Finance + MarketWatch | `server/news.py` |
| Macro (conector DBnomics) | ✅ Fed, BCE, paro, IPC, PIB y búsqueda | `server/macro.py` |
| PaperTrading + OrderMatcher | ✅ market/limit/stop, P&L, sin cortos | `server/paper.py` |
| Backtesting (motor de Fincept) | ✅ sin look-ahead (ejecución en la siguiente apertura), comisión + slippage, benchmark alineado, Monte Carlo, validación hold-out y walk-forward | `server/backtest.py` |
| McpProvider (catálogo de tools) | ✅ 25 tools + 8 meta-tools | `server/tools.py` |
| McpHttpServer (todo lo de §1.3) | ✅ incluida la aprobación por llamada; revisado con la skill mcp-builder: anotaciones completas, `structuredContent`, `response_format` json/markdown, paginación, errores accionables, límite de 120 llamadas/min | `server/mcp_server.py` |
| AI Chat + ToolDispatcher | ✅ Claude con *tool use*, o un agente offline determinista | `server/ai_chat.py` |
| UI Qt (tema Obsidian, barra de comandos, F1–F12, ticker, paneles) | ✅ web, sin dependencias | `web/` |

**Comprobado:** el puente stdio **original** de Fincept (`fincept-qt/scripts/mcp/fincept_mcp_stdio.py`, sin modificar) funciona contra esta réplica: `initialize`, `tools/list`, `tools/call` y los rechazos por política.

---

## 2b. Fondo de IA multi-agente (pantalla FUND, comando `FUND`)

Un equipo de agentes que funciona como un comité de inversión sobre un universo global multi-activo: renta variable de EE. UU., Europa, Japón, emergentes y España; bonos; oro, plata y petróleo; dólar, euro y yen; y cripto. **Opera solo en la cuenta paper (dinero simulado).**

| Agente | Qué hace | Skill de la que aprende |
|---|---|---|
| Estratega macro | Régimen (expansivo/neutro/defensivo) con regla de Sahm, Fed Funds e inflación (DBnomics) | `macro-rates-monitor` |
| Analista de sentimiento | Tono de los titulares; descarta los que parecen inyección de instrucciones | `llm-trading-agent-security` |
| Analistas por mesa | Tendencia, momentum, RSI, volatilidad y drawdown de cada activo | `equity-research`, `yfinance-data` |
| Investigador cuant | Elige entre 7 estrategias con datos in-sample y la valida en el 30 % reservado; si falla, su peso se reduce a la mitad | `backtesting-frameworks` |
| CIO | Cartera por convicción × confianza × régimen × paridad de riesgo; con Claude redacta el acta, **sin poder cambiar nada** | `claude-api` |
| Gestor de riesgos (veto) | Límites por activo y mesa, volatilidad objetivo 10 %, caja mínima 5 %, sin apalancamiento ni cortos, cortacircuitos (drawdown 10 % o 3 ciclos en pérdidas) | `llm-trading-agent-security` |
| Trader | Órdenes con banda de rebalanceo, rotación máx. 30 % por ciclo, ventas primero y compras por convicción | `llm-trading-agent-security` |

**Aprendizaje:** cada ciclo guarda sus opiniones; el siguiente las compara con lo que hizo el mercado y sube o baja la confianza de cada mesa (0,5–1,5). La estrategia de cada activo se reelige con los datos nuevos.

**Ejecución:** el comité solo **propone**. Para ejecutar hace falta el botón de aprobar (la propuesta caduca a los 15 minutos), la tool MCP `fund_execute_run` (con permiso de acciones y aprobación en la terminal) o el **autopiloto**, que hay que activar a mano (mínimo cada 15 minutos). La **parada de emergencia** bloquea las compras y apaga el autopiloto. Todo ciclo queda auditado en `fund_runs`, también lo bloqueado y lo rechazado.

### Base de conocimiento (papers, investigación y código)

Toda la información está junta en una sola base: los 36 papers que respaldan las reglas del fondo, los 43 papers de quant-finance-research y las 39 funciones de `quantfin`, fusionados sin duplicados en **83 entradas**. Cada entrada dice qué idea aporta y en qué parte del código se usa. Está en tres sitios:

- **`docs/BASE_DE_CONOCIMIENTO.md`**: el documento completo, por tema, más el catálogo de funciones (se regenera con `python -m server.fund.research`; un test avisa si queda desactualizado).
- **Pantalla FUND**, panel *Base de conocimiento*, con filtro de texto; y `GET /fund/research`.
- **`GET /fund/research/functions`** y la tool `qf_catalog`: cada función con parámetros, salidas, papers y un ejemplo listo para correr.

Las referencias del fondo incluyen clásicos (Jegadeesh y Titman 1993; Moskowitz, Ooi y Pedersen 2012; Bailey y López de Prado 2014…) y trabajos de 2024–2026 sobre agentes LLM (TradingAgents 2024, FinCon 2024, HedgeAgents 2025, Miyazaki et al. 2026, Huang et al. 2026). Un test comprueba que cada entrada apunta a funciones que existen en el código.

Qué cambió en el código por esa investigación:
- **Deflated Sharpe Ratio** (Bailey y López de Prado 2014): el cuant elige entre varias estrategias (hoy 7), y eso infla el Sharpe de la ganadora. Ahora una estrategia solo queda *validada* si su DSR ≥ 0,5 **y** su Sharpe fuera de muestra es > 0; su confianza es 0,5, 0,75 o 1,0.
- **Momentum de series temporales a 12 meses** (Moskowitz et al. 2012; Hurst et al. 2017), como quinta estrategia del playbook.
- **Estado de pánico** (Daniel y Moskowitz 2016): tras una caída > 20 % con la volatilidad disparada, el momentum pesa la mitad.
- **Debate alcista/bajista por activo** (TradingAgents 2024) con **desacuerdo medido y preservado** (Huang et al. 2026: la "convergencia complaciente" empeora el Sharpe; preservar el desacuerdo lo mejora).
- **Objetivo de volatilidad solo como techo** (DeMiguel et al. 2024: las carteras gestionadas por volatilidad de un solo factor fallan fuera de muestra y con costes).
- **El LLM no decide ni entra en los backtests** (Glasserman y Lin 2023: sesgo de anticipación en señales de LLM; Greshake et al. 2023: inyección indirecta de instrucciones).

### Librería `quantfin` (quant-finance-research, Agustín Ortega)

`quantfin/` es la librería de la investigación *quant-finance-research* (39 funciones en `mercados.py` y `avanzados.py`, solo numpy y scipy), copiada sin cambios junto con sus 21 tests (`tests/test_quantfin.py`). El documento de investigación, el índice de 43 papers y la demo están en `docs/quantfin/`.

Dónde la usa el fondo:
- **Burbujas** (Phillips, Shi y Yu 2015): `sadf` sobre el último año de cada activo; si supera 1,5 el peso máximo del activo baja a la mitad y entra como argumento bajista en el debate. El umbral 1,5 es una aproximación, no un valor crítico simulado para cada muestra.
- **Fragilidad sistémica** (Kritzman et al. 2011): `absorption_ratio` sobre el universo; z ≥ 1 vuelve el régimen más defensivo.
- **Paridad de riesgo con covarianza real** (`risk_parity`), con reparación de Higham (2002) si la matriz de correlación no es válida.
- **Volatilidad de la cartera corregida** por el sesgo del optimizador (Pafka y Kondor 2003) antes de compararla con el objetivo del 10 %.
- **Dos estrategias nuevas** en el playbook: `ema_20_100` y `donchian_20` (Brock et al. 1992; Levine y Pedersen 2016). El Deflated Sharpe ya penaliza el mayor número de pruebas.
- **Impacto de mercado** (ley de la raíz cuadrada): cada orden muestra su coste estimado en puntos básicos y se recorta si pasa de 50 pb. (Bonart 2026, arXiv 2606.07059).

Tools (por MCP, en el chat y en el panel **Laboratorio quantfin** de QUANTLIB):
- 9 sobre datos de mercado: `qf_bubble_test`, `qf_systemic_fragility`, `qf_pairs_ou`, `qf_risk_parity`, `qf_execution_plan`, `qf_yield_curve`, `qf_bond`, `qf_kelly_binary`, `qf_market_making`.
- **`qf_function`**: ejecuta cualquiera de las 39 funciones con los números que le pases (opciones, bonos, carry de divisas, basis de materias primas, TSMOM, DeFi, mercados de predicción, VaR/ES, GARCH, mínima varianza, OU, SADF, Deflated Sharpe, Higham…). Sin argumentos corre el ejemplo del catálogo. Los vectores y bucles tienen límites para no bloquear el servidor.
- **`qf_catalog`**: lista y busca las funciones.

La pantalla FUND muestra el absorption ratio, las burbujas detectadas y el presupuesto de riesgo en el acta, y el impacto estimado de cada orden.

## 3. Arranque

Requiere Python 3.10 o superior.

```bash
cd fincept-lite
./run.sh                                  # crea .venv la primera vez
FINCEPT_DATA_MODE=sim ./run.sh            # sin red: mercado simulado
ANTHROPIC_API_KEY=sk-ant-… ./run.sh       # chat IA con Claude (Opus 5.5, tool use)
```

| Variable | Por defecto | Efecto |
|---|---|---|
| `FINCEPT_PORT` | `41800` | Puerto (distinto del 41720 del terminal real para poder usar ambos a la vez) |
| `FINCEPT_DATA_MODE` | `live` | `live` = Yahoo/RSS/DBnomics con respaldo al simulador; `sim` = todo simulado |
| `FINCEPT_DEV` | `1` | Devuelve el OTP en la respuesta y crea el usuario demo. **Ponlo a `0` fuera de local.** |
| `FINCEPT_AI` | — | `offline` fuerza el agente sin LLM |
| `FINCEPT_AI_MODEL` / `FINCEPT_AI_EFFORT` | `claude-opus-5-5` / `medium` | Modelo y esfuerzo del chat |
| `FINCEPT_MCP_GRACE` | `8` | Segundos antes de que una tool larga pase a ser un job |

Si Yahoo responde **429** (ocurre desde IPs compartidas o de la nube), el proveedor se pausa con *backoff* exponencial y las cotizaciones salen del simulador. La UI lo indica con la insignia `YAHOO PAUSADO · SIM` y con una etiqueta `SIM` en cada precio. Nunca se muestran datos simulados como si fueran reales.

## 4. Conectar un agente por MCP

Entra en la pestaña **F11 MCP**: muestra la URL y el token, y genera los comandos listos para copiar:

```bash
claude mcp add --transport http fincept http://127.0.0.1:41800/mcp -H "Authorization: Bearer fmcp_…" -s user
```

Desde ahí también se activan las acciones (órdenes, watchlists), se cambia el toolset (essentials/full), se ve la actividad en vivo y se pueden enviar peticiones JSON-RPC desde una consola. Cuando un agente llama a `pt_place_order`, el terminal abre un diálogo de aprobación.

## 5. Pantallas y comandos

`F1` Dashboard · `F2` Mercados · `F3` Noticias · `F4` Cartera paper · `F5` Backtest (SMA sin look-ahead, costes, Monte Carlo, hold-out y walk-forward) · `F6` Watchlists · `F7` QuantLib (Black-Scholes, VaR) · `F8` Macro · `F9` Ficha del activo · `F10` Chat IA · `F11` MCP · `F12` Perfil e inspector del DataHub.

Barra de comandos (`/` o `Ctrl+K`): `AAPL` · `SAN.MC GO` · `BUY 10 NVDA` · `SELL 5 MSFT @ 420` · `BUY 1 TSLA STOP 300` · `AI ¿cómo va el IBEX?` · `NEWS` · `HELP`.

## 6. Tests

```bash
.venv/bin/python -m pytest -q      # 155 tests: auth, /v1, mercado, paper, DataHub, MCP (+ cliente oficial del SDK), backtesting, fondo multi-agente, investigación, quantfin, analítica, chat
```

### Evaluación del servidor MCP

`evals/fincept_lite_eval.xml` contiene 10 preguntas de solo lectura con respuesta estable (series históricas de DBnomics, cálculos Black-Scholes y la política de las tools), verificadas contra el servidor. Se ejecutan con el arnés de la skill `mcp-builder`, que necesita una clave de Anthropic y el SDK de MCP **1.x** (el script importa `streamablehttp_client`, que ya no existe en `mcp` 2.x):

```bash
python3 -m venv /tmp/evalenv && /tmp/evalenv/bin/pip install "mcp<2" anthropic
FINCEPT_DATA_MODE=live ./run.sh &          # las preguntas usan DBnomics en vivo
ANTHROPIC_API_KEY=sk-ant-… /tmp/evalenv/bin/python ../.claude/skills/mcp-builder/scripts/evaluation.py \
  -t http -u http://127.0.0.1:41800/mcp -H "Authorization: Bearer fmcp_…" -m claude-opus-5-5 \
  evals/fincept_lite_eval.xml
```

El token sale de la pestaña F11. Pasa `-m` explícitamente: el script trae por defecto un modelo antiguo.

## 7. Límites y diferencias

- El backend de Fincept es **cerrado**. Esta réplica reproduce sus **contratos** (rutas, cabeceras, formas de respuesta, mensajes y políticas), no su código interno.
- No se replican las fuentes con licencia (CEIC, TradingEconomics, AIS marítimo), los pagos (Cashfree), el LLM propio de Fincept ni los brokers reales. QuantLib se limita a Black-Scholes y a métricas de riesgo.
- Un solo proceso con SQLite y estado de MCP y chat en memoria. Está pensado para uso local y para aprender, no para producción multiusuario.
- Paper trading con dinero ficticio. **Nada de esto es asesoramiento de inversión.**
