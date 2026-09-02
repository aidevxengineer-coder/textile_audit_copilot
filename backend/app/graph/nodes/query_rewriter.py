from __future__ import annotations

import json
from collections import Counter

from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.node_utils import compact_history, compact_project_context, emit_complete, emit_start, get_runtime, image_to_data_url, read_attachment_bytes
from app.graph.prompts import QUERY_REWRITER_PROMPT
from app.graph.state import AgentState


def _collect_vision_candidates(attachments: list[dict]) -> list[dict]:
    """Gather everything the vision model should look at.

    This includes attachments uploaded directly as image files, plus images
    embedded inside PDF/DOCX evidence (scanned certificates, photos pasted
    into a report). Without the second half, a factory photo saved inside a
    PDF is invisible to the pipeline even though a standalone JPG upload of
    the same photo would be reviewed normally.
    """

    candidates: list[dict] = []
    for attachment in attachments:
        mime_type = str(attachment.get("mime_type") or "")
        if mime_type.startswith("image/"):
            candidates.append(
                {
                    "stored_path": attachment.get("stored_path"),
                    "mime_type": mime_type,
                    "file_name": attachment.get("file_name"),
                }
            )
        file_name = attachment.get("file_name") or "document"
        for embedded in attachment.get("embedded_images") or []:
            label = (
                f"{file_name} (page {embedded['page']}, image {embedded.get('index', '?')})"
                if embedded.get("page")
                else f"{file_name} (embedded image {embedded.get('index', '?')})"
            )
            candidates.append(
                {
                    "stored_path": embedded.get("stored_path"),
                    "mime_type": embedded.get("mime_type"),
                    "file_name": label,
                }
            )
    return candidates


def _build_attachment_brief(attachments: list[dict]) -> str | None:
    if not attachments:
        return None

    lines: list[str] = []
    type_counter = Counter()
    for attachment in attachments:
        document_type = attachment.get("document_type") or "general"
        type_counter[document_type] += 1
        summary = attachment.get("evidence_summary")
        if summary:
            lines.append(f"- {summary}")
            continue
        lines.append(f"- Uploaded {document_type} file: {attachment.get('file_name')}")

    counts = ", ".join(f"{count} {document_type}" for document_type, count in sorted(type_counter.items()))
    return f"Uploaded evidence types: {counts}\n" + "\n".join(lines[:8])


