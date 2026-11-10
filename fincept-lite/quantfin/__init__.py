"""quantfin: modelos cuantitativos por mercado (investigación nov 2026).

- quantfin.mercados: modelos base por mercado (derivados, acciones, renta fija, FX,
  commodities, microestructura, DeFi, mercados de predicción, riesgo y portafolio).
- quantfin.avanzados: modelos de los papers citados por @vince.quant (OU, SADF,
  absorption ratio, Deflated Sharpe, Higham, diversity-weighted, tendencia, impacto).
"""
from . import mercados, avanzados

__all__ = ["mercados", "avanzados"]
__version__ = "0.1.0"
