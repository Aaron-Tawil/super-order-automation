from src.shared.ai_cost import calculate_cost


def test_calculate_cost_treats_missing_usage_counts_as_zero():
    cost = calculate_cost(
        "gemini-2.5-pro",
        {
            "prompt_token_count": None,
            "candidates_token_count": None,
        },
    )

    assert cost == 0.0
