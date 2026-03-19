from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse

from src.core.pipeline import ExtractionPipeline
from src.data.items_service import ItemsService
from src.data.orders_service import OrdersService
from src.data.supplier_service import SupplierService
from src.ingestion.firestore_writer import save_order_to_firestore
from src.ingestion.gcs_writer import download_file_from_gcs, upload_to_gcs
from src.shared.config import settings
from src.web_api.auth import (
    build_login_url,
    decode_session_cookie,
    decode_state,
    encode_session_cookie,
    exchange_code_for_token,
    get_enabled_auth_providers,
    get_user_info,
    is_provider_configured,
    is_user_allowed,
    normalize_provider,
    provider_label,
)
from src.web_api.schemas import (
    AuthProviderDto,
    AuthSessionDto,
    DeleteItemsDto,
    ItemBatchMutationDto,
    ItemDto,
    ItemMutationDto,
    MutationResultDto,
    OrderDetailDto,
    OrdersListResponseDto,
    SupplierCreateDto,
    SupplierDto,
    SuppliersListResponseDto,
    SupplierUpdateDto,
    ToggleOrderTestFlagDto,
    UpdateOrderDto,
    UploadExtractionResponseDto,
)
from src.web_api.serializers import (
    build_order_metrics,
    filter_orders,
    serialize_order_detail,
    serialize_order_list_item,
)

app = FastAPI(title="Super Order Automation Web API", version="0.1.0")

