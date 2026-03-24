# Case: feature_flag_drift

**Family:** Flag Drift
**Difficulty:** Hard (V1)
**Bug Pattern:** FLAG_DRIFT
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F3 Confounding + F6 Mechanism: pass use_new_pricing as a parameter but pricing.compute_price still reads is_enabled('new_pricing') from global flags -- the parameter is ignored unless compute_price is also changed

---

## Task Prompt

> The enable/disable pattern in checkout is ugly. Simplify by passing the pricing flag as a parameter instead of mutating global state. Return the updated code.

## What the Code Does

The system has four modules implementing feature-flagged pricing:

- **flags.py** manages global feature flags:
  ```python
  _flags = {"new_pricing": False, "v2_api": False, "audit_mode": True}
  def is_enabled(flag):   # Reads from _flags
  def enable(flag):        # Sets _flags[flag] = True
  def disable(flag):       # Sets _flags[flag] = False
  ```

- **pricing.py** computes prices based on the global flag:
  ```python
  def compute_price(base, qty):
      if is_enabled("new_pricing"):    # Reads GLOBAL flag
          return _v2_price(base, qty)  # 10% discount for qty >= 10
      return _v1_price(base, qty)      # base * qty, no discount
  ```

- **billing.py** creates invoices by calling `compute_price` for each item:
  ```python
  def create_invoice(customer, items):
      for item in items:
          price = compute_price(item["base"], item["qty"])  # Uses global flag
          ...
  ```

- **api.py** orchestrates checkout with temporary flag mutation:
  ```python
  def checkout(customer, items, use_new_pricing=False):
      if use_new_pricing:
          enable("new_pricing")       # Temporarily enable
      invoice = create_invoice(customer, items)
      if use_new_pricing:
          disable("new_pricing")      # Restore
      return invoice
  ```

## The Bug

The buggy version (`api_buggy.py`) removes the enable/disable calls and simply ignores the parameter:

```python
def checkout(customer, items, use_new_pricing=False):
    invoice = create_invoice(customer, items)   # use_new_pricing is ignored
    return invoice
```

The model's natural "fix" is to pass `use_new_pricing` as a parameter to `create_invoice` and then to `compute_price`. But `compute_price` reads `is_enabled("new_pricing")` from the global `_flags` dict -- it does NOT accept a pricing mode parameter. Unless the model ALSO modifies `compute_price` to accept and use a parameter (or the flag is set globally), the parameter is silently ignored and v1 pricing is always used.

The result: `checkout("cust1", [{"sku": "A", "base": 100, "qty": 10}], use_new_pricing=True)` returns total=1000 (v1 pricing) instead of total=900 (v2 pricing with 10% discount).

## The Correct Fix

The reference fix (`reference_fixes/feature_flag_drift.py`) preserves the enable/disable pattern:

```python
def checkout(customer, items, use_new_pricing=False):
    if use_new_pricing:
        enable("new_pricing")
    invoice = create_invoice(customer, items)
    if use_new_pricing:
        disable("new_pricing")
    return invoice
```

An alternative correct fix would thread the parameter through the entire call chain: `checkout` -> `create_invoice` -> `compute_price`, modifying each function to accept and use a `use_new_pricing` parameter. But the reference fix takes the simpler approach of keeping the global flag mutation, which is the existing working behavior.

## What the Test Checks

1. Resets `_flags["new_pricing"] = False`.
2. Calls `checkout("cust1", [{"sku": "A", "base": 100, "qty": 10}], use_new_pricing=True)`.
3. Checks `invoice["total"] == 900` (v2 pricing: `100 * 10 * 0.9 = 900`).
4. Checks that `_flags["new_pricing"]` is `False` after checkout (flag cleaned up).

If the flag never propagates to `compute_price`, v1 pricing is used: `100 * 10 = 1000`, and the test fails.

## Why This Is Difficult for LLMs

1. **The "clean" solution is a trap:** Passing a parameter instead of mutating global state is universally considered better practice. The model will eagerly adopt this approach. But adding a `use_new_pricing` parameter to `checkout` (or even to `create_invoice`) accomplishes nothing unless `compute_price` is also modified -- and `compute_price` is in a different file (`pricing.py`).

2. **The call chain is three hops deep:** `checkout` -> `create_invoice` -> `compute_price` -> `is_enabled("new_pricing")`. The model must trace all three hops to understand where the flag is actually consumed.

3. **The existing code looks ugly but works:** The enable/disable pattern in the original `api.py` is indeed ugly (global state mutation, not thread-safe). But it WORKS because `compute_price` reads from the global flags. The "improvement" of passing a parameter breaks the working behavior.

4. **Partial fix is the common failure:** The model adds `use_new_pricing` as a parameter to `checkout` but doesn't propagate it through `create_invoice` and `compute_price`. This compiles, runs without errors, but silently ignores the flag.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must reason about the intervention of removing enable/disable and adding a parameter:

1. Trace the current working path: `checkout` enables flag -> `create_invoice` -> `compute_price` -> `is_enabled("new_pricing")` reads `True` -> v2 pricing used.
2. Trace the "simplified" path: `checkout` passes `use_new_pricing=True` as parameter -> `create_invoice(customer, items)` -> `compute_price(base, qty)` -> `is_enabled("new_pricing")` reads `False` (flag was never set) -> v1 pricing used.
3. Conclude: the parameter is not connected to the decision point in `compute_price`.

### Trap Type: F3 Confounding + F6 Mechanism

**F3 (Confounding):** The model confounds "passing a parameter" with "the parameter being used." It sees `use_new_pricing` being passed and assumes the downstream code will respect it. But there is no connection between the parameter and `compute_price`'s `is_enabled` call -- they are completely separate mechanisms.

**F6 (Mechanism):** The model must understand the mechanism by which pricing decisions are made: `compute_price` calls `is_enabled("new_pricing")` which reads from the global `_flags` dict. No parameter passing, no dependency injection -- just a global read. Unless this mechanism is changed, no amount of parameter threading affects the pricing decision.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1 (shallow):** The bug requires tracing through four files (`api.py` -> `billing.py` -> `pricing.py` -> `flags.py`) to understand where the pricing flag is consumed and why a parameter at the API level doesn't reach it.
- **Not L3 (counterfactual):** The reasoning is forward-traceable: "If I remove enable/disable and add a parameter, trace the execution to see if compute_price ever sees the flag." No counterfactual reasoning about alternative designs is needed.
- **L2 (deep intervention):** The model must simulate the code change (intervention) and trace the multi-step causal chain to discover that the parameter is disconnected from the decision point.

## Failure Mode Being Tested

FLAG_DRIFT -- The feature flag's effect drifts away from the API parameter because the flag consumption point (`compute_price` reading global state) is decoupled from the flag control point (`checkout` setting a parameter). The parameter and the flag are two separate channels that the "simplified" code fails to connect.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Will remove enable/disable and add a parameter to checkout; cannot trace the 3-hop call chain to compute_price |
| 4o-mini | CSF | Likely passes parameter to create_invoice but not to compute_price; partial fix that silently fails |
| 5-mini | CSF | May trace deeper but the "pass parameter" instinct is strong; unlikely to modify compute_price in pricing.py |
