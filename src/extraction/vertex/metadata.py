def extract_response_metadata(response) -> dict:
    """
    Extracts response metadata from a Gemini response.
    Includes usage stats, finish reason, safety ratings, and citations.
    """
    metadata = {
        "usage": {},
        "finish_reason": "UNKNOWN",
        "safety_ratings": [],
        "citation_metadata": None,
    }

    if hasattr(response, "usage_metadata"):
        raw_usage = response.usage_metadata
        metadata["usage"] = {
            "prompt_token_count": getattr(raw_usage, "prompt_token_count", 0),
            "candidates_token_count": getattr(raw_usage, "candidates_token_count", 0),
            "total_token_count": getattr(raw_usage, "total_token_count", 0),
        }

    if response.candidates and len(response.candidates) > 0:
        candidate = response.candidates[0]

        metadata["finish_reason"] = str(getattr(candidate, "finish_reason", "UNKNOWN"))

        if getattr(candidate, "safety_ratings", None):
            metadata["safety_ratings"] = [
                {
                    "category": str(getattr(r, "category", "UNKNOWN")),
                    "probability": str(getattr(r, "probability", "UNKNOWN")),
                    "blocked": getattr(r, "blocked", False),
                }
                for r in candidate.safety_ratings
            ]

        if hasattr(candidate, "citation_metadata") and candidate.citation_metadata:
            cit = candidate.citation_metadata
            metadata["citation_metadata"] = {
                "citations": [
                    {
                        "start_index": getattr(c, "start_index", 0),
                        "end_index": getattr(c, "end_index", 0),
                        "uri": getattr(c, "uri", ""),
                    }
                    for c in getattr(cit, "citations", [])
                ]
            }

    return metadata
