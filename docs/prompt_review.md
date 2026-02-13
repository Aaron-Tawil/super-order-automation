# Vertex AI Client Prompt Review & Improvements

This document outlines suggested improvements for the prompts in `src/extraction/vertex_client.py`.



## 2. Phase 2: Invoice Extraction (`process_invoice`)

**Location:** Lines 553-607

### Issues Identified



**B. Math Accuracy**
The prompt asks the LLM to perform complex calculations (line discounts, global discounts, VAT adjustments).
- **Risk:** LLMs can make arithmetic errors.
- **Recommendation:** 
    - **Option A:** Extract raw values (`raw_unit_price`, `discount_percentage`, etc.) and perform the final price calculation in Python.
    - **Option B (Recommended):** Enable `code_execution` on the **first attempt**, not just the retry, to allow the model to use Python for the "MANDATORY MATH SELF-CHECK".





