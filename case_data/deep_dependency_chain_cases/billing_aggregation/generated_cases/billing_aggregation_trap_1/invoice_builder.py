def build_invoice(charges):
    invoice = {"total": charges["subtotal"], "tier": charges["tier"],
               "units": charges["units"], "period": charges["period"]}
    if invoice["tier"] == "growth" and invoice["total"] > 8.0:
        invoice["tier"] = "enterprise"
        invoice["total"] = round(invoice["units"] * 0.05, 2)
        invoice["adjustment"] = "applied"
    return invoice
