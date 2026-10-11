"""Phase 1 tests. All network behavior is simulated; no real key is needed."""

import importlib.util
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

import llm_service
from llm_service import ConfigurationError, ConnectionCheckError, load_settings
from schemas import CitedItem, DocumentData, PageSource, PolicyResponse

DOCUMENT_ID = "a" * 64
FAKE_KEY = "unit-test-secret-not-a-real-key"
ENV_NAMES = (
    "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_CONTEXT_TOKENS",
    "LLM_MAX_OUTPUT_TOKENS", "LLM_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        f"LLM_API_KEY={FAKE_KEY}\n"
        "LLM_BASE_URL=https://example.org/v1\n"
        "LLM_MODEL=unit-test-model\n"
        "LLM_CONTEXT_TOKENS=8192\n",
        encoding="utf-8",
    )
    return path


def make_source(page=1, document_id=DOCUMENT_ID):
    return PageSource(
        source_id=f"{document_id}:p{page}", document_id=document_id,
        pdf_page=page, text="  Notify your supervisor.\n",
    )


def response_payload(status="ANSWERED"):
    return {
        "status": status,
        "answer": [{"text": "Notify your supervisor.", "source_ids": [f"{DOCUMENT_ID}:p1"]}],
        "steps": [], "policy_warnings": [], "missing_information": [],
        "clarification_question": None,
    }


def test_settings_defaults_and_key_redaction(env_file):
    settings = load_settings(env_file)
    assert settings.max_output_tokens == 1200
    assert settings.timeout_seconds == 30
    assert settings.context_tokens == 8192
    assert settings.api_key == FAKE_KEY
    assert FAKE_KEY not in repr(settings)


def test_environment_overrides_file(env_file, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "another-model")
    assert load_settings(env_file).model == "another-model"


def test_empty_environment_value_does_not_fall_back(env_file, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    with pytest.raises(ConfigurationError, match="LLM_API_KEY"):
        load_settings(env_file)


def test_project_path_does_not_search_parent_dotenv(env_file):
    child_path = env_file.parent / "child" / ".env"
    with pytest.raises(ConfigurationError, match="LLM_API_KEY"):
        load_settings(child_path)


@pytest.mark.parametrize("name", ENV_NAMES[:4])
def test_each_required_setting_is_required(env_file, name):
    lines = [line for line in env_file.read_text().splitlines() if not line.startswith(name + "=")]
    env_file.write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=name):
        load_settings(env_file)


@pytest.mark.parametrize("name,value", [
    ("LLM_API_KEY", "REPLACE_WITH_YOUR_API_KEY"),
    ("LLM_API_KEY", "key with spaces"),
    ("LLM_MODEL", "your_model"),
    ("LLM_MODEL", "model with spaces"),
    ("LLM_CONTEXT_TOKENS", "0"),
    ("LLM_CONTEXT_TOKENS", "-1"),
    ("LLM_CONTEXT_TOKENS", "8192.5"),
    ("LLM_CONTEXT_TOKENS", "not-a-number"),
    ("LLM_MAX_OUTPUT_TOKENS", "0"),
    ("LLM_MAX_OUTPUT_TOKENS", "8192"),
    ("LLM_MAX_OUTPUT_TOKENS", "8193"),
    ("LLM_TIMEOUT_SECONDS", "0"),
    ("LLM_TIMEOUT_SECONDS", "-1"),
    ("LLM_TIMEOUT_SECONDS", "nan"),
    ("LLM_TIMEOUT_SECONDS", "inf"),
    ("LLM_TIMEOUT_SECONDS", "bad-number"),
])
def test_invalid_settings_are_safe(env_file, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError) as caught:
        load_settings(env_file)
    assert name in str(caught.value)
    assert FAKE_KEY not in str(caught.value)


@pytest.mark.parametrize("url", [
    "http://example.org/v1", "not-a-url", "https:///v1",
    "https://user:password@example.org/v1", "https://example.org/v1?key=secret",
    "https://example.org/v1#fragment", "https://example.org:bad/v1",
    "https://example.org/v1/chat/completions",
])
def test_invalid_base_urls(env_file, monkeypatch, url):
    monkeypatch.setenv("LLM_BASE_URL", url)
    with pytest.raises(ConfigurationError, match="LLM_BASE_URL"):
        load_settings(env_file)


def test_original_source_text_is_preserved():
    assert make_source().text == "  Notify your supervisor.\n"


@pytest.mark.parametrize("page", [0, 21, "1", True])
def test_page_number_is_a_strict_one_based_integer(page):
    with pytest.raises(ValidationError):
        make_source(page)


