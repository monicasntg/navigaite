"""Shared data contracts. This file does not read PDFs or call an API."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_PDF_PAGES = 20
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_QUESTION_CHARACTERS = 1000

# Check for a non-whitespace character without changing the original text.
NonBlankText = Annotated[str, Field(min_length=1, pattern=r"\S")]
DocumentId = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
STRICT_MODEL = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class PageSource(BaseModel):
    """Application-owned evidence, not a structure the LLM creates."""

    model_config = STRICT_MODEL

    source_id: NonBlankText
    document_id: DocumentId
    pdf_page: int = Field(ge=1, le=MAX_PDF_PAGES)
    text: NonBlankText

    @model_validator(mode="after")
    def check_source_identity(self) -> Self:
        expected = f"{self.document_id}:p{self.pdf_page}"
        if self.source_id != expected:
            raise ValueError("Source ID must match its document and physical page.")
        return self


class DocumentData(BaseModel):
    """All physical pages must be accounted for, including unreadable pages."""

    model_config = STRICT_MODEL

    document_id: DocumentId
    filename: NonBlankText
    total_pages: int = Field(ge=1, le=MAX_PDF_PAGES)
    sources: list[PageSource] = Field(min_length=1)
    pages_without_text: list[Annotated[int, Field(ge=1, le=MAX_PDF_PAGES)]]

    @model_validator(mode="after")
    def check_page_coverage(self) -> Self:
        readable_pages = [source.pdf_page for source in self.sources]
        all_pages = readable_pages + self.pages_without_text

        if any(source.document_id != self.document_id for source in self.sources):
            raise ValueError("Every source must belong to this document.")
        if len(all_pages) != len(set(all_pages)):
            raise ValueError("A physical page must not be recorded twice.")
        if set(all_pages) != set(range(1, self.total_pages + 1)):
            raise ValueError("Every physical page must be accounted for.")
        if readable_pages != sorted(readable_pages):
            raise ValueError("Readable sources must stay in physical page order.")
        if self.pages_without_text != sorted(self.pages_without_text):
            raise ValueError("Pages without text must stay in physical page order.")
        return self


class CitedItem(BaseModel):
    """One policy statement and the IDs proposed as its evidence."""

    model_config = STRICT_MODEL

    text: NonBlankText
    source_ids: list[NonBlankText] = Field(min_length=1)

    @model_validator(mode="after")
    def check_duplicate_references(self) -> Self:
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("Do not repeat a source ID within the same item.")
        return self


class PolicyResponse(BaseModel):
    """LLM output: source IDs are allowed; page-number fields are not."""

    model_config = STRICT_MODEL

    status: Literal[
        "ANSWERED", "PARTIALLY_ANSWERED", "NOT_FOUND",
        "CLARIFICATION_NEEDED", "CONFLICT_DETECTED",
    ]
    answer: list[CitedItem]
    steps: list[CitedItem]
    policy_warnings: list[CitedItem]
    missing_information: list[NonBlankText]
    clarification_question: NonBlankText | None

    @model_validator(mode="after")
    def check_status_rules(self) -> Self:
        has_policy_content = bool(self.answer or self.steps or self.policy_warnings)

        if self.status in {"NOT_FOUND", "CLARIFICATION_NEEDED"}:
            if has_policy_content:
                raise ValueError("This status must not contain policy claims.")
        elif not self.answer:
            raise ValueError("An answer with cited evidence is required.")

        if self.status in {"NOT_FOUND", "PARTIALLY_ANSWERED"}:
            if not self.missing_information:
                raise ValueError("Explain which information is missing.")
        if self.status == "ANSWERED" and self.missing_information:
            raise ValueError("Use PARTIALLY_ANSWERED when requested details are missing.")

        if self.status == "CLARIFICATION_NEEDED":
            if self.clarification_question is None:
                raise ValueError("A clarification question is required.")
        elif self.clarification_question is not None:
            raise ValueError("Use CLARIFICATION_NEEDED for a clarification question.")

        if self.status == "CONFLICT_DETECTED" and len(self.answer) < 2:
            raise ValueError("Describe both conflicting statements with evidence.")
        return self
