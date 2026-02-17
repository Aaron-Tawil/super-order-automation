import os
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile

# Ensure src is in python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.core.processor import OrderProcessor
from src.extraction.vertex_client import init_client
from src.ingestion.firestore_writer import save_order_to_firestore
from src.ingestion.gcs_writer import upload_to_gcs
from src.shared.config import settings
from src.shared.logger import get_logger
from src.shared.models import ExtractedOrder

load_dotenv()

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize the Gemini Client on startup.
    """
    logger.info("--- Starting Super Order Automation API ---")

    # Check what creds we have via Settings
    if settings.GEMINI_API_KEY:
        logger.info("Authenticated via API Key.")
    elif settings.PROJECT_ID:
        logger.info(f"Authenticated via Vertex AI Project: {settings.PROJECT_ID}")
    else:
        logger.warning("Warning: No credentials found (GEMINI_API_KEY or GCP_PROJECT_ID).")

    try:
        # Use settings defaults in init_client
        init_client()
        logger.info("Gemini Client Initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize client: {e}")

    yield
    logger.info("Shutting down API...")


app = FastAPI(title="Super Order Automation API", lifespan=lifespan)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "super-order-automation"}


@app.post("/extract", response_model=list[ExtractedOrder])
async def extract_invoice_endpoint(file: UploadFile = File(...)):
    """
    Upload a PDF invoice and get structured JSON data.
    """
    # Validate file type
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Save uploaded file to temp
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        logger.info(f"Processing uploaded file: {file.filename} temp_path: {tmp_path}")

        # 1. Upload to GCS (Async-like but doing sync for now)
        gcs_uri = upload_to_gcs(tmp_path, file.filename)

        # 2. Extract Data
        processor = OrderProcessor()
        orders = processor.process_file(tmp_path)

        if not orders:
            logger.error("Extraction returned no orders.")
            raise HTTPException(status_code=500, detail="Extraction failed to return valid data.")

        # 3. Save to Firestore (Handle multiple orders?)
        # For now, save each one
        for order in orders:
            doc_id = save_order_to_firestore(order, gcs_uri)
            logger.info(f"Order processed successfully. Firestore ID: {doc_id}")

        return orders

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    finally:
        # Cleanup temp file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
