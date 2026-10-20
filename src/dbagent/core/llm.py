"""Talk to a Large Language Model (LLM) through an OpenAI-compatible API.

Many providers (Google Gemini, Groq, Ollama, OpenAI...) accept the same request
format, so one client works with all of them. Only three settings change:
base URL, API key and model name.
"""

import json

import openai


class LLMError(Exception):
    """Raised when the LLM cannot be reached or gives an unusable answer."""


class LLMClient:
    """Sends prompts to an LLM and returns its answer."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout_s: float = 60.0):
        self.model = model
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s)

    def ask(self, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
        """Send one question and return the answer text."""
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
            )
        except openai.AuthenticationError as error:
            raise LLMError("The API key was rejected. Check LLM_API_KEY in .env.") from error
        except openai.RateLimitError as error:
            raise LLMError("Rate limit reached. Wait a minute and try again.") from error
        except openai.APIConnectionError as error:
            raise LLMError("Could not reach the LLM. Check LLM_BASE_URL and your network.") from error
        except openai.APIError as error:
            raise LLMError(f"The LLM API returned an error: {error}") from error

        text = response.choices[0].message.content
        if not text:
            raise LLMError("The LLM returned an empty answer.")
        return text

    def ask_json(self, system_prompt: str, user_prompt: str) -> dict:
        """Send one question and return the answer parsed as a JSON object."""
        return extract_json(self.ask(system_prompt, user_prompt))

    def list_models(self) -> list[str]:
        """Names of the models this API key can use."""
        try:
            return sorted(model.id for model in self._client.models.list())
        except openai.APIError as error:
            raise LLMError(f"Could not list models: {error}") from error


def extract_json(text: str) -> dict:
    """Find and parse the JSON object inside an LLM answer.

    LLMs often wrap JSON in ```json fences or add a sentence around it,
    so we take the text from the first '{' to the last '}'.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end < start:
        raise LLMError(f"No JSON object found in the answer: {text[:200]!r}")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise LLMError(f"The answer is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise LLMError("Expected a JSON object { ... }.")
    return data