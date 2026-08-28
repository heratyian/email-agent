"""Offline evaluations for model-backed email workflows."""

from email_agent.evaluations.classification import run_classification_evaluation
from email_agent.evaluations.drafting import run_drafting_evaluation
from email_agent.evaluations.search import run_search_evaluation

__all__ = [
    "run_classification_evaluation",
    "run_drafting_evaluation",
    "run_search_evaluation",
]
