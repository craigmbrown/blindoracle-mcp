"""
LLM Router Client — thin import wrapper so all signal intelligence modules
can call router.route(task_type, prompt) without knowing where the router lives.

Usage:
    from chainlink-prediction-markets-mcp-enhanced.core.llm_router_client import get_router
    router = get_router()
    result = router.route("entity_extraction", "SEC delays ETH ETF...")
    print(result["content"])   # LLM response
    print(result["actual_model"])  # e.g. "groq/llama-3.1-8b-instant"
    print(result["cost_usd"])
"""

import sys
from pathlib import Path

# Make sure the ETAC module path is on sys.path
_ETAC_PATH = Path("/home/craigmbrown/Project/ETAC/workspace/ETAC-System")
if str(_ETAC_PATH) not in sys.path:
    sys.path.insert(0, str(_ETAC_PATH))

_PROJECT_PATH = Path("/home/craigmbrown/Project")
if str(_PROJECT_PATH) not in sys.path:
    sys.path.insert(0, str(_PROJECT_PATH))

_router_instance = None


def get_router():
    """Return singleton EnhancedLLMRouter instance."""
    global _router_instance
    if _router_instance is None:
        from adws.adw_modules.llm_router_enhanced import EnhancedLLMRouter
        _router_instance = EnhancedLLMRouter()
    return _router_instance
