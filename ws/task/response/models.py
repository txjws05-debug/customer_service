from dataclasses import dataclass
from enum import Enum
class ResponseMode(Enum):
    STATIC="static"
    REPHRASE="rephrase"
    GENERATE="generate"
@dataclass
class ResponseTemplate:
    mode: ResponseMode=ResponseMode.STATIC
    text: str| None = None
    prompt: str | None = None
