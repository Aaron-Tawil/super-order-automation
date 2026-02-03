from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException
import shutil
import os
import tempfile
import sys

# Ensure src is in python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.extraction.vertex_client import init_client, process_invoice
from src.shared.models import ExtractedOrder
from src.ingestion.gcs_writer import upload_to_gcs
from src.ingestion.firestore_writer import save_order_to_firestore
from dotenv import load_dotenv

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize the Gemini Client on startup.
    """
    project_id = os.getenv("GCP_PROJECT_ID")
    location = os.getenv("GCP_LOCATION", "us-central1")
    api_key = os.getenv("GEMINI_API_KEY")
    
    print("--- Starting Super Order Automation API ---")
    if api_key:
        print("Authenticated via API Key.")
    elif project_id:
        print(f"Authenticated via Vertex AI Project: {project_id}")
    else:
        print("Warning: No credentials found (GEMINI_API_KEY or GCP_PROJECT_ID).")

    try:
        init_client(project_id, location, api_key)
        print("Gemini Client Initialized.")
    except Exception as e:
        print(f"Failed to initialize client: {e}")
    
    yield
    print("Shutting down API...")

app = FastAPI(title="Super Order Automation API", lifespan=lifespan)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "super-order-automation"}

@app.post("/extract", response_model=ExtractedOrder)
async def extract_invoice_endpoint(file: UploadFile = File(...)):
    """
    Upload a PDF invoice and get structured JSON data.
    """
    # Validate file type
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Save uploaded file to temp
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    
    try:
        print(f"Processing uploaded file: {file.filename} temp_path: {tmp_path}")
        
        # 1. Upload to GCS (Async-like but doing sync for now)
        gcs_uri = upload_to_gcs(tmp_path, file.filename)
        
        # 2. Extract Data
        order = process_invoice(tmp_path)
        
        if not order:
            raise HTTPException(status_code=500, detail="Extraction failed to return valid data.")
            
        # 3. Save to Firestore
        doc_id = save_order_to_firestore(order, gcs_uri)
        
        # Add doc_id to response headers or wrap response? 
        # For now, just returning the order, but logging the ID.
        print(f"Order processed successfully. Firestore ID: {doc_id}")
            
        return order
        
    except Exception as e:
        print(f"Error processing file: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        # Cleanup temp file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
