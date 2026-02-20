import argparse
import mimetypes
import os
import sys

# Ensure the project root is in the Python path (scripts/tests/ -> scripts/ -> /)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.extraction.local_detector import LocalSupplierDetector
from src.shared.logger import get_logger

logger = get_logger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Test Local Supplier Detection on a raw file.")
    parser.add_argument("file_path", help="Path to the PDF or Excel order file")
    parser.add_argument("--mime-type", help="Optional mime type (e.g. application/pdf)", default=None)
    args = parser.parse_args()

    if not os.path.exists(args.file_path):
        print(f"Error: File not found at {args.file_path}")
        sys.exit(1)

    mime_type = args.mime_type
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(args.file_path)
        if not mime_type:
            # Fallback based on extension
            ext = os.path.splitext(args.file_path)[1].lower()
            if ext == ".pdf":
                mime_type = "application/pdf"
            elif ext in [".xlsx", ".xls"]:
                mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif ext == ".csv":
                mime_type = "text/csv"
            else:
                mime_type = "application/octet-stream"
                
    print(f"Testing local detection on: {args.file_path}")
    print(f"Guessed Mime Type: {mime_type}")
    print("-" * 40)

    try:
        detector = LocalSupplierDetector()
        
        # Test purely content-based detection (no email metadata provided)
        # We pass debug=True to get raw_text and found_identifiers
        result = detector.detect_supplier(
            file_path=args.file_path,
            mime_type=mime_type,
            email_metadata=None,
            debug=True
        )

        print("\n--- Detection Results ---")
        print(f"Supplier Code: {result['code']}")
        print(f"Confidence:    {result['conf']}")
        print(f"Method Used:   {result['method']}")
        
        print("\n--- Identifiers Found in Text ---")
        if result['found_identifiers']:
            for identifier in result['found_identifiers']:
                print(f" - {identifier}")
        else:
            print(" - None")

        print("\n--- Raw Text Extracted ---")
        print(result['raw_text'].strip() or "(No text extracted)")
        print("-------------------------")
        
    except Exception as e:
        logger.exception(f"Error running detector: {e}")
        print(f"\nError: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
