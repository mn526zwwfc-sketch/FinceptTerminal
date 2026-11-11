# fincept-fondo

Equipo de inversión del fondo Fincept como subagentes de Claude Code: estratega macro, analista de sentimiento, analistas por mesa, investigador cuant, CIO, gestor de riesgos y trader, cada uno con sus skills, sus papers y su código, más la skill comite-fincept que los coordina.

## Agentes

| Subagente | Rol | Skills | Papers |
|---|---|---|---|
| `fincept-estratega-macro` | Estratega macro | macro-rates-monitor, economic-calendar-fetcher | 8 |
| `fincept-analista-sentimiento` | Analista de sentimiento | llm-trading-agent-security | 12 |
| `fincept-analistas-mesa` | Analistas por mesa | equity-research, yfinance-data, option-vol-analysis | 20 |
| `fincept-investigador-cuant` | Investigador cuant | backtesting-frameworks | 21 |
| `fincept-cio` | CIO | — | 7 |
| `fincept-gestor-riesgos` | Gestor de riesgos | backtesting-frameworks, option-vol-analysis, llm-trading-agent-security | 21 |
| `fincept-trader` | Trader | llm-trading-agent-security | 2 |

Cada subagente trae en su definición su misión, su método, su entregable, sus papers (de la base de conocimiento de Fincept Lite), sus funciones de `quantfin` y el código del fondo que le corresponde. Trabajan sobre el repositorio FinceptTerminal (`fincept-lite/`) y obtienen sus datos con `python -m server.fund.team <rol>`, que convoca el comité en paper sin tocar ninguna cuenta.

## Uso

- «Convoca el comité» activa la skill `comite-fincept`: acta del día, equipo de investigación en paralelo, comité de inversión y acta final.
- También puedes llamar a un agente suelto: «pídele a fincept-gestor-riesgos que revise la cartera» (en Claude Code se llama `fincept-fondo:fincept-gestor-riesgos`).

Ningún agente aprueba ni envía órdenes reales: eso lo hace la persona en la terminal.

## Instalación

    /plugin marketplace add mn526zwwfc-sketch/FinceptTerminal
    /plugin install fincept-fondo@fincept

Se regenera con `cd fincept-lite && .venv/bin/python -m server.fund.build_plugin`.

## Skills incluidas y su origen

- `backtesting-frameworks`: wshobson/agents (MIT)
- `economic-calendar-fetcher`: tradermonty/claude-trading-skills
- `equity-research`: anthropics/financial-services
- `llm-trading-agent-security`: affaan-m/everything-claude-code (MIT)
- `macro-rates-monitor`: anthropics/financial-services
- `option-vol-analysis`: anthropics/financial-services
- `yfinance-data`: anthropics/financial-services

Cada skill conserva su licencia y su autoría originales.
