from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

OrderStatus = Literal["COMPLETED", "FAILED", "NEEDS_REVIEW", "UNKNOWN"]
AuthProvider = Literal["google", "microsoft"]


class AuthProviderDto(BaseModel):
    provider: AuthProvider
    label: str


class AuthSessionDto(BaseModel):
    authenticated: bool
    email: str | None = None
    name: str | None = None
    provider: AuthProvider | None = None


class OrderMetricsDto(BaseModel):
    total: int
    completed: int
    needs_review: int
    failed: int
    unknown_supplier: int


class OrderListItemDto(BaseModel):
    order_id: str
    status: OrderStatus
    supplier_code: str
    supplier_name: str
    invoice_number: str
    sender: str
    subject: str
    filename: str
    created_at: str | None = None
    line_items_count: int = 0
    warnings_count: int = 0
    is_test: bool = False


class OrdersListResponseDto(BaseModel):
    items: list[OrderListItemDto]
    metrics: OrderMetricsDto
    total_items: int
    page: int
    page_size: int
    total_pages: int


class OrderLineItemDto(BaseModel):
    barcode: str
    item_code: str
    description: str
    quantity: float | int
    final_net_price: float | int


class OrderDetailDto(BaseModel):
    order_id: str
    status: OrderStatus
    supplier_code: str
    supplier_name: str
    invoice_number: str
    sender: str
    subject: str
    filename: str
    created_at: str | None = None
    processing_cost_ils: float = 0.0
    is_test: bool = False
    warnings: list[str] = Field(default_factory=list)
    notes: str | None = None
    math_reasoning: str | None = None
    qty_reasoning: str | None = None
    line_items: list[OrderLineItemDto] = Field(default_factory=list)
    source_file_url: str
    export_url: str


class UpdateOrderDto(BaseModel):
    is_test: bool | None = None


class ToggleOrderTestFlagDto(BaseModel):
    is_test: bool


class UploadExtractionResponseDto(BaseModel):
    order_id: str
    supplier_code: str
    supplier_name: str
    detection_method: str
    new_items_added: int = 0


class SupplierDto(BaseModel):
    code: str
    name: str
    global_id: str = ""
    email: str = ""
    phone: str = ""
    special_instructions: str = ""


class SuppliersListResponseDto(BaseModel):
    items: list[SupplierDto]
    total_items: int
    page: int
    page_size: int
    total_pages: int


class SupplierCreateDto(BaseModel):
    code: str
    name: str
    global_id: str
    email: str = ""
    phone: str = ""
    special_instructions: str = ""


class SupplierUpdateDto(BaseModel):
    name: str | None = None
    global_id: str | None = None
    email: str | None = None
    phone: str | None = None
    special_instructions: str | None = None


class ItemDto(BaseModel):
    barcode: str
    name: str
    item_code: str | None = None
    note: str | None = None


class ItemMutationDto(BaseModel):
    barcode: str
    name: str
    item_code: str
    note: str | None = None


class ItemBatchMutationDto(BaseModel):
    items: list[ItemMutationDto]


class DeleteItemsDto(BaseModel):
    barcodes: list[str]


class MutationResultDto(BaseModel):
    success: bool
    count: int = 0
    message: str | None = None
