from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChunkType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"


class Route(str, Enum):
    COMPUTE_ONLY = "compute_only"
    EDUCATIONAL_ANSWER = "educational_answer"
    RETRIEVE_THEN_ANSWER = "retrieve_then_answer"
    RETRIEVE_THEN_COMPUTE_THEN_ANSWER = "retrieve_then_compute_then_answer"
    MULTIMODAL_REASONING = "multimodal_reasoning"
    WEB_GROUNDED_ANSWER = "web_grounded_answer"
    ABSTAIN = "abstain"


class DocumentChunk(BaseModel):
    id: str
    document_id: str
    source_name: str
    type: ChunkType
    content: str
    page: int | None = None
    section: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalHit(BaseModel):
    chunk: DocumentChunk
    score: float
    source: Literal["dense", "sparse", "hybrid"]


class Citation(BaseModel):
    chunk_id: str | None = None
    source_name: str
    page: int | None = None
    section: str | None = None
    snippet: str
    source_type: Literal["document", "web"] = "document"
    url: str | None = None


class ToolCalculation(BaseModel):
    tool_name: str
    inputs: dict[str, Any]
    result: dict[str, Any]
    assumptions: list[str] = Field(default_factory=list)
    trace: str
    confidence: float = 1.0


class ToolResult(BaseModel):
    success: bool
    calculation: ToolCalculation | None = None
    error: str | None = None


class AnswerClaim(BaseModel):
    text: str
    citation_ids: list[str] = Field(default_factory=list)


class StructuredLLMAnswer(BaseModel):
    answer: str
    used_citation_ids: list[str] = Field(default_factory=list)
    claims: list[AnswerClaim] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_more_data: bool = False


class RouterDecision(BaseModel):
    route: Route
    required_tools: list[str] = Field(default_factory=list)
    required_retrieval: bool = False
    required_modalities: list[ChunkType] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    reason: str


class VerifiedResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    calculations: list[ToolCalculation] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    claims: list[AnswerClaim] = Field(default_factory=list)
