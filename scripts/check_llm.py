"""Check that the LLM settings in .env work.

Usage:
    python scripts/check_llm.py --models   # list models your API key can use
    python scripts/check_llm.py            # ask a test question, expect JSON back
"""

import sys

from dbagent.core.config import load_llm_settings
from dbagent.core.llm import LLMClient, LLMError, extract_json

SYSTEM_PROMPT = "You are a helpful assistant. Reply ONLY with a JSON object and no other text."
USER_PROMPT = (
    'What is 17 + 25? Reply as {"answer": <number>, "explanation": "<one short sentence>"}'
)


def main() -> None:
    settings = load_llm_settings()
    llm = LLMClient(settings.base_url, settings.api_key, settings.model)

    try:
        if "--models" in sys.argv:
            for name in llm.list_models():
                print(name)
            return

        print(f"Asking model '{settings.model}'...")
        raw_answer = llm.ask(SYSTEM_PROMPT, USER_PROMPT)
        print("\nRaw answer from the LLM:")
        print(raw_answer)
        print("\nParsed as JSON:")
        print(extract_json(raw_answer))
    except LLMError as error:
        print(f"LLM problem: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()