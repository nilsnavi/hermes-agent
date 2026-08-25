"""Time-independent canary idempotency binding."""
from .models import ProductionCanaryRequest
def semantic_canary_key(request:ProductionCanaryRequest)->str:return request.semantic_key()
