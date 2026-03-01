from src.shared.models import ExtractedOrder

SupplierDetectionResult = tuple[str, float, float, str, dict, str | None, str | None]
InvoiceExtractionResult = tuple[list[ExtractedOrder], float, dict, dict]
