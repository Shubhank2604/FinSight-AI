from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from google import genai
from google.genai import types

from config import Settings
from local_embeddings import hash_embedding
from schemas import Citation, RetrievalHit, StructuredLLMAnswer, ToolCalculation


class GeminiClient:
    def __init__(self, settings: Settings, embedding_dimensions: int = 768) -> None:
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")
        self.settings = settings
        self.embedding_dimensions = embedding_dimensions
        self.client = genai.Client(api_key=settings.gemini_api_key)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.settings.embedding_provider == "local_hash":
            return [
                hash_embedding(text, dimensions=self.embedding_dimensions)
                for text in texts
            ]

        response = self.client.models.embed_content(
            model=self.settings.gemini_embedding_model,
            contents=texts,
            config=types.EmbedContentConfig(
                output_dimensionality=self.embedding_dimensions,
                task_type="RETRIEVAL_DOCUMENT",
            ),
        )
        return [list(embedding.values) for embedding in response.embeddings] # type: ignore

    def embed_query(self, query: str) -> list[float]:
        if self.settings.embedding_provider == "local_hash":
            return hash_embedding(query, dimensions=self.embedding_dimensions)

        response = self.client.models.embed_content(
            model=self.settings.gemini_embedding_model,
            contents=query,
            config=types.EmbedContentConfig(
                output_dimensionality=self.embedding_dimensions,
                task_type="RETRIEVAL_QUERY",
            ),
        )
        return list(response.embeddings[0].values) # type: ignore

    def generate_grounded_answer(
        self,
        query: str,
        hits: list[RetrievalHit],
        calculations: list[ToolCalculation] | None = None,
    ) -> StructuredLLMAnswer:
        response = self.client.models.generate_content(
            model=self.settings.gemini_text_model,
            contents=self._structured_prompt(
                query=query,
                context_text=self._context_text(hits),
                calculation_text=self._calculation_text(calculations or []),
                include_visual_instruction=False,
            ),
            config={
                "response_mime_type": "application/json",
                "response_json_schema": StructuredLLMAnswer.model_json_schema(),
            },
        )
        return self._parse_structured_response(response.text or "")

    def generate_educational_answer(
        self,
        query: str,
        hits: list[RetrievalHit] | None = None,
        calculations: list[ToolCalculation] | None = None,
    ) -> StructuredLLMAnswer:
        response = self.client.models.generate_content(
            model=self.settings.gemini_text_model,
            contents=self._educational_prompt(
                query=query,
                context_text=self._context_text(hits or []),
                calculation_text=self._calculation_text(calculations or []),
            ),
            config={
                "response_mime_type": "application/json",
                "response_json_schema": StructuredLLMAnswer.model_json_schema(),
            },
        )
        return self._parse_structured_response(response.text or "")

    def generate_multimodal_answer(
        self,
        query: str,
        image_paths: list[str | Path],
        hits: list[RetrievalHit],
        calculations: list[ToolCalculation] | None = None,
    ) -> StructuredLLMAnswer:
        contents: list[object] = [
            self._structured_prompt(
                query=query,
                context_text=self._context_text(hits),
                calculation_text=self._calculation_text(calculations or []),
                include_visual_instruction=True,
            )
        ]
        contents.extend(self._image_parts(image_paths))

        response = self.client.models.generate_content(
            model=self.settings.gemini_text_model,
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": StructuredLLMAnswer.model_json_schema(),
            },
        )
        return self._parse_structured_response(response.text or "")

    def generate_web_grounded_answer(
        self,
        query: str,
    ) -> tuple[StructuredLLMAnswer, list[Citation]]:
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        response = self.client.models.generate_content(
            model=self.settings.gemini_web_grounding_model,
            contents=self._web_prompt(query),
            config=types.GenerateContentConfig(tools=[grounding_tool]),
        )
        citations = self._extract_web_citations(response)
        structured = StructuredLLMAnswer(
            answer=response.text or "Insufficient data to answer reliably.",
            used_citation_ids=[citation.chunk_id for citation in citations if citation.chunk_id],
            claims=[],
            assumptions=[
                "Uses Gemini Google Search grounding for current web information.",
                "Web results can change; verify timestamps and source quality before acting.",
            ],
            confidence=0.75 if citations else 0.45,
            needs_more_data=not bool(response.text),
        )
        return structured, citations

    def _context_text(self, hits: list[RetrievalHit]) -> str:
        if not hits:
            return "No retrieved context."

        context_blocks = []
        for hit in hits:
            chunk = hit.chunk
            location = f"{chunk.source_name}"
            if chunk.page is not None:
                location += f", page {chunk.page}"
            if chunk.section:
                location += f", section {chunk.section}"
            context_blocks.append(
                f"[{chunk.id}] {location}\nType: {chunk.type.value}\n{chunk.content}"
            )
        return "\n\n".join(context_blocks)

    def _calculation_text(self, calculations: list[ToolCalculation]) -> str:
        if not calculations:
            return "No tool calculations."

        calculation_blocks = []
        for calculation in calculations:
            calculation_blocks.append(
                f"Tool: {calculation.tool_name}\n"
                f"Inputs: {calculation.inputs}\n"
                f"Result: {calculation.result}\n"
                f"Trace: {calculation.trace}"
            )
        return "\n\n".join(calculation_blocks)

    def _structured_prompt(
        self,
        query: str,
        context_text: str,
        calculation_text: str,
        include_visual_instruction: bool,
    ) -> str:
        visual_rule = (
            "- For image/chart/screenshot claims, use only visible evidence from the "
            "images and any retrieved context supplied.\n"
            if include_visual_instruction
            else ""
        )
        return f"""
You are FinSight AI, a financial decision-support system.

Rules:
- Answer the user's question directly in the first paragraph.
- Use only the provided retrieved context and deterministic calculation outputs.
- Do not perform new calculations.
- Prefer specific figures, dates, document sections, and table evidence when present.
- If multiple chunks disagree, explain the conflict instead of forcing one answer.
- If the user asks how to calculate, estimate, plan, or reason about a financial goal, provide the calculation framework, formulas, and required inputs. Do not set `needs_more_data` merely because the user's personal numbers are missing.
- Set `needs_more_data` to true only when no useful method, explanation, or grounded answer can be provided.
- Cite evidence using the exact chunk IDs provided in square brackets.
- Put every cited chunk ID in `used_citation_ids`.
- For each factual claim, include a `claims` item with supporting citation IDs.
- If the answer is mainly based on tool output, cite no document chunks but keep the tool result unchanged.
{visual_rule}- Keep the answer concise, structured, and analytical.
- Avoid generic filler. Use bullets or numbered steps when that makes the answer clearer.
- End with missing inputs or next steps only if they are genuinely needed.

Return valid JSON matching the provided schema.

User query:
{query}

Retrieved context:
{context_text}

Deterministic calculations:
{calculation_text}
"""

    def _educational_prompt(
        self,
        query: str,
        context_text: str,
        calculation_text: str,
    ) -> str:
        return f"""
You are FinSight AI, a precise financial education and decision-support assistant.

Answer quality rules:
- Answer the user's actual question directly first.
- Give a complete, practical framework, not a vague overview.
- Use formulas, variables, and step-by-step logic where useful.
- If the user asks how to calculate something, show the formula and list the inputs needed.
- If a common rule of thumb exists, explain when it is useful and when it breaks.
- Include a compact worked structure with variable names even when exact numbers are missing.
- Do not invent personal facts. Say which user-specific values are needed for a final number.
- Do not give licensed financial, tax, or investment advice.
- If deterministic calculation output is provided, use it and do not recompute it mentally.
- Use retrieved context when relevant, but you may use general financial knowledge for broad educational explanations.
- Keep the answer concise but complete enough to be useful.
- Set `needs_more_data` to false when you can provide a method/framework even without personal numbers.

For retirement-planning questions, include the core structure:
1. estimate annual retirement spending
2. choose retirement horizon/life expectancy
3. adjust for inflation
4. estimate real return
5. calculate required corpus using either the 25x rule or present value of withdrawals
6. subtract existing assets and expected income
7. compute required monthly investment if needed

Return valid JSON matching the provided schema.

User query:
{query}

Retrieved context, if useful:
{context_text}

Deterministic calculations:
{calculation_text}
"""

    def _web_prompt(self, query: str) -> str:
        return f"""
You are FinSight AI, a financial decision-support system.

Use Google Search grounding for current web information.
Rules:
- Be concise and analytical.
- Do not provide personalized investment advice.
- Prefer factual comparisons, source-backed facts, and explicit uncertainty.
- If sources disagree or are weak, say so.
- Include dates or freshness context when relevant.
- Do not use web search results for uploaded-document questions unless the user asks for current/external information.

User query:
{query}
"""

    def _image_parts(self, image_paths: list[str | Path]) -> list[types.Part]:
        parts = []
        for image_path in image_paths:
            path = Path(image_path)
            if not path.exists() or path.stat().st_size > 18 * 1024 * 1024:
                continue
            mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
            parts.append(types.Part.from_bytes(data=path.read_bytes(), mime_type=mime_type))
        return parts

    def _parse_structured_response(self, raw_text: str) -> StructuredLLMAnswer:
        try:
            return StructuredLLMAnswer.model_validate_json(raw_text)
        except Exception:
            try:
                return StructuredLLMAnswer.model_validate(json.loads(raw_text))
            except Exception:
                return StructuredLLMAnswer(
                    answer=raw_text.strip() or "Insufficient data to answer reliably.",
                    used_citation_ids=[],
                    claims=[],
                    assumptions=[],
                    confidence=0.2,
                    needs_more_data=True,
                )

    def _extract_web_citations(self, response: object) -> list[Citation]:
        citations: list[Citation] = []
        seen_urls: set[str] = set()

        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            metadata = getattr(candidate, "grounding_metadata", None)
            chunks = getattr(metadata, "grounding_chunks", None) if metadata else None
            for index, chunk in enumerate(chunks or [], start=1):
                web = getattr(chunk, "web", None)
                if not web:
                    continue
                url = getattr(web, "uri", None) or getattr(web, "url", None)
                title = getattr(web, "title", None) or "Web source"
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                citations.append(
                    Citation(
                        chunk_id=f"web-{len(citations) + 1}",
                        source_name=title,
                        snippet=title,
                        source_type="web",
                        url=url,
                    )
                )

        return citations