def test_mismatched_source_id_is_rejected():
    data = make_source().model_dump()
    data["source_id"] = f"{DOCUMENT_ID}:p2"
    with pytest.raises(ValidationError):
        PageSource.model_validate(data)


def test_blank_page_does_not_renumber_later_pages():
    document = DocumentData(
        document_id=DOCUMENT_ID, filename="handbook.pdf", total_pages=3,
        sources=[make_source(1), make_source(3)], pages_without_text=[2],
    )
    assert [source.pdf_page for source in document.sources] == [1, 3]


@pytest.mark.parametrize("sources,missing", [
    ([make_source(1)], []),                     # Physical page 2 is unaccounted for.
    ([make_source(1)], [1, 2]),                 # Page 1 is recorded twice.
    ([make_source(2), make_source(1)], []),      # Sources are out of order.
    ([make_source(1, "b" * 64)], [2]),          # Evidence belongs to another file.
    ([make_source(1), make_source(1)], []),      # Duplicate source.
])
def test_invalid_document_coverage(sources, missing):
    with pytest.raises(ValidationError):
        DocumentData(
            document_id=DOCUMENT_ID, filename="handbook.pdf", total_pages=2,
            sources=sources, pages_without_text=missing,
        )


def test_supported_response_allows_empty_steps_and_warnings():
    result = PolicyResponse.model_validate(response_payload())
    assert result.status == "ANSWERED"
    assert result.steps == []
    assert result.policy_warnings == []
    assert PolicyResponse.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("ids", [[], [" "], ["source-1", "source-1"]])
def test_cited_items_need_nonblank_unique_references(ids):
    with pytest.raises(ValidationError):
        CitedItem(text="A policy claim.", source_ids=ids)


@pytest.mark.parametrize("field", ["pdf_page", "page_number", "filename"])
def test_llm_cannot_add_source_metadata_fields(field):
    payload = response_payload()
    payload[field] = 99
    with pytest.raises(ValidationError):
        PolicyResponse.model_validate(payload)
    with pytest.raises(ValidationError):
        CitedItem.model_validate({"text": "A claim.", "source_ids": ["source-1"], field: 99})


def test_valid_not_found_has_no_policy_claims():
    payload = response_payload("NOT_FOUND")
    payload["answer"] = []
    payload["missing_information"] = ["Pay eligibility is not established by the readable text."]
    assert PolicyResponse.model_validate(payload).status == "NOT_FOUND"


def test_valid_partial_answer():
    payload = response_payload("PARTIALLY_ANSWERED")
    payload["missing_information"] = ["Pay eligibility is not established."]
    assert PolicyResponse.model_validate(payload).status == "PARTIALLY_ANSWERED"


def test_valid_clarification():
    payload = response_payload("CLARIFICATION_NEEDED")
    payload["answer"] = []
    payload["clarification_question"] = "Is this a planned or unexpected absence?"
    assert PolicyResponse.model_validate(payload).status == "CLARIFICATION_NEEDED"


def test_conflict_can_occur_on_one_page():
    payload = response_payload("CONFLICT_DETECTED")
    payload["answer"].append({"text": "A conflicting statement.", "source_ids": [f"{DOCUMENT_ID}:p1"]})
    assert PolicyResponse.model_validate(payload).status == "CONFLICT_DETECTED"


@pytest.mark.parametrize("change", [
    {"status": "UNKNOWN"},
    {"answer": []},
    {"status": "NOT_FOUND", "missing_information": ["Missing."]},
    {"status": "NOT_FOUND", "answer": []},
    {"status": "PARTIALLY_ANSWERED"},
    {"missing_information": ["Missing."]},
    {"clarification_question": "Which process?"},
    {"status": "CLARIFICATION_NEEDED", "answer": []},
    {"status": "CONFLICT_DETECTED"},
    {"steps": "Not a list"},
])
def test_invalid_response_combinations(change):
    payload = response_payload()
    payload.update(change)
    with pytest.raises(ValidationError):
        PolicyResponse.model_validate(payload)


def test_unknown_source_membership_is_not_claimed_by_schema():
    # Deliberately shows the boundary: active-document membership is Phase 5.
    payload = response_payload()
    payload["answer"][0]["source_ids"] = ["unknown-source"]
    result = PolicyResponse.model_validate(payload)
    assert result.answer[0].source_ids == ["unknown-source"]


class SimulatedStatusError(Exception):
    def __init__(self, status_code):
        super().__init__("Private provider response that must not be printed.")
        self.status_code = status_code


@pytest.fixture
def fake_sdk(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(choices=[
        SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="NAVIGAITE_OK"))
    ])
    sdk = SimpleNamespace(
        OpenAI=MagicMock(return_value=client), APITimeoutError=TimeoutError,
        APIConnectionError=ConnectionError, APIStatusError=SimulatedStatusError,
    )
    monkeypatch.setitem(sys.modules, "openai", sdk)
    return sdk, client


