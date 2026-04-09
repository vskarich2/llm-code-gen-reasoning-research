def model_scorer_node(scaled):
    score = 0.5 + 0.3 * scaled["scaled_rolling_mean"]
    adjusted = round(score - 0.1, 4)
    return {
        "score": adjusted,
        "scaled_input": scaled["scaled_rolling_mean"],
        "prediction": "high" if adjusted > 0.7 else "low",
        "adjusted": True,
    }
