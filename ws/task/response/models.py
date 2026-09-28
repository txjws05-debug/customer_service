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

    @classmethod
    def from_dict(cls, template_data: dict) -> "ResponseTemplate":
        return cls(
            mode=ResponseMode(template_data['mode'])
            if 'mode' in template_data else ResponseMode.STATIC,
            text=template_data.get('text'),
            prompt=template_data.get('prompt')
        )