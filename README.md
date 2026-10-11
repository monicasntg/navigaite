# NavigAIte - Phase 1

Find the right policy. Follow the right process.

## What exists now

This delivery contains configuration loading, shared Pydantic data models, an
explicit API connection check, and offline tests. It is NOT the finished PDF app.
There is no PDF extraction, context assembly, policy-answer generation, or UI yet.

The approved architecture uses all readable pages of one short PDF. There will
be no retrieval.py, embedding search, database, OCR, or conversation memory.

## Files

| File | Responsibility |
| --- | --- |
| schemas.py | Document, page source, cited item, and response data contracts. |
| llm_service.py | Phase 1 configuration checks and one opt-in API request. |
| requirements.txt | Required packages with bounded compatibility ranges. |
| .env.example | Configuration template with placeholders, not credentials. |
| .gitignore | Keep local secrets, environments, and generated files out of Git. |
| tests/test_core.py | Offline schema/configuration tests and simulated API tests. |
| README.md | Setup, checks, limits, and current verification status. |

## 1. Set up Python

Use Python 3.11-3.13. The local tests in this delivery used Python 3.13.5.
Open Git Bash in this extracted navigaite folder:

```bash
python --version
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

For macOS or Linux, activation is `source .venv/bin/activate` instead.
Do not install the unrelated package named `fitz`; requirements uses PyMuPDF.

An import check for the complete planned dependency list is:

```bash
python -c "import streamlit, pymupdf, pydantic, openai, dotenv, pytest; print('IMPORTS OK')"
```

## 2. Configure locally

For a new project, copy the template. Do not overwrite an existing configured .env.

```bash
cp -n .env.example .env
```

Open .env in your editor and set:

- LLM_API_KEY: your real key, kept only on your machine.
- LLM_BASE_URL: the provider's HTTPS API base; not /chat/completions.
- LLM_MODEL: the exact model ID your account can access.
- LLM_CONTEXT_TOKENS: the documented limit for that exact endpoint/model.

The NVIDIA base URL is supplied as an example. No model or context limit has been
guessed. LLM_MAX_OUTPUT_TOKENS defaults to 1200; LLM_TIMEOUT_SECONDS defaults to 30.
Existing environment values override .env, even when those values are empty.
The loader reads only this project's .env and does not search parent folders.
It does not modify the process environment or expand ${...} inside values.

Never paste your key into chat, a source file, a screenshot, or a Git commit.
The key is omitted from the settings object's normal representation; this is not
encryption. Do not explicitly print settings.api_key or serialize settings.
.gitignore does not remove secrets that have already been committed; rotate an
exposed key and remove it from repository history as appropriate.

## 3. Run offline checks first

```bash
python -m pytest -q
python llm_service.py --check-config
```

The tests use dummy settings and simulated API responses. They do not need a real
key and do not call the network. The optional SDK-construction test is skipped
when the actual openai package is unavailable; it does not make a network call.

After valid local settings, the configuration command prints:

```text
CONFIG OK: required settings are present and locally valid.
This does not verify the model's actual context limit or access.
No API request was made.
```

Missing settings produce a readable error and exit status 1, for example:

```text
SETUP ERROR: LLM_API_KEY is required and cannot be blank.
```

Configuration validation checks syntax and relationships, not provider truth.
A positive context-limit value is not proof the provider accepts that limit.
The complete document input-budget guard belongs to Phase 4.

## 4. Explicitly check the real endpoint

After you have installed the requirements and configured your account:

```bash
python llm_service.py --smoke-test
```

This makes ONE request and may consume API credits. It asks the model to copy the
provided text NAVIGAITE_OK. It sends no handbook, no employee question, and no key
inside the model's messages. The key is used only for client authentication.
The client uses temperature 0, no streaming, a small output allowance, and zero
automatic retries. Temperature 0 is not a guarantee of identical model behavior.
The timeout is a network timeout setting, not a hard end-to-end time guarantee.

Expected success, after the two configuration lines:

```text
SMOKE TEST PASSED: the endpoint returned NAVIGAITE_OK.
Structured output and token-counting support remain unverified.
```

Authentication, permission, model/URL, rate-limit, connection, timeout, empty
output, and incomplete-output failures give safe setup messages. They never
become a NOT_FOUND policy response. No raw provider exception is printed.

A passing smoke check only proves that this small request worked at that time.
It does NOT prove native schema support, document accuracy, context capacity,
reliable token counting, or future availability.

## Shared contracts and why they matter

PageSource stores source_id, document_id, pdf_page, and original extracted text.
Document IDs are defined as 64-character SHA-256 hex strings. Actual hashing and
extraction are future phases. The source-ID contract is `<document_id>:p<page>`.
The full document identity prevents accidental reuse of short page-only IDs.
Only application-owned records contain pdf_page. All page numbers are one-based
physical PDF positions, including covers and blank pages.

DocumentData accounts for every page exactly once, either as readable evidence or
as a page without extracted text. It rejects mixed-document or out-of-order data.
These checks validate records; they do not prove future extraction is correct.

CitedItem requires nonblank text and at least one distinct, nonblank source ID.
PolicyResponse requires all fields, though lists can be empty and the clarification
question can be null. Unknown fields and wrong types are rejected.

The status values are:

- ANSWERED: a supported answer; missing_information must be empty.
- PARTIALLY_ANSWERED: a cited answer plus an explanation of missing details.
- NOT_FOUND: no policy claims; missing_information must explain the gap.
- CLARIFICATION_NEEDED: no policy claims; a clarification question is required.
- CONFLICT_DETECTED: at least two cited answer items describe the conflicting text.
  Both items may cite the same page, because a conflict can occur on one page.

A response schema deliberately has no page-number or filename fields. The model
will supply only IDs. The future service will check each ID against the active
request's sources; the interface will resolve pages from application data.
Unknown source membership is NOT checked by these Phase 1 schemas alone. A test
explicitly documents this boundary. Phase 5 adds active-source membership checks.
Structural validity also does not prove that cited text supports the claim.

## Verification status for this delivery

The local runtime had pydantic 2.13.5, python-dotenv 1.2.2, and pytest 9.0.2.
Offline code was tested with those versions. The actual openai and streamlit
packages were unavailable; an attempted installation was blocked by network/DNS
resolution. Therefore requirements.txt is a compatibility range, NOT a verified
complete dependency lock. Record and pin your working versions after a full
successful installation. No live model call was made for this delivery.

Run the commands above on your machine to verify full installation and API access.
Native structured-output support and a matching token-counting method remain open
until the actual endpoint/model is known and checked. No endpoint capabilities are
inferred from the small connectivity test.

## Not implemented in Phase 1

Do not run streamlit run app.py yet: app.py does not exist in this delivery.
PDF parsing, content hashing, page-based chunk creation, complete context assembly,
model-response generation/repair, source membership resolution, and the Streamlit
experience remain in their approved later phases.

## References

Official documentation consulted for the client behavior and configuration rules:

- NVIDIA hosted API: https://docs.api.nvidia.com/nim/reference/llm-apis
- NVIDIA structured output: https://docs.nvidia.com/nim/large-language-models/latest/structured-generation.html
- OpenAI Python client: https://github.com/openai/openai-python
- Pydantic strict mode: https://docs.pydantic.dev/latest/concepts/strict_mode/
- Pydantic validators: https://docs.pydantic.dev/latest/concepts/validators/
- python-dotenv: https://bbc2.github.io/python-dotenv/
- pytest mocking: https://docs.pytest.org/en/stable/how-to/monkeypatch.html
