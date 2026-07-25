from collections.abc import Callable
from datetime import datetime

def get_time() -> str:
    """Get the current local time. Call this when the user asks what time it is."""
    return str(datetime.now().astimezone())

available_tools: list[Callable] = [get_time]
REGISTRY: dict[str, Callable] = {f.__name__: f for f in available_tools}