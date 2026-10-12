"""
quant_evidence — the academic-quant literature review "La academia quant desinfla
sus propias estrategias" as structured data, the statistics it relies on, and a decision evaluator.

    from quant_evidence import evaluate_decision
    evaluate_decision({'strategy_id': 'momentum', 'sharpe_annual': 1.2,
                       'years': 8, 'n_trials': 50})
"""

from .evaluator import evaluate_decision, resolve_inputs
from .knowledge_base import get_strategy, list_strategies, load_kb, load_repo_map, organize
from . import stats

__all__ = ['evaluate_decision', 'resolve_inputs', 'get_strategy', 'list_strategies',
           'load_kb', 'load_repo_map', 'organize', 'stats']
