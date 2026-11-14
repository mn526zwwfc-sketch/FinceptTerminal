"""Universo de mercados de la terminal: clases de activo, regiones e instrumentos (símbolos de Yahoo Finance)."""

from __future__ import annotations

CLASSES: list[dict] = [
    {"id": "indices", "code": "MON", "name": "Índices mundiales", "groups": [
        ("Américas", [("^GSPC", "S&P 500"), ("^DJI", "Dow Jones"), ("^IXIC", "Nasdaq Composite"),
                      ("^RUT", "Russell 2000"), ("^GSPTSE", "S&P/TSX Canadá"), ("^MXX", "S&P/BMV IPC México"),
                      ("^BVSP", "Bovespa Brasil")]),
        ("Europa", [("^STOXX50E", "Euro Stoxx 50"), ("^FTSE", "FTSE 100"), ("^GDAXI", "DAX"), ("^FCHI", "CAC 40"),
                    ("^IBEX", "IBEX 35"), ("^SSMI", "SMI Suiza")]),
        ("Asia-Pacífico", [("^N225", "Nikkei 225"), ("^HSI", "Hang Seng"), ("000001.SS", "Shanghái Composite"),
                           ("^BSESN", "Sensex India"), ("^AXJO", "S&P/ASX 200"), ("^KS11", "KOSPI")]),
        ("Volatilidad", [("^VIX", "VIX")]),
    ]},
    {"id": "acciones", "code": "ACC", "name": "Acciones", "groups": [
        ("Estados Unidos", [("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "Nvidia"), ("AMZN", "Amazon"),
                            ("GOOGL", "Alphabet"), ("META", "Meta Platforms"), ("TSLA", "Tesla"),
                            ("BRK-B", "Berkshire Hathaway"), ("JPM", "JPMorgan Chase"), ("XOM", "Exxon Mobil"),
                            ("LLY", "Eli Lilly"), ("WMT", "Walmart")]),
        ("México", [("AMXB.MX", "América Móvil"), ("WALMEX.MX", "Walmart de México"), ("GFNORTEO.MX", "Banorte"),
                    ("FEMSAUBD.MX", "FEMSA"), ("CEMEXCPO.MX", "Cemex"), ("GMEXICOB.MX", "Grupo México")]),
        ("Europa", [("ASML", "ASML"), ("SAP", "SAP"), ("NVO", "Novo Nordisk"), ("SAN.MC", "Banco Santander"),
                    ("ITX.MC", "Inditex")]),
        ("Asia", [("TSM", "TSMC"), ("BABA", "Alibaba"), ("TM", "Toyota")]),
    ]},
    {"id": "divisas", "code": "FX", "name": "Divisas", "groups": [
        ("Principales", [("EURUSD=X", "EUR/USD"), ("USDJPY=X", "USD/JPY"), ("GBPUSD=X", "GBP/USD"),
                         ("USDCHF=X", "USD/CHF"), ("AUDUSD=X", "AUD/USD"), ("USDCAD=X", "USD/CAD"),
                         ("DX-Y.NYB", "Índice dólar (DXY)")]),
        ("Peso mexicano", [("USDMXN=X", "USD/MXN"), ("EURMXN=X", "EUR/MXN")]),
        ("Emergentes", [("USDBRL=X", "USD/BRL"), ("USDCNY=X", "USD/CNY"), ("USDINR=X", "USD/INR")]),
    ]},
    {"id": "tasas", "code": "TAS", "name": "Tasas y renta fija", "groups": [
        ("Rendimientos del Tesoro de EE. UU.", [("^IRX", "Letra 13 semanas"), ("^FVX", "Nota 5 años"),
                                                 ("^TNX", "Nota 10 años"), ("^TYX", "Bono 30 años")]),
        ("ETF de renta fija", [("SHY", "Tesoro 1-3 años"), ("IEF", "Tesoro 7-10 años"), ("TLT", "Tesoro 20+ años"),
                               ("TIP", "Tesoro ligado a inflación"), ("LQD", "Corporativo grado de inversión"),
                               ("HYG", "Corporativo alto rendimiento"), ("EMB", "Soberano emergente en USD")]),
    ]},
    {"id": "materias", "code": "MAT", "name": "Materias primas", "groups": [
        ("Metales", [("GC=F", "Oro"), ("SI=F", "Plata"), ("HG=F", "Cobre"), ("PL=F", "Platino")]),
        ("Energía", [("CL=F", "Petróleo WTI"), ("BZ=F", "Petróleo Brent"), ("NG=F", "Gas natural")]),
        ("Agrícolas", [("ZC=F", "Maíz"), ("ZW=F", "Trigo"), ("ZS=F", "Soya"), ("KC=F", "Café"), ("SB=F", "Azúcar")]),
    ]},
    {"id": "cripto", "code": "CRI", "name": "Criptoactivos", "groups": [
        ("Principales", [("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana"),
                         ("BNB-USD", "BNB"), ("XRP-USD", "XRP"), ("ADA-USD", "Cardano"), ("DOGE-USD", "Dogecoin")]),
    ]},
    {"id": "etf", "code": "ETF", "name": "ETF del fondo", "groups": [
        ("Renta variable", [("SPY", "S&P 500"), ("QQQ", "Nasdaq 100"), ("VGK", "Europa"), ("EWJ", "Japón"),
                            ("EEM", "Emergentes"), ("EWP", "España"), ("EWW", "México")]),
        ("Renta fija", [("TLT", "Tesoro 20+ años"), ("IEF", "Tesoro 7-10 años")]),
        ("Materias primas", [("GLD", "Oro"), ("SLV", "Plata"), ("USO", "Petróleo")]),
        ("Divisas", [("UUP", "Dólar"), ("FXE", "Euro"), ("FXY", "Yen")]),
    ]},
]
YIELDS = {"^IRX": 0.25, "^FVX": 5.0, "^TNX": 10.0, "^TYX": 30.0}  # índice de rendimiento → plazo en años
BENCHMARK = "^GSPC"
BY_ID = {c["id"]: c for c in CLASSES}


def symbols(cls: str) -> list[tuple[str, str, str]]:
    """[(símbolo, nombre, grupo)] de una clase."""
    return [(s, n, g) for g, items in BY_ID[cls]["groups"] for s, n in items]


def find(symbol: str) -> dict | None:
    """Primera clase en la que aparece el símbolo."""
    for c in CLASSES:
        for g, items in c["groups"]:
            for s, n in items:
                if s == symbol:
                    return {"class": c["id"], "class_name": c["name"], "group": g, "name": n}
    return None


def all_symbols() -> list[str]:
    return list(dict.fromkeys(s for c in CLASSES for s, _, _ in symbols(c["id"])))
