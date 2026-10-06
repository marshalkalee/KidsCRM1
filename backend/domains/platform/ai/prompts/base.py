from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTemplate:
    key: str
    version: str
    system: str
    schema: dict
    fixture: dict
    validate: Callable[[dict, dict], dict]
    max_tokens: int = 2500
