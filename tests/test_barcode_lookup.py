
import unittest
from unittest.mock import MagicMock
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data.items_service import ItemsService

class TestBarcodeLookup(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_collection = MagicMock()
        self.mock_db.collection.return_value = self.mock_collection
        self.service = ItemsService(firestore_client=self.mock_db)

    def test_get_new_barcodes_with_leading_zeros(self):
        # Setup: "123" exists in DB
        # We want to check: ["123", "0123", "00123", "456"]
        # Expected result: ["456"]
        
        input_barcodes = ["123", "0123", "00123", "456"]
        
        # Mock get_all response
        # It will be called with refs for ["123", "0123", "00123", "456", "123", "123"] (duplicates handled by set)
        # Actually logic is: unique checks = ["123", "0123", "00123", "456"] because 0123->123, 00123->0123->123 etc?
        # No, my logic was: append b, and if b starts with 0, append b.lstrip('0').
        # So checks for "0123" -> ["0123", "123"]
        # checks for "123" -> ["123"]
        # checks for "456" -> ["456"]
        
        # Mocking the docs returned
        # Valid docs in DB: "123"
        
        mock_doc_123 = MagicMock()
        mock_doc_123.exists = True
        mock_doc_123.id = "123"
        
        mock_doc_0123 = MagicMock()
        mock_doc_0123.exists = False
        mock_doc_0123.id = "0123"
        
        mock_doc_00123 = MagicMock()
        mock_doc_00123.exists = False
        mock_doc_00123.id = "00123"

        mock_doc_456 = MagicMock()
        mock_doc_456.exists = False
        mock_doc_456.id = "456"
        
        # We need to simulate get_all returning these based on input refs
        # The service calls: docs = self._db.get_all(refs)
        
        def side_effect_get_all(refs):
            results = []
            for ref in refs:
                # ref.id is the document ID (barcode)
                bid = ref._document_path.split('/')[-1] if hasattr(ref, '_document_path') else ref
                # Simulating ref object behavior just enough or just matching by ID if we could
                # But here we just mock the return list regardless of order if we can controls it
                pass
            
            # Simplified: The logic iterates over docs and checks doc.id
            # So we just need to return a list of docs where "123" exists and others don't.
            # The service creates a set: existing_ids = {doc.id for doc in docs if doc.exists}
            # So we just returns [mock_doc_123, mock_doc_0123, ...]
            return [mock_doc_123, mock_doc_0123, mock_doc_00123, mock_doc_456]

        self.mock_db.get_all.side_effect = side_effect_get_all
        
        result = self.service.get_new_barcodes(input_barcodes)
        
        print(f"Input: {input_barcodes}")
        print(f"Result: {result}")
        
        self.assertIn("456", result)
        self.assertNotIn("123", result)
        self.assertNotIn("0123", result)
        self.assertNotIn("00123", result)
        self.assertEqual(len(result), 1)

if __name__ == '__main__':
    unittest.main()
