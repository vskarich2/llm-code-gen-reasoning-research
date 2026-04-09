def compute_charges(resolved):
    charge = resolved["units"] * resolved["rate"]
    return {"period": resolved["period"], "units": resolved["units"],
            "tier": resolved["tier"], "rate": resolved["rate"],
            "subtotal": round(charge, 2)}