allowed_origins = [settings.get_next_ui_url.rstrip("/"), "http://localhost:3000", "http://127.0.0.1:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(origin for origin in allowed_origins if origin)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_current_session(request: Request) -> dict:
    raw_cookie = request.cookies.get(settings.API_SESSION_COOKIE_NAME)
    payload = decode_session_cookie(raw_cookie)
    if not payload:
        raise HTTPException(status_code=401, detail="Authentication required")
    return payload


def base_api_path(request: Request) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/api/v1"


def parse_csv_query(values: list[str] | None) -> list[str]:
    parsed: list[str] = []
    for value in values or []:
        for item in str(value).split(","):
            cleaned = item.strip()
            if cleaned:
                parsed.append(cleaned)
    return parsed


def paginate_items(items: list[dict], page: int, page_size: int) -> tuple[list[dict], int, int]:
    safe_page_size = max(1, min(page_size, 100))
    safe_page = max(page, 1)
    total_items = len(items)
    total_pages = max(1, (total_items + safe_page_size - 1) // safe_page_size)
    page_index = min(safe_page, total_pages) - 1
    start = page_index * safe_page_size
    end = start + safe_page_size
    return items[start:end], total_items, total_pages


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/auth/providers", response_model=list[AuthProviderDto])
def auth_providers() -> list[AuthProviderDto]:
    return [
        AuthProviderDto(provider=provider, label=provider_label(provider))
        for provider in get_enabled_auth_providers()
    ]


@app.get("/api/v1/auth/login/{provider}")
def auth_login(provider: str, order_id: str | None = None):
    normalized_provider = normalize_provider(provider)
    if not is_provider_configured(normalized_provider):
        raise HTTPException(status_code=400, detail=f"{provider_label(provider)} auth is not configured")

    redirect_params = {"order_id": order_id} if order_id else None
    return RedirectResponse(build_login_url(normalized_provider, redirect_params=redirect_params))


@app.get("/api/v1/auth/callback/{provider}")
def auth_callback(provider: str, code: str | None = None, state: str | None = None):
    normalized_provider = normalize_provider(provider)
    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth code")

    decoded_state = decode_state(state)
    if not decoded_state:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    token_data = exchange_code_for_token(code, normalized_provider)
    if not token_data:
        raise HTTPException(status_code=400, detail="Failed to exchange OAuth code")

    user_info = get_user_info(token_data, normalized_provider)
    if not user_info:
        raise HTTPException(status_code=400, detail="Failed to fetch user info")

    email = user_info.get("email")
    if not is_user_allowed(email):
        raise HTTPException(status_code=403, detail=f"Email '{email}' is not allowed")

    redirect_target = f"{settings.get_next_ui_url.rstrip('/')}/inbox"
    redirect_params = decoded_state.get("redir")
    if isinstance(redirect_params, dict) and redirect_params.get("order_id"):
        redirect_target = f"{settings.get_next_ui_url.rstrip('/')}/orders/{redirect_params['order_id']}"

    response = RedirectResponse(redirect_target, status_code=302)
    response.set_cookie(
        key=settings.API_SESSION_COOKIE_NAME,
        value=encode_session_cookie(email=email, user_name=str(user_info.get("name") or "User"), provider=normalized_provider),
        httponly=True,
        secure=settings.is_cloud_runtime,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
        path="/",
    )
    return response


@app.post("/api/v1/auth/logout", response_model=MutationResultDto)
def auth_logout():
    response = JSONResponse({"success": True, "count": 1, "message": "Logged out"})
    response.delete_cookie(settings.API_SESSION_COOKIE_NAME, path="/")
    return response


@app.get("/api/v1/auth/session", response_model=AuthSessionDto)
def auth_session(request: Request):
    payload = decode_session_cookie(request.cookies.get(settings.API_SESSION_COOKIE_NAME))
    if not payload:
        return AuthSessionDto(authenticated=False)
    return AuthSessionDto(
        authenticated=True,
        email=str(payload.get("email") or ""),
        name=str(payload.get("name") or ""),
        provider=normalize_provider(payload.get("provider")),
    )


@app.get("/api/v1/orders", response_model=OrdersListResponseDto)
def list_orders(
    _: dict = Depends(get_current_session),
    search: str = "",
    status: list[str] = Query(default=[]),
    supplier: list[str] = Query(default=[]),
    include_test: bool = False,
    limit: int = 500,
    page: int = 1,
    page_size: int = 10,
):
    orders = OrdersService().list_orders(limit=limit)
    filtered = filter_orders(
        orders,
        search=search,
        statuses=parse_csv_query(status),
        supplier_codes=parse_csv_query(supplier),
        include_test=include_test,
    )
    paged_items, total_items, total_pages = paginate_items(filtered, page, page_size)
    supplier_service = SupplierService()
    return OrdersListResponseDto(
        items=[serialize_order_list_item(order, supplier_service=supplier_service) for order in paged_items],
        metrics=build_order_metrics(filtered),
        total_items=total_items,
        page=max(page, 1),
        page_size=max(1, min(page_size, 100)),
        total_pages=total_pages,
    )


@app.get("/api/v1/orders/{order_id}", response_model=OrderDetailDto)
def get_order(order_id: str, request: Request, _: dict = Depends(get_current_session)):
    order = OrdersService().get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return serialize_order_detail(order, base_path=base_api_path(request), items_service=ItemsService())


@app.patch("/api/v1/orders/{order_id}", response_model=MutationResultDto)
def patch_order(order_id: str, payload: UpdateOrderDto, _: dict = Depends(get_current_session)):
    if payload.is_test is None:
        raise HTTPException(status_code=400, detail="No supported fields to update")
    success = OrdersService().update_order_test_flag(order_id, payload.is_test)
    return MutationResultDto(success=success, count=1 if success else 0)


@app.post("/api/v1/orders/{order_id}/test-flag", response_model=MutationResultDto)
def toggle_order_test_flag(order_id: str, payload: ToggleOrderTestFlagDto, _: dict = Depends(get_current_session)):
    success = OrdersService().update_order_test_flag(order_id, payload.is_test)
    return MutationResultDto(success=success, count=1 if success else 0)


@app.get("/api/v1/orders/{order_id}/source-file")
def download_source_file(order_id: str, _: dict = Depends(get_current_session)):
    order = OrdersService().get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    metadata = order.get("ui_metadata", {}) or {}
    gcs_uri = order.get("gcs_uri") or metadata.get("source_file_uri")
    if not gcs_uri:
        raise HTTPException(status_code=404, detail="Source file unavailable")

    original_name = metadata.get("filename") or order.get("filename") or Path(gcs_uri).name
    suffix = Path(original_name).suffix or ".bin"
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file.close()
    if not download_file_from_gcs(gcs_uri, temp_file.name):
        os.unlink(temp_file.name)
        raise HTTPException(status_code=502, detail="Failed to download source file")
    return FileResponse(temp_file.name, media_type="application/octet-stream", filename=original_name)


@app.get("/api/v1/orders/{order_id}/export.xlsx")
def download_export(order_id: str, _: dict = Depends(get_current_session)):
    order = OrdersService().get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    rows = []
    for item in order.get("line_items", []) or []:
        rows.append(
            {
                "קוד פריט": item.get("barcode") or "",
                "כמות": item.get("quantity", 0),
                "מחיר נטו": item.get("final_net_price", 0),
            }
        )
    dataframe = pd.DataFrame(rows or [{"קוד פריט": "", "כמות": 0, "מחיר נטו": 0}])
    buffer = tempfile.SpooledTemporaryFile()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False)
    buffer.seek(0)
    filename = f"order_{order.get('invoice_number', order_id)}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/v1/uploads/extract", response_model=UploadExtractionResponseDto)
