# VAT rate to be used as single source of truth across the project
VAT_RATE = 0.18

# Tolerance for validation checks (in currency units, e.g., NIS)
VALIDATION_TOLERANCE = 5.0

# Maximum number of retries for extraction
MAX_RETRIES = 1

# --- Model Configuration ---
EXTRACTION_MODEL_TRIAL_1 = "gemini-2.5-flash"   # Fast model for first attempt
EXTRACTION_MODEL_TRIAL_2 = "gemini-2.5-pro"     # Stronger model for retry
SUPPLIER_DETECTION_MODEL = "gemini-2.5-flash"   # Phase 1 supplier detection

# --- Blacklists & Filters ---

# Emails and domains to ignore during supplier detection (e.g. company's own emails)
EXCLUDED_EMAILS = [
    "@superhome.co.il",
    "store4@superhome.co.il",
    "moishiop@gmail.com",
    "aarondavidtawil@gmail.com",
    "orders.superhome.bot@gmail.com",
]

# Business IDs to ignore (e.g. company's own H.P. numbers)
BLACKLIST_IDS = [
    "515020394",
    "029912221",
]

# Company names to ignore during supplier detection (our own company)
BLACKLIST_NAMES = ["סופר הום", "שטובה אינטרנשיונל","שטובה"]
