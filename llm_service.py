"""Phase 1 only: load settings and explicitly test API connectivity.

No document answering, retrieval, or model-output repair is implemented here yet.
"""

import argparse
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parent / ".env"
SMOKE_MARKER = "NAVIGAITE_OK"


class ConfigurationError(ValueError):
    """A safe configuration message that never includes setting values."""


class ConnectionCheckError(RuntimeError):
    """A safe setup error, not a document's NOT_FOUND answer."""


@dataclass(frozen=True)
class LLMSettings:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    context_tokens: int
    max_output_tokens: int
    timeout_seconds: float


def load_settings(env_file: Path = ENV_FILE) -> LLMSettings:
    """Read this project's .env; existing environment variables take priority."""
    try:
        # Do not search parent folders, mutate os.environ, or expand ${...}.
        file_values = dotenv_values(env_file, interpolate=False)
    except (OSError, UnicodeError):
        raise ConfigurationError("Cannot read the project's .env file.") from None

    def read(name: str, default: str | None = None) -> str:
        value = os.environ.get(name, file_values.get(name, default))
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"{name} is required and cannot be blank.")
        value = value.strip()
        if value.lower().startswith(("replace_", "your_", "paste_", "<")):
            raise ConfigurationError(f"Replace the placeholder for {name}.")
        if value.lower() in {"changeme", "change_me", "placeholder"}:
            raise ConfigurationError(f"Replace the placeholder for {name}.")
        return value

    def positive_integer(name: str, default: str | None = None) -> int:
        value = read(name, default)
        if not value.isascii() or not value.isdecimal():
            raise ConfigurationError(f"{name} must be a positive whole number.")
        try:
            number = int(value)
        except ValueError:
            raise ConfigurationError(f"{name} is not a usable whole number.") from None
        if number <= 0:
            raise ConfigurationError(f"{name} must be greater than zero.")
        return number

    api_key = read("LLM_API_KEY")
    base_url = read("LLM_BASE_URL").rstrip("/")
    model = read("LLM_MODEL")
    if any(character.isspace() for character in api_key):
        raise ConfigurationError("LLM_API_KEY must not contain whitespace.")
    if any(character.isspace() for character in model):
        raise ConfigurationError("LLM_MODEL must be a model identifier without spaces.")

    try:
        url = urlsplit(base_url)
        _ = url.port  # Validate malformed or out-of-range ports too.
        valid_url = (
            url.scheme == "https" and bool(url.hostname)
            and not url.username and not url.password
            and not url.query and not url.fragment
            and not any(character.isspace() for character in base_url)
        )
    except ValueError:
        valid_url = False
    if not valid_url:
        raise ConfigurationError(
            "LLM_BASE_URL must be an HTTPS base URL without credentials, query, or fragment."
        )
    if base_url.endswith("/chat/completions"):
        raise ConfigurationError("LLM_BASE_URL must not include /chat/completions.")

    context_tokens = positive_integer("LLM_CONTEXT_TOKENS")
    max_output_tokens = positive_integer("LLM_MAX_OUTPUT_TOKENS", "1200")
    if max_output_tokens >= context_tokens:
        raise ConfigurationError(
            "LLM_MAX_OUTPUT_TOKENS must be smaller than LLM_CONTEXT_TOKENS."
        )
    try:
        timeout_seconds = float(read("LLM_TIMEOUT_SECONDS", "30"))
    except ValueError:
        raise ConfigurationError("LLM_TIMEOUT_SECONDS must be a positive number.") from None
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ConfigurationError("LLM_TIMEOUT_SECONDS must be a positive finite number.")

    return LLMSettings(
        api_key=api_key,
        base_url=base_url,
        model=model,
        context_tokens=context_tokens,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
    )


def run_smoke_test(settings: LLMSettings) -> None:
    """Make one tiny request only when explicitly requested. May use API credits."""
    # Lazy import: schemas and local configuration checks need no API client.
    try:
        import openai
    except ImportError:
        raise ConnectionCheckError(
            "Install requirements.txt before running the live API check."
        ) from None

    try:
        with openai.OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            max_retries=0,
        ) as client:
            response = client.chat.completions.create(
                model=settings.model,
                messages=[
                    {"role": "system", "content": "Copy only the text after DATA: exactly."},
                    {"role": "user", "content": f"DATA: {SMOKE_MARKER}"},
                ],
                temperature=0,
                max_tokens=min(32, settings.max_output_tokens),
                stream=False,
            )
    except openai.APITimeoutError:
        raise ConnectionCheckError("The API check timed out. No automatic retry was made.") from None
    except openai.APIConnectionError:
        raise ConnectionCheckError("Cannot reach the configured API. Check the network and base URL.") from None
    except openai.APIStatusError as error:
        messages = {
            400: "The endpoint rejected the request format or model parameters.",
            401: "The API rejected the key. Check LLM_API_KEY locally.",
            403: "The API denied access to this model or account.",
            404: "The API endpoint or model was not found.",
            429: "The API rate or usage limit was reached.",
        }
        message = messages.get(error.status_code, "The API returned an unsuccessful response.")
        raise ConnectionCheckError(message) from None
    except Exception:
        # Never expose a provider response body, key, or raw exception to the UI.
        raise ConnectionCheckError("The API check failed. Check the installed client and endpoint settings.") from None

    if not response.choices:
        raise ConnectionCheckError("The API returned no completion choices.")
    choice = response.choices[0]
    if choice.finish_reason != "stop":
        raise ConnectionCheckError("The API did not complete the small test normally.")
    if choice.message.content is None or choice.message.content.strip() != SMOKE_MARKER:
        raise ConnectionCheckError("The API responded, but did not return the expected test text.")


def main() -> int:
    parser = argparse.ArgumentParser(description="NavigAIte Phase 1 setup checks")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-config", action="store_true", help="Check local settings; no API call.")
    mode.add_argument("--smoke-test", action="store_true", help="Make one live API request; may use credits.")
    args = parser.parse_args()

    try:
        settings = load_settings()
        print("CONFIG OK: required settings are present and locally valid.")
        print("This does not verify the model's actual context limit or access.")
        if args.smoke_test:
            run_smoke_test(settings)
            print("SMOKE TEST PASSED: the endpoint returned NAVIGAITE_OK.")
            print("Structured output and token-counting support remain unverified.")
        else:
            print("No API request was made.")
    except (ConfigurationError, ConnectionCheckError) as error:
        print(f"SETUP ERROR: {error}")
        return 1
    except Exception:
        print("SETUP ERROR: an unexpected setup failure occurred; no raw details are displayed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
