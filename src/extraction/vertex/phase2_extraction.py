import json
import os

from google.genai import types

from src.extraction.prompts import get_invoice_extraction_prompt
from src.extraction.schemas import raw_response_schema
from src.shared.ai_cost import calculate_cost
from src.shared.constants import EXTRACTION_MODEL_TRIAL_1, EXTRACTION_MODEL_TRIAL_2
from src.shared.logger import get_logger
from src.shared.models import MultiOrderResponse
from src.shared.utils import convert_pdf_bytes_to_images, get_mime_type, is_excel_file

from .client import generate_content_safe
from .excel_fallback import read_excel_safe
from .metadata import extract_response_metadata
from .types import InvoiceExtractionResult

logger = get_logger(__name__)


def _truncate_for_log(text: str, limit: int = 2000) -> str:
    """Trim verbose model output to a safe logging size."""
    if not text:
        return ""
    text = str(text).strip()
    return text if len(text) <= limit else f"{text[:limit]}...[truncated]"


def extract_invoice_data(
    file_path: str,
    mime_type: str = None,
    email_context: str = None,
    supplier_instructions: str = None,
    retry_count: int = 0,
    trace_context: str = "",
) -> InvoiceExtractionResult:
    """
    Phase 2 LLM call: extract invoice line items and totals from document inputs.

    Returns:
        (orders_list, phase2_cost, response_metadata, parsed_raw_response)
    """
    trial_version = 1 if retry_count == 0 else 2
    prompt_text = get_invoice_extraction_prompt(
        email_context=email_context,
        supplier_instructions=supplier_instructions,
        trial=trial_version,
    )

    model_name = EXTRACTION_MODEL_TRIAL_2 if trial_version == 2 else EXTRACTION_MODEL_TRIAL_1

    logger.info(f"{trace_context}>>> Phase 2: Starting Extraction (Attempt {retry_count}) using {model_name}...")
    logger.info(f"{trace_context}File: {os.path.basename(file_path)} | Trial Version: {trial_version}")

    if mime_type is None:
        mime_type = get_mime_type(file_path)
        logger.info(f"Auto-detected MIME type for Phase 2: {mime_type}")

    file_parts = []
    try:
        if is_excel_file(mime_type):
            try:
                df = read_excel_safe(file_path)
                csv_text = df.to_csv(index=False)
                file_parts.append(types.Part.from_text(text=csv_text))
                logger.info("Excel file converted to CSV for Phase 2.")
            except Exception as e:
                logger.error(f"Error converting Excel file: {e}")
                return [], 0.0, {}, {}
        elif "pdf" in mime_type.lower():
            logger.info("Preparing hybrid PDF + Image inputs for Phase 2...")
            with open(file_path, "rb") as f:
                file_content = f.read()

            file_parts.append(types.Part.from_bytes(data=file_content, mime_type="application/pdf"))

            image_bytes_list = convert_pdf_bytes_to_images(file_content, dpi=200)
            if image_bytes_list:
                for img_bytes in image_bytes_list:
                    file_parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/png"))
                logger.info(f"Attached {len(image_bytes_list)} secondary image parts alongside the PDF.")
            else:
                logger.warning("PDF to image conversion returned empty. Proceeding with natively attached PDF only.")

        elif "image" in mime_type.lower():
            with open(file_path, "rb") as f:
                file_content = f.read()
            file_parts.append(types.Part.from_bytes(data=file_content, mime_type=mime_type))

        else:
            logger.warning(f"Warning: Sending unknown mime-type {mime_type} as PDF fallback.")
            with open(file_path, "rb") as f:
                file_content = f.read()
            file_parts.append(types.Part.from_bytes(data=file_content, mime_type="application/pdf"))

    except FileNotFoundError:
        logger.error(f"Error: File not found at {file_path}")
        return [], 0.0, {}, {}

    if trial_version == 2:
        current_tools = [types.Tool(code_execution=types.ToolCodeExecution())]
        current_schema = None
    else:
        current_tools = None
        current_schema = raw_response_schema

    try:
        parts_list = file_parts + [types.Part.from_text(text=prompt_text)]

        response = generate_content_safe(
            model=model_name,
            contents=[types.Content(role="user", parts=parts_list)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json" if current_schema else "text/plain",
                response_schema=current_schema,
                tools=current_tools,
                temperature=0.0,
            ),
        )

        if response.candidates and response.candidates[0].content.parts:
            text_parts = [part.text for part in response.candidates[0].content.parts if part.text is not None]
            raw_json = "".join(text_parts)
        else:
            raw_json = ""

        if retry_count > 0:
            if "```json" in raw_json:
                try:
                    raw_json = raw_json.split("```json")[1].split("```")[0].strip()
                except IndexError:
                    pass
            else:
                raw_json = raw_json.replace("```json", "").replace("```", "").strip()

        raw_json = raw_json.replace("```json", "").replace("```", "").strip()

        logger.info(f"{trace_context}✅ Phase 2 Finished (Model={model_name}). JSON received.")
        logger.debug(
            f"{trace_context}Raw Phase 2 response preview (attempt {retry_count}): {_truncate_for_log(raw_json, 800)}"
        )

        parsed_json = {}
        try:
            parsed_json = json.loads(raw_json)
            logger.info(
                "AI Model Response (Phase 2 - Structured)",
                extra={
                    "json_fields": {
                        "json_payload": parsed_json,
                        "event_type": "ai_response",
                        "attempt": retry_count,
                        "model": model_name,
                    }
                },
            )
        except json.JSONDecodeError:
            logger.error(
                "❌ AI returned invalid JSON",
                extra={
                    "json_fields": {
                        "event_type": "ai_invalid_json",
                        "attempt": retry_count,
                        "model": model_name,
                        "raw_text_preview": _truncate_for_log(raw_json),
                    }
                },
            )
            parsed_json = {"error": "Invalid JSON", "raw_text": raw_json}

        response_metadata = {}
        cost = 0.0
        try:
            response_metadata = extract_response_metadata(response)
            usage_metadata = response_metadata.get("usage", {})
            cost = calculate_cost(model_name, usage_metadata)
        except Exception as cost_err:
            logger.warning(f"{trace_context}Failed to calculate cost for Phase 2: {cost_err}")

        logger.info(f"{trace_context}Phase 2 Cost: ${cost:.6f}")

        try:
            multi_order = MultiOrderResponse.model_validate_json(raw_json)
            return multi_order.orders, cost, response_metadata, parsed_json
        except Exception as validation_err:
            logger.error(
                "❌ Pydantic validation failed",
                extra={
                    "json_fields": {
                        "event_type": "ai_validation_failure",
                        "attempt": retry_count,
                        "model": model_name,
                        "error": str(validation_err),
                        "raw_text_preview": _truncate_for_log(raw_json),
                    }
                },
            )
            if "error" not in parsed_json:
                parsed_json["error"] = f"Validation failed: {str(validation_err)}"
            return [], cost, response_metadata, parsed_json

    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        return [], 0.0, {}, {"error": str(e)}
