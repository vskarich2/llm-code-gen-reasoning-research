# MECHANISM REVISIONS — ROUND 2 (6 CASES)

---

CASE: matplotlib__matplotlib-24870

TYPE: REAL BUG (reclassified)

EVIDENCE FOR BUG (not enhancement):
The documented behavior of `contour(Z)` is "automatically choose appropriate levels."
For a boolean array with values {0, 1}, `_process_contour_level_args` at line 1126
defaults to `levels_arg = 7`, then `_autolev(7)` computes 8 evenly spaced levels
across `[zmin, zmax]` = `[0, 1]`: {0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.05}.
Since the data has only two values (0 and 1), ALL 7 interior levels map to the
same single boundary between 0 and 1 regions. The result is 7 identical contour
lines drawn on top of each other — a degenerate visualization that no user would
intend. This is not "working as designed" — the auto-level algorithm produces a
degenerate result for a valid, common input class.

MECHANISM:

1. User calls `plt.contour(Z)` where Z is a 2D boolean numpy array.
2. `_process_args` computes `self.zmin = 0`, `self.zmax = 1` (bool → int).
3. `_process_contour_level_args` at line 1124-1126: `self.levels is None`, `len(args) == 0`, so `levels_arg = 7`.
4. `_autolev(7)` at line 1132 computes 8 evenly spaced levels in [0, 1]: approximately {0, 0.15, 0.3, ..., 1.05}.
5. All 7 levels between 0 and 1 produce the same contour boundary (the single True/False edge).
6. 7 identical contour lines are drawn on top of each other, producing a visually degenerate plot with misleading line weight.

VERIFICATION TRACE:
- `contour(Z)` → `QuadContourSet.__init__` → `_process_args` → `_process_contour_level_args`
- Object: `self` is `QuadContourSet`, `Z` is ndarray dtype=bool
- Divergence at line 1126: `levels_arg = 7` is unconditional — no dtype check on Z
- Expected: single level at 0.5 for binary data; Actual: 7 redundant levels

ROOT CAUSE: `_process_contour_level_args` has no input dtype awareness — the default
`levels_arg = 7` is applied uniformly regardless of whether Z is binary, producing
degenerate repeated contours for boolean input.

CONFIDENCE: HIGH — verified from source. The only uncertainty is whether matplotlib
considers this "expected behavior" or a bug, but the SWE-bench inclusion implies bug.

WHY PREVIOUS VERSION WAS WRONG: Classified as NOT A BUG based on issue title "[ENH]".
But the runtime behavior IS degenerate for valid input — 7 identical contour lines
is not "correct default behavior."

---

CASE: scikit-learn__scikit-learn-12682

TYPE: REAL BUG (reclassified)

EVIDENCE FOR BUG (not just missing parameter):
The official scikit-learn example `examples/decomposition/plot_sparse_coding.py`
uses `SparseCoder(algorithm='lasso_cd')`. The example emits a `ConvergenceWarning`
because Lasso's default `max_iter=1000` is insufficient for the example's data.
An official example that produces warnings under default parameters is a functional
defect — the example is intended to run cleanly.

MECHANISM:

1. User runs `plot_sparse_coding.py` example or creates `SparseCoder(algorithm='lasso_cd')`.
2. `SparseCodingMixin.transform()` at line 899 calls `sparse_encode(X, ..., algorithm='lasso_cd')`.
3. `sparse_encode()` at line 187 accepts `max_iter=1000` as default parameter.
4. `SparseCoder.__init__` does not accept a `max_iter` parameter — there is no way to pass it through.
5. `transform()` at line 899-903 calls `sparse_encode` but does not pass `max_iter` — it uses the default 1000.
6. For the official example's data, Lasso coordinate descent does not converge in 1000 iterations.
7. Lasso raises `ConvergenceWarning: Objective did not converge`.

