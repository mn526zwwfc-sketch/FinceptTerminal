"""Corre los ejemplos de ambos módulos: python examples/demo.py"""
import runpy
from pathlib import Path

src = Path(__file__).resolve().parents[2] / "quantfin"  # fincept-lite/quantfin
for modulo in ["mercados.py", "avanzados.py"]:
    print(f"\n===== {modulo} =====")
    runpy.run_path(str(src / modulo), run_name="__main__")
