from pathlib import Path

def load_prompt(name: str) -> str:
    file =Path(__file__).parent/'jinjia2'/f'{name}.jinjia2'
    return file.read_text(encoding='utf-8')