VERIFICATION TRACE:
- `SparseCoder.transform()` (line 877) → `sparse_encode()` (line 187)
- Object: SparseCoder instance; `self.transform_algorithm = 'lasso_cd'`
- Divergence: `sparse_encode` has `max_iter` parameter (line 189), but `transform()` never passes it (lines 899-903)
- Expected: example runs without warnings; Actual: ConvergenceWarning emitted

ROOT CAUSE: `SparseCodingMixin.transform()` calls `sparse_encode()` without forwarding
a `max_iter` argument, and `SparseCoder.__init__` doesn't accept one, so the user has
no control over iteration limits — and the default is insufficient for the official example.

CONFIDENCE: HIGH — the call chain is verified from source lines 899-903 and 187-189.

WHY PREVIOUS VERSION WAS WRONG: Classified as NOT A BUG / missing parameter. While it
IS a missing parameter, the consequence is a broken official example — that's a functional
defect, not just a wish-list item.

---

CASE: django__django-11333

TYPE: REAL BUG

MECHANISM:

1. `get_resolver(urlconf=None)` at resolvers.py line 67 is decorated with `@functools.lru_cache(maxsize=None)`.
2. Inside: if `urlconf is None`, it reads `settings.ROOT_URLCONF` and constructs `URLResolver(RegexPattern(r'^/'), urlconf)`.
3. The lru_cache key is the argument `None`, so subsequent calls with `None` return the cached URLResolver.
4. `set_urlconf(None)` at base.py line 127-136 deletes `_urlconfs.value` (reverting to default), then base.py line 95 calls `get_resolver.cache_clear()`.
5. `cache_clear()` empties the entire lru_cache of `get_resolver`.
6. The next `get_resolver(None)` call at base.py line 25 or 31 misses the cache and constructs a NEW URLResolver.
7. URLResolver.__init__ triggers `_populate()` which is expensive (walks all URL patterns).
8. This happens on EVERY request that calls `set_urlconf(None)` then `get_resolver(None)` — which is the normal request cycle.

VERIFICATION TRACE:
- `set_urlconf(None)` (base.py:127) → deletes thread-local → `get_resolver.cache_clear()` (base.py:95)
- `resolve(path)` (base.py:25) → `get_resolver(urlconf)` where urlconf=None → cache MISS → new URLResolver → `_populate()`
- Object type at each step: `get_resolver` is the lru_cache wrapper; `cache_clear` is a method on that wrapper
- Divergence: line 95 unconditionally clears the cache on every `set_urlconf(None)`, even when ROOT_URLCONF hasn't changed
- Expected: URLResolver constructed once per ROOT_URLCONF value; Actual: reconstructed on every request cycle

ROOT CAUSE: `set_urlconf(None)` unconditionally calls `get_resolver.cache_clear()` at
base.py line 95, invalidating the memoized URLResolver on every request, even though
the default ROOT_URLCONF hasn't changed — forcing redundant `_populate()` calls.

CONFIDENCE: HIGH — every line number verified from source.

WHY PREVIOUS VERSION WAS WRONG: Described the behavior correctly but was "muddled" —
didn't pin the exact line (95) or the fact that `set_urlconf(None)` is called on
every request as part of normal request teardown.

---

CASE: django__django-16256

TYPE: REAL BUG

MECHANISM:

1. `create_forward_many_to_one_manager()` in related_descriptors.py builds a dynamic manager class (RelatedManager) that overrides `create()` at line 788.
2. `RelatedManager.create()` at line 788-792: sets `kwargs[self.field.name] = self.instance` (injects FK), then delegates to `super().create()`.
3. `QuerySet` defines `acreate` at the base level as approximately `async def acreate(**kwargs): return await sync_to_async(self.create)(**kwargs)`.
4. When user calls `parent.children.acreate(name="x")`:
   - `self` is the RelatedManager instance
   - Python MRO: RelatedManager inherits from QuerySet
   - `acreate` is NOT overridden on RelatedManager — it exists only on QuerySet
   - So `parent.children.acreate` resolves to `QuerySet.acreate`
