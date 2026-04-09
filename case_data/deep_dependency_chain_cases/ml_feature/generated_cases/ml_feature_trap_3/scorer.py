def model_scorer_node(scaled):
    score = 0.5 + 0.3 * scaled["scaled_rolling_mean"]
    return {
        "score": round(score, 4),
        "scaled_input": scaled["scaled_rolling_mean"],
        "prediction": "high" if score > 0.7 else "low",
    }