def test_smoke_request_settings_and_no_key_in_messages(env_file, fake_sdk):
    sdk, client = fake_sdk
    settings = load_settings(env_file)
    llm_service.run_smoke_test(settings)
    options = sdk.OpenAI.call_args.kwargs
    assert options["max_retries"] == 0
    assert options["timeout"] == 30
    assert options["base_url"] == settings.base_url
    request = client.chat.completions.create.call_args.kwargs
    assert request["temperature"] == 0
    assert FAKE_KEY not in str(request["messages"])
    client.chat.completions.create.assert_called_once()
    client.__exit__.assert_called_once()


@pytest.mark.parametrize("error", [
    TimeoutError(), ConnectionError(), SimulatedStatusError(400),
    SimulatedStatusError(401), SimulatedStatusError(403), SimulatedStatusError(404),
    SimulatedStatusError(429), SimulatedStatusError(500), RuntimeError(FAKE_KEY),
])
def test_smoke_failures_are_safe_and_never_retried(env_file, fake_sdk, error):
    _, client = fake_sdk
    client.chat.completions.create.side_effect = error
    with pytest.raises(ConnectionCheckError) as caught:
        llm_service.run_smoke_test(load_settings(env_file))
    assert FAKE_KEY not in str(caught.value)
    assert "Private provider response" not in str(caught.value)
    client.chat.completions.create.assert_called_once()


@pytest.mark.parametrize("content,finish", [(None, "stop"), ("wrong", "stop"), ("NAVIGAITE_OK", "length")])
def test_smoke_rejects_empty_wrong_or_truncated_output(env_file, fake_sdk, content, finish):
    _, client = fake_sdk
    choice = client.chat.completions.create.return_value.choices[0]
    choice.message.content = content
    choice.finish_reason = finish
    with pytest.raises(ConnectionCheckError):
        llm_service.run_smoke_test(load_settings(env_file))


def test_smoke_rejects_no_choices(env_file, fake_sdk):
    _, client = fake_sdk
    client.chat.completions.create.return_value.choices = []
    with pytest.raises(ConnectionCheckError, match="no completion choices"):
        llm_service.run_smoke_test(load_settings(env_file))


def test_check_config_does_not_call_api_or_print_key(env_file, monkeypatch, capsys):
    settings = load_settings(env_file)
    monkeypatch.setattr(llm_service, "load_settings", lambda: settings)
    fake_smoke = MagicMock(side_effect=AssertionError("Unexpected API call"))
    monkeypatch.setattr(llm_service, "run_smoke_test", fake_smoke)
    monkeypatch.setattr(sys, "argv", ["llm_service.py", "--check-config"])
    assert llm_service.main() == 0
    output = capsys.readouterr().out
    assert "No API request was made." in output
    assert FAKE_KEY not in output
    fake_smoke.assert_not_called()


def test_cli_missing_configuration_returns_one(monkeypatch, capsys):
    def fail():
        raise ConfigurationError("LLM_API_KEY is required and cannot be blank.")
    monkeypatch.setattr(llm_service, "load_settings", fail)
    monkeypatch.setattr(sys, "argv", ["llm_service.py", "--check-config"])
    assert llm_service.main() == 1
    assert "SETUP ERROR" in capsys.readouterr().out


def test_real_sdk_client_constructs_without_network(env_file):
    if importlib.util.find_spec("openai") is None:
        pytest.skip("OpenAI SDK is not installed; actual SDK construction remains unverified.")
    import openai
    settings = load_settings(env_file)
    with openai.OpenAI(
        api_key=settings.api_key, base_url=settings.base_url,
        timeout=settings.timeout_seconds, max_retries=0,
    ) as client:
        assert client.max_retries == 0
        assert str(client.base_url).rstrip("/") == settings.base_url


def test_twentieth_page_keeps_its_physical_number():
    document = DocumentData(
        document_id=DOCUMENT_ID, filename="handbook.pdf", total_pages=20,
        sources=[make_source(20)], pages_without_text=list(range(1, 20)),
    )
    assert document.sources[0].pdf_page == 20


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_source_text_cannot_be_blank(text):
    payload = make_source().model_dump()
    payload["text"] = text
    with pytest.raises(ValidationError):
        PageSource.model_validate(payload)


def test_schema_declares_all_response_fields_required():
    schema = PolicyResponse.model_json_schema()
    assert set(schema["required"]) == {
        "status", "answer", "steps", "policy_warnings", "missing_information",
        "clarification_question",
    }
    assert schema["additionalProperties"] is False