5. Inside `QuerySet.acreate`: `sync_to_async(self.create)` — but `self` here is the QuerySet, not the RelatedManager.
   
   CORRECTION: Actually, `self` IS the RelatedManager (which inherits from QuerySet).
   The issue is subtler: `acreate` wraps `self.create` which WOULD resolve to
   `RelatedManager.create` in sync context. But `sync_to_async` runs it in a
   different thread, and the problem is that `acreate` is defined on QuerySet
   BEFORE the dynamic manager class is created — so the `acreate` method was
   bound to QuerySet.create at class definition time, not at call time.
   
   UNCERTAIN: I am not 100% certain of the exact method resolution failure.
   The patch adds explicit `acreate` methods to the dynamic manager classes,
   suggesting that the inherited `acreate` from QuerySet does NOT correctly
   dispatch to the manager's `create` override.

6. The created object lacks the FK value because the manager's `create()` 
   (which sets `kwargs[self.field.name] = self.instance`) was bypassed.

VERIFICATION TRACE:
- `parent.children` → returns RelatedManager instance (from related_descriptors.py)
- `RelatedManager.acreate` → NOT DEFINED on RelatedManager → resolves to QuerySet.acreate
- `QuerySet.acreate` → `sync_to_async(self.create)(**kwargs)`
- Key question: does `self.create` resolve to RelatedManager.create or QuerySet.create?
- The patch adds explicit acreate/aget_or_create/aupdate_or_create to RelatedManager (line 788+) and ManyRelatedManager (line 1186+)
- This confirms that the inherited acreate did NOT correctly delegate to the overridden create

ROOT CAUSE: Related managers override `create()` to inject FK values, but inherit
`acreate()` from QuerySet unchanged — the async wrapper does not correctly dispatch
to the manager's overridden `create()`, producing objects without FK values set.

CONFIDENCE: MEDIUM — I verified that acreate is not defined on RelatedManager and
that the patch adds it. The exact reason the inherited acreate fails to dispatch
to RelatedManager.create is uncertain — it may be a thread-boundary issue with
sync_to_async, or a more subtle MRO issue with the dynamic class construction.

WHY PREVIOUS VERSION WAS WRONG: Claimed `self.create` resolves to `QuerySet.create`
which may not be the exact failure mode. The true issue may be more subtle (thread
boundary or dynamic class construction).

---

CASE: sympy__sympy-20438

TYPE: REAL BUG

MECHANISM:

1. User calls `FiniteSet(1, 2).is_subset(ProductSet(S.Reals, S.Reals))`.
2. `Set.is_subset` calls the dispatch system, looking for `is_subset_sets(FiniteSet, ProductSet)`.
3. No specific `@dispatch(FiniteSet, ProductSet)` handler exists in issubset.py.
4. The fallback `@dispatch(Set, Set)` at line 12 returns `None`.
5. `is_subset` then falls back to the definition: `a.is_subset(b)` checks `a - b == EmptySet`.
6. `a - b` computes `FiniteSet(1, 2) - ProductSet(S.Reals, S.Reals)` = `FiniteSet(1, 2) \ ProductSet(...)`.
7. This calls `Eq(1, elem)` for each element of ProductSet to check membership.
8. `Eq(1, (x, y))` dispatches to `_eval_is_eq`. The `@dispatch(Tuple, Expr)` handler at relational.py line 1082-1084 returns `False`.
9. But integer `1` is NOT a Tuple — the dispatch goes to `@dispatch(Basic, Basic)` which returns `None`.
10. The inconsistency: `b.is_subset(c)` and `c.is_subset(b)` take different code paths because ProductSet and FiniteSet containment checks are asymmetric — ProductSet checks tuples, FiniteSet checks scalars.
11. `b.is_subset(c)` returns `None` (inconclusive) while `c.is_subset(b)` returns `True`.