async def query_rewriter(state: AgentState, config) -> AgentState:
    node_name = "Query Rewriter"
    await emit_start(config, node_name, "Preparing standalone compliance query")
    runtime = get_runtime(config)

    image_analysis = state.get("image_analysis")
    attachments = state.get("current_attachment_contexts") or state.get("attachment_contexts", [])
    attachment_brief = _build_attachment_brief(attachments)
    if attachments and not image_analysis:
        image_attachments = _collect_vision_candidates(attachments)
        first_document = next(
            (
                attachment
                for attachment in attachments
                if not str(attachment.get("mime_type") or "").startswith("image/")
            ),
            None,
        )

        if image_attachments:
            max_images = getattr(runtime.ollama_service, "vision_max_images", 3)
            selected_images = image_attachments[:max_images]
            if runtime.pipeline_log_service:
                runtime.pipeline_log_service.log_step(
                    run_id=runtime.run_id,
                    node_name=node_name,
                    status="in_progress",
                    detail=f"Running visual review for {len(selected_images)} image(s)",
                )
            await runtime.emitter.stage(
                node_name,
                "in_progress",
                f"Reviewing {len(selected_images)} attached image(s)",
            )
            try:
                content: list[dict] = [
                    {
                        "type": "text",
                        "text": (
                            f"User question: {state['original_query']}\n"
                            "Review each labeled image separately, then explain any relationship between them."
                        ),
                    }
                ]
                analyzed_names: list[str] = []
                for index, attachment in enumerate(selected_images, start=1):
                    payload = read_attachment_bytes(attachment["stored_path"])
                    filename = str(attachment.get("file_name") or f"image-{index}")
                    analyzed_names.append(filename)
                    content.extend(
                        [
                            {"type": "text", "text": f"Image {index}: {filename}"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": image_to_data_url(attachment["mime_type"], payload)
                                },
                            },
                        ]
                    )

                messages = [
                    SystemMessage(
                        content=(
                            "You are the visual evidence reviewer for a textile and leather pre-audit assistant. "
                            "Describe only visible evidence relevant to the user's question and social compliance. "
                            "Check fire exits, extinguishers, signage, chemical storage, PPE, machine guarding, "
                            "worker facilities, blocked pathways, visible certificates, housekeeping, and hazards. "
                            "Separate observations from uncertainty. Never claim a standard violation from an image "
                            "alone, and clearly say when a requested detail is not visible."
                        )
                    ),
                    HumanMessage(content=content),
                ]
                if hasattr(runtime.ollama_service, "invoke_vision_with_metadata"):
                    vision_result = await runtime.ollama_service.invoke_vision_with_metadata(messages)
                    image_analysis = vision_result.content
                    provider_detail = f"{vision_result.provider.title()} ({vision_result.model})"
                else:
                    image_analysis = await runtime.ollama_service.invoke_vision(messages)
                    provider_detail = "configured vision model"

                success_detail = (
                    f"Visual evidence ready for {', '.join(analyzed_names)} using {provider_detail}"
                )
                if len(image_attachments) > len(selected_images):
                    success_detail += f"; {len(image_attachments) - len(selected_images)} additional image(s) remain attached"
                if runtime.pipeline_log_service:
                    runtime.pipeline_log_service.log_step(
                        run_id=runtime.run_id,
                        node_name=node_name,
                        status="in_progress",
                        detail=success_detail,
                    )
                await runtime.emitter.stage(node_name, "in_progress", success_detail)
            except Exception as exc:
                # A missing or temporarily unavailable vision model must not
                # terminate the whole WebSocket run. Keep the attachment in
                # scope and make the limitation explicit to the response model.
                image_analysis = (
                    f"{len(image_attachments)} image evidence file(s) are attached, but visual analysis "
                    "was unavailable for this run. Do not infer details that are not present in text evidence."
                )
                if runtime.pipeline_log_service:
                    runtime.pipeline_log_service.log_step(
                        run_id=runtime.run_id,
                        node_name=node_name,
                        status="failed",
                        detail=f"Image analysis unavailable: {str(exc)[:240]}",
                    )
                await runtime.emitter.stage(
                    node_name,
                    "in_progress",
                    "Images are saved, but visual analysis is temporarily unavailable; continuing with other evidence.",
                )
        elif first_document:
            image_analysis = f"Document evidence excerpt: {first_document.get('preview_text') or 'No text extracted.'}"

    history_text = compact_history(state.get("conversation_history", []))
    evaluator_feedback = state.get("evaluator_feedback") or "None"

    rewritten_query = await runtime.ollama_service.invoke_text(
        [
            SystemMessage(content=QUERY_REWRITER_PROMPT),
            HumanMessage(
                content=json.dumps(
                    {
                        "original_query": state["original_query"],
                        "conversation_history": history_text,
                        "project_context": compact_project_context(state.get("project_context")),
                        "cross_reference_result": state.get("cross_reference_result"),
                        "image_analysis": image_analysis,
                        "attachment_brief": attachment_brief,
                        "evaluator_feedback": evaluator_feedback,
                        "retry_count": state.get("retry_count", 0),
                    },
                    indent=2,
                )
            ),
        ]
    )

    await emit_complete(config, node_name, "Standalone query ready")
    return {
        "rewritten_query": rewritten_query.strip(),
        "image_analysis": image_analysis,
        "attachment_brief": attachment_brief,
        "evaluator_feedback": None,
    }