def extract_upload(
    _: dict = Depends(get_current_session),
    file: UploadFile = File(...),
    is_test: bool = Form(False),
):
    suffix = Path(file.filename or "upload.bin").suffix.lower() or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(file.file.read())
        temp_path = temp_file.name

    try:
        mime_type = file.content_type or "application/octet-stream"
        result = ExtractionPipeline().run_pipeline(
            file_path=temp_path,
            mime_type=mime_type,
            email_metadata={"body": "Attached is the invoice."},
        )
        order = result.orders[0] if result.orders else None
        if not order:
            raise HTTPException(status_code=422, detail="No order extracted from upload")

        source_uri = upload_to_gcs(temp_path, file.filename or Path(temp_path).name) or ""
        doc_id = save_order_to_firestore(
            order,
            source_file_uri=source_uri,
            is_test=is_test,
            metadata={
                "filename": file.filename,
                "phase1_reasoning": result.phase1_reasoning,
                "from_manual_upload": True,
            },
            new_items_data=result.new_items_data,
            added_items_barcodes=result.added_barcodes,
        )
        if not doc_id:
            raise HTTPException(status_code=500, detail="Failed to save extracted order")

        return UploadExtractionResponseDto(
            order_id=doc_id,
            supplier_code=result.supplier_code,
            supplier_name=result.supplier_name,
            detection_method=result.detection_method,
            new_items_added=result.new_items_added,
        )
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@app.get("/api/v1/suppliers", response_model=SuppliersListResponseDto)
def list_suppliers(_: dict = Depends(get_current_session), search: str = "", page: int = 1, page_size: int = 10):
    suppliers = SupplierService().get_all_suppliers()
    if search:
        query = search.lower()
        suppliers = [
            supplier
            for supplier in suppliers
            if query in str(supplier.get("code", "")).lower()
            or query in str(supplier.get("name", "")).lower()
            or query in str(supplier.get("global_id", "")).lower()
            or query in str(supplier.get("email", "")).lower()
        ]
    paged_items, total_items, total_pages = paginate_items(suppliers, page, page_size)
    return SuppliersListResponseDto(
        items=[
            SupplierDto(
                code=str(supplier.get("code", "")),
                name=str(supplier.get("name", "")),
                global_id=str(supplier.get("global_id", "")),
                email=str(supplier.get("email", "")),
                phone=str(supplier.get("phone", "")),
                special_instructions=str(supplier.get("special_instructions", "")),
            )
            for supplier in paged_items
        ],
        total_items=total_items,
        page=max(page, 1),
        page_size=max(1, min(page_size, 100)),
        total_pages=total_pages,
    )


@app.post("/api/v1/suppliers", response_model=MutationResultDto)
def create_supplier(payload: SupplierCreateDto, _: dict = Depends(get_current_session)):
    success = SupplierService().add_supplier(
        supplier_code=payload.code,
        name=payload.name,
        global_id=payload.global_id,
        email=payload.email,
        phone=payload.phone,
        special_instructions=payload.special_instructions,
    )
    return MutationResultDto(success=success, count=1 if success else 0)


@app.patch("/api/v1/suppliers/{supplier_code}", response_model=MutationResultDto)
def update_supplier(supplier_code: str, payload: SupplierUpdateDto, _: dict = Depends(get_current_session)):
    success = SupplierService().update_supplier(
        supplier_code=supplier_code,
        name=payload.name,
        global_id=payload.global_id,
        email=payload.email,
        phone=payload.phone,
        special_instructions=payload.special_instructions,
    )
    return MutationResultDto(success=success, count=1 if success else 0)


@app.get("/api/v1/items/search", response_model=list[ItemDto])
def search_items(query: str, _: dict = Depends(get_current_session)):
    return [ItemDto(**item) for item in ItemsService().search_items(query)]


@app.post("/api/v1/items", response_model=MutationResultDto)
def create_item(payload: ItemMutationDto, _: dict = Depends(get_current_session)):
    success = ItemsService().add_new_item(
        barcode=payload.barcode,
        name=payload.name,
        item_code=payload.item_code,
        note=payload.note,
    )
    return MutationResultDto(success=success, count=1 if success else 0)


@app.post("/api/v1/items/batch", response_model=MutationResultDto)
def create_items_batch(payload: ItemBatchMutationDto, _: dict = Depends(get_current_session)):
    count = ItemsService().add_new_items_batch([item.model_dump() for item in payload.items])
    return MutationResultDto(success=True, count=count)


@app.delete("/api/v1/items/by-barcode", response_model=MutationResultDto)
def delete_items(payload: DeleteItemsDto, _: dict = Depends(get_current_session)):
    count = ItemsService().delete_items_by_barcodes(payload.barcodes)
    return MutationResultDto(success=True, count=count)


@app.post("/api/v1/items/delete-batch", response_model=MutationResultDto)
def delete_items_batch(payload: DeleteItemsDto, _: dict = Depends(get_current_session)):
    count = ItemsService().delete_items_by_barcodes(payload.barcodes)
    return MutationResultDto(success=True, count=count)