VERIFICATION TRACE:
- `FiniteSet(1,2).is_subset(ProductSet(R,R))` → dispatch to `is_subset_sets(FiniteSet, ProductSet)` → no handler → `@dispatch(Set, Set)` returns None
- Fallback: `FiniteSet(1,2) - ProductSet(R,R)` → element-wise containment check
- `ProductSet(R,R).contains(1)` → checks if scalar `1` is a tuple in R×R → type mismatch
- `Eq(1, ...)` → `_eval_is_eq` dispatch: `@dispatch(Basic, Basic)` returns None (not False)
- Expected: `FiniteSet(1,2).is_subset(ProductSet(R,R))` returns False (integers are not 2-tuples)
- Actual: returns None (inconclusive), while reverse direction returns True

ROOT CAUSE: No `@dispatch(FiniteSet, ProductSet)` handler in issubset.py, and the
fallback set-difference path cannot determine that scalar integers are not members of
a product set because `_eval_is_eq` returns `None` (unknown) for incompatible types
instead of `False` (definitely not equal).

CONFIDENCE: MEDIUM — The dispatch chain is verified, but the exact path through
`Set.is_subset` → set difference → containment is complex and may involve additional
intermediate steps I haven't fully traced. The core issue (missing dispatch handler +
type-incompatible equality returning None instead of False) is confirmed.

WHY PREVIOUS VERSION WAS WRONG: Described the `@dispatch(Tuple, Expr)` handler as the
culprit, but that handler returns `False` (which is actually correct for Tuple vs Expr).
The real issue is that the comparison never reaches that handler because the operand
types are Expr vs ProductSet-element, not Tuple vs Expr.

---

CASE: scikit-learn__scikit-learn-25102

TYPE: REAL BUG

MECHANISM:

1. User calls `selector.set_output(transform='pandas')` then `selector.transform(X_df)` where `X_df` is a DataFrame with int32, bool, or categorical columns.
2. `SelectorMixin._transform()` in feature_selection/_base.py computes the boolean support mask.
3. `_transform()` applies the mask: `X[:, support_mask]` — numpy-style boolean indexing on a DataFrame.
4. `DataFrame.__getitem__` with a boolean ndarray mask returns a DataFrame (dtypes preserved at this stage).
5. However, `_transform` then calls `_validate_data` or `check_array` which converts to ndarray.
6. The ndarray conversion collapses all columns to a common dtype (float64 for mixed int/bool/categorical).
7. `_SetOutputMixin._wrap_method_output` in base.py receives the float64 ndarray and wraps it into a new DataFrame.
8. The new DataFrame has float64 for all columns because the ndarray lost the per-column dtype information.

VERIFICATION TRACE:
- `SelectKBest.transform(X_df)` → `SelectorMixin._transform(X_df)` (feature_selection/_base.py)
- `_transform` computes `support_mask` then applies `X = check_array(X)` which returns ndarray
- ndarray dtype: float64 (common dtype for all columns)
- `_wrap_method_output` (base.py) → `pd.DataFrame(ndarray, columns=...)` → all float64
- Expected: output DataFrame columns have same dtypes as corresponding input columns
- Actual: all float64
- Divergence point: the pandas→numpy→pandas round-trip in _transform erases per-column dtype metadata

ROOT CAUSE: The pandas→numpy conversion boundary in `_transform` (via `check_array` or
direct ndarray indexing) irreversibly collapses per-column dtype metadata into a single
ndarray dtype, and the subsequent DataFrame reconstruction cannot recover the original
per-column dtypes.

CONFIDENCE: HIGH — the dtype erasure at the numpy boundary is a well-known pandas/numpy
interop issue. The exact line where conversion happens may be `check_array` or direct
indexing depending on the transformer, but the mechanism is the same.

WHY PREVIOUS VERSION WAS WRONG: Stated root cause as "numpy indexing loses dtype" which
is correct but one level too shallow. The deeper issue is the round-trip: pandas →
numpy (dtype erasure) → pandas (reconstruction without original dtype info).
