def build_invoice(charges):
    return {"total": charges["subtotal"], "tier": charges["tier"],
            "units": charges["units"], "period": charges["period"]}
