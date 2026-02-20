import re
from enum import StrEnum
from typing import List, Optional

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from src.shared.constants import VAT_RATE


class VatStatus(StrEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


class LineItem(BaseModel):
    barcode: str | None = Field(None, description="EAN or Supplier SKU")
    description: str = Field("Unknown Item", description="Product name or description")
    quantity: float | None = Field(0.0, description="Number of units")

    # Financials
    raw_unit_price: float | None = Field(0.0, description="Price per unit as listed on the line")
    vat_status: VatStatus = Field(VatStatus.EXCLUDED, description="Is VAT included in the raw_unit_price?")
    discount_percentage: float = Field(0.0, description="Line-specific discount", ge=0, le=100)

    # Promotion handling (e.g., "11+1 free")
    paid_quantity: float | None = Field(None, description="Number of PAID units in promotion (e.g., 11 in '11+1')")
    bonus_quantity: float | None = Field(None, description="Number of FREE units in promotion (e.g., 1 in '11+1')")

    # Calculated fields (populated by LLM or Validator)
    final_net_price: float | None = Field(0.0, description="Final price per unit EXCLUDING VAT and discounts")

    @field_validator("barcode", mode="before")
    @classmethod
    def clean_barcode(cls, v):
        if not v:
            return None
        # Remove non-numeric characters (spaces, hyphens, etc.)
        # Ensure it's a string first
        s = str(v)
        clean_v = re.sub(r"[^0-9]", "", s)
        if not clean_v:
            return None
        return clean_v

    @field_validator("quantity", "raw_unit_price", "final_net_price", "discount_percentage", mode="before")
    @classmethod
    def coerce_none_to_default(cls, v, info):
        if v is None:
            return 0.0
        return v

    @model_validator(mode="after")
    def validate_net_price(self) -> "LineItem":
        # Sanity check: Net price shouldn't normally be higher than raw price
        if self.vat_status == VatStatus.INCLUDED:
            if self.final_net_price > self.raw_unit_price:
                pass  # Warning: Logic for specific edge cases might go here
        return self


class ExtractedOrder(BaseModel):
    # Note: supplier_name removed - we get supplier from Phase 1 detection
    invoice_number: str | None = None
    currency: str = "ILS"

    # Validation Warnings
    warnings: list[str] = Field(default_factory=list, description="List of warnings or errors found during validation")

    # Supplier identification
    supplier_name: str | None = Field(None, description="Supplier name (from detection or fallback)")
    supplier_code: str | None = Field(None, description="Supplier code (from detection or fallback)")

    # Supplier identification for matching
    supplier_global_id: str | None = Field(None, description="Supplier's global ID (עוסק/ח\"פ) if present in document")
    supplier_email: str | None = Field(None, description="Supplier's email address if visible in document")
    supplier_phone: str | None = Field(None, description="Supplier's phone/mobile/fax if visible")

    # Invoice-level discount (applies to ALL line items) - Optional bc AI may return None
    global_discount_percentage: float | None = Field(
        0.0, description="Invoice-level discount as percentage (e.g., 15.25 for 15.25% off)"
    )

    # "Hidden" invoice-level discounts - Optional bc AI may return None
    total_invoice_discount_amount: float | None = Field(0.0, description="Lump sum discount applied to total")

    # Document totals for validation
    document_total_with_vat: float | None = Field(
        None, description="Final total amount from bottom of invoice (usually includes VAT)"
    )
    document_total_without_vat: float | None = Field(
        None, description="Final total amount from bottom of invoice PRE-VAT (excluding VAT)"
    )
    document_total_quantity: float | None = Field(None, description="Total quantity of items from bottom of invoice")

    # LLM Verification (Trial 2)
    is_math_valid: bool | None = Field(None, description="Did the LLM verify that the calculated sum matches the printed total?")
    math_reasoning: str | None = Field(None, description="Explanation for math discrepancy if any")
    is_qty_valid: bool | None = Field(None, description="Did the LLM verify that the calculated quantities match?")
    qty_reasoning: str | None = Field(None, description="Explanation for quantity discrepancy if any")

    # Metadata from API
    ai_metadata: dict | None = Field(default_factory=dict, description="Metadata from Vertex AI extraction")

    # Usage / Cost Metadata
    processing_cost: float = Field(0.0, description="Estimated cost of AI processing for this order (USD)")
    processing_cost_ils: float = Field(0.0, description="Estimated cost of AI processing for this order (ILS)")
    usage_metadata: dict | None = Field(None, description="Raw token usage metadata from AI model")

    line_items: list[LineItem] = Field(..., validation_alias=AliasChoices("line_items", "items"))

    @field_validator("global_discount_percentage", "total_invoice_discount_amount", mode="before")
    @classmethod
    def coerce_none_to_default(cls, v, info):
        if v is None:
            defaults = {
                "global_discount_percentage": 0.0,
                "total_invoice_discount_amount": 0.0,
            }
            return defaults.get(info.field_name, 0.0)
        return v


class MultiOrderResponse(BaseModel):
    orders: list[ExtractedOrder] = Field(..., description="List of all orders extracted from the document")
