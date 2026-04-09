# MECHANISM REVISIONS — 15 CASES

---

CASE: django__django-12741

TYPE: NOT A BUG

This is an API cleanup / signature simplification. The problem statement says:
"The current signature is: def execute_sql_flush(self, using, sql_list):
The using argument can be dropped and inferred by the calling instance."

There is no runtime failure. The code works correctly. The `using` parameter is redundant
but not broken. Callers already pass `connection.alias` which always equals
`self.connection.alias`. This is a refactoring task, not a bug fix.

WHY PREVIOUS VERSION WAS WRONG: Described a "redundant parameter" as if it were a bug
mechanism. There is no incorrect behavior — just unnecessary API surface.

---

CASE: django__django-15103

TYPE: NOT A BUG

The problem statement explicitly says: "I recently had a use-case where I wanted to use
json_script but I didn't need any id for it."

This is a feature request to make the `element_id` argument optional. The current code
works correctly — it requires an id and produces a valid script tag with an id. There is
no runtime error, no wrong output, no invariant violation.

WHY PREVIOUS VERSION WAS WRONG: Described "json_script requires element_id" as a bug
mechanism when it is actually documented required behavior that the user wants changed.

---

CASE: django__django-16560

TYPE: NOT A BUG

The problem statement says: "It is currently possible to customize the
violation_error_message of a ValidationError raised by a constraint but not the code.
I'd like to add a new violation_error_code parameter."

This is a feature request to add a customization hook. BaseConstraint.validate works
correctly — it raises ValidationError with code='constraint'. The user wants the code
to be configurable, not that it produces wrong results.

WHY PREVIOUS VERSION WAS WRONG: Described "hardcoded 'constraint' code" as if it were
a bug. It is working as designed; the request is for new functionality.

---

CASE: matplotlib__matplotlib-25775

TYPE: NOT A BUG

The problem statement is titled "[ENH]: Add get/set_antialiased to Text objects" and says:
"Currently, Text objects always retrieve their antialiasing state via the global
rcParams["text.antialias"], unlike other artists for which this can be configured on a
per-artist basis."

This is an enhancement request. Text antialiasing works correctly via rcParams. The user
wants per-instance control that doesn't exist yet.

WHY PREVIOUS VERSION WAS WRONG: Described "Text objects don't have get/set_antialiased"
as a missing-property bug. It is a feature that was never implemented, not broken behavior.

---

CASE: pylint-dev__pylint-4551

TYPE: NOT A BUG

The problem statement says: "It seems that pyreverse does not read python type hints
(as defined by PEP 484)."

This is a feature request. pyreverse was built before PEP 484 type hints existed. It
reads types from docstrings and runtime inspection. Not reading type hints is not a bug
— it's missing feature support.

WHY PREVIOUS VERSION WAS WRONG: Described "inspector.py only reads types from docstrings"
as if it were a bug. pyreverse never claimed to support PEP 484 hints.

---

CASE: pylint-dev__pylint-4661

TYPE: NOT A BUG

The problem statement says: "Make pylint XDG Base Directory Specification compliant" and
"I have this really annoying .pylint.d directory in my home folder."

This is a standards compliance request. pylint stores data in ~/.pylint.d which works
correctly. The user wants it moved to ~/.local/share/pylint per XDG spec. No runtime
failure, no incorrect output.

WHY PREVIOUS VERSION WAS WRONG: Described "PYLINT_HOME hardcoded to ~/.pylint.d" as a
bug mechanism. It is working as designed — just not following a preferred standard.

---

CASE: scikit-learn__scikit-learn-12682

TYPE: NOT A BUG

The problem statement says: "SparseCoder doesn't expose max_iter for Lasso" and
"I guess there should be a way for the user to specify other parameters."

This is a missing parameter exposure. SparseCoder works correctly with the default
max_iter=1000. The user wants to customize it. The convergence warning mentioned is
informational, not an error.

UNCERTAIN: The convergence warning could be considered a bug if the default max_iter
is insufficient for the example in plot_sparse_coding.py. But the core issue is a
missing API parameter, not incorrect computation.

WHY PREVIOUS VERSION WAS WRONG: Described it as "missing parameter passthrough" which
is accurate but framed it as a bug mechanism when it's primarily an API gap.

---

CASE: scikit-learn__scikit-learn-25102

TYPE: REAL BUG

MECHANISM:

1. User enables pandas DataFrame output via `set_output(transform='pandas')` on a
   feature selector (e.g., SelectKBest).
2. Input DataFrame has columns with non-float64 dtypes (e.g., int32, bool, categorical).
3. SelectorMixin._transform in feature_selection/_base.py applies the boolean support
   mask via numpy indexing: `X[:, support_mask]` which converts the DataFrame to a
   numpy ndarray.
4. The ndarray loses all pandas dtype information — everything becomes float64.
5. _SetOutputMixin in base.py wraps the ndarray back into a DataFrame using
   `_wrap_method_output`, but constructs the new DataFrame from the float64 ndarray.
6. The output DataFrame has all float64 columns instead of the original dtypes.

Expected: Output DataFrame preserves input dtypes for columns that were not modified.
Actual: All output columns are float64 regardless of input dtype.

ROOT CAUSE: SelectorMixin._transform uses numpy array indexing (`X[:, mask]`) which
discards pandas dtype metadata, and the output wrapping reconstructs a DataFrame from
the dtype-erased ndarray.

WHY PREVIOUS VERSION WAS WRONG: Correctly identified the dtype loss but described it
in patch language ("Fix requires propagating dtype info").

---

CASE: pydata__xarray-3993

TYPE: NOT A BUG

The problem statement says: "DataArray.integrate has a 'dim' arg, but Dataset.integrate
has a 'coord' arg. This is just a minor gripe but I think it should be fixed."

This is an API inconsistency cleanup. Both methods work correctly. The parameter is
named differently but does the same thing. No runtime error, no wrong output.

WHY PREVIOUS VERSION WAS WRONG: Described "inconsistent API naming" as a bug mechanism.
There is no incorrect behavior — just inconsistent naming that confuses users.

---

CASE: django__django-10554

TYPE: REAL BUG

MECHANISM:

1. Two querysets are combined: `qs1.union(qs2).order_by('field')`.
2. The union query's `get_order_by()` in compiler.py resolves the ordering string
   'field' against the combined query's select list.
3. For a derived queryset (e.g., from `.values()`), the ordering field string
   references a column alias that exists in the subquery but not in the outer
   combined query.
4. `get_order_by()` at line 280 iterates the ordering list. For string-based ordering,
   it calls `self.query.resolve_ref(field)` which resolves against the current
   query's annotations and select list.
5. In a UNION query, `change_aliases()` in query.py remaps table aliases for
   the combined branches, but the ordering expressions still reference the
   pre-remapping aliases.
6. The generated SQL contains `ORDER BY <stale_alias>.column` which doesn't
   exist in the UNION output, producing a DatabaseError.

Expected: ORDER BY references valid columns in the UNION result set.
Actual: ORDER BY references stale aliases from pre-union subqueries.

ROOT CAUSE: `change_aliases()` remaps table aliases in WHERE/SELECT but does not
remap aliases referenced by ORDER BY expressions inherited from subqueries.

WHY PREVIOUS VERSION WAS WRONG: Correctly identified get_order_by and change_aliases
but described it in vague terms without tracing the specific resolution path.

---

CASE: django__django-11333

TYPE: REAL BUG

MECHANISM:

1. `get_resolver()` in resolvers.py is decorated with `@functools.lru_cache(maxsize=None)`.
2. On first call with urlconf=None, the lru_cache stores the result keyed on None.
3. `set_urlconf()` in base.py calls `get_resolver.cache_clear()` to invalidate
   cached resolvers when the URL configuration changes.
4. However, `reverse()` in base.py imports `get_resolver` at module level:
   `from .resolvers import get_resolver`.
5. When `set_urlconf(None)` is called, it clears the cache, but the next call to
   `get_resolver(None)` creates a NEW URLResolver and caches it.
6. A subsequent call to `get_resolver(None)` (before set_urlconf is called again)
   returns the cached result correctly, BUT if the default urlconf hasn't been
   set yet (urlconf=None), multiple calls from different code paths each trigger
   `get_resolver(None)` which all return the same cached result — HOWEVER, the
   bug is that `set_urlconf` clears the cache of `get_resolver` (the wrapper),
   but the actual expensive work is re-done because the lru_cache is on the
   public function whose cache gets cleared on every `set_urlconf(None)` call.
7. Each `set_urlconf(None)` → `get_resolver(None)` cycle constructs a new
   URLResolver and calls the expensive `_populate()` method.

Expected: URLResolver is constructed once and reused across set_urlconf(None) calls.
Actual: URLResolver is reconstructed on every set_urlconf(None) → get_resolver cycle
because cache_clear invalidates the memoization each time.

ROOT CAUSE: `set_urlconf(None)` calls `get_resolver.cache_clear()` which forces
reconstruction of the URLResolver on the next `get_resolver()` call, even though
the urlconf hasn't actually changed.

WHY PREVIOUS VERSION WAS WRONG: Described it as a "cache key mismatch" which is
inaccurate. The actual issue is unnecessary cache invalidation.

---

CASE: django__django-16256

TYPE: REAL BUG

MECHANISM:

1. Django's QuerySet defines async methods `acreate()`, `aget_or_create()`, and
   `aupdate_or_create()` that wrap the sync versions via `sync_to_async`.
2. Related managers (e.g., `parent.children`) are created dynamically by
   `create_forward_many_to_many_manager()` in related_descriptors.py.
3. These dynamic managers override `create()`, `get_or_create()`, and
   `update_or_create()` to inject the relation filter (e.g., setting the FK).
4. The async variants (`acreate`, etc.) are inherited from QuerySet, NOT from
   the related manager.
5. When user calls `parent.children.acreate(name="x")`, the call goes to
   `QuerySet.acreate()` → `sync_to_async(self.create)()`.
6. `self.create` resolves to `QuerySet.create`, NOT `RelatedManager.create`,
   because `acreate` is defined on QuerySet and `self` is the QuerySet, not
   the manager.
7. The FK value is never set on the created object because the related
   manager's `create()` override (which sets the FK) is bypassed.

Expected: `parent.children.acreate(name="x")` creates a child with FK pointing to parent.
Actual: `acreate` calls QuerySet.create directly, creating an object without the FK set.

ROOT CAUSE: Async CRUD methods on QuerySet bypass the related manager's sync method
overrides because they call `self.create` (QuerySet.create) instead of going through
the manager's overridden create.

WHY PREVIOUS VERSION WAS WRONG: Described it as "async method not delegated" which is
correct in spirit but didn't trace the actual method resolution chain or explain WHY
the FK is missing.

---

CASE: sympy__sympy-13877

TYPE: REAL BUG

MECHANISM:

1. User calls `det()` on a matrix with symbolic entries (e.g., `Matrix([[i + a*j ...]])`
   for size >= 5).
2. `_eval_det_bareiss()` in matrices.py uses the Bareiss algorithm with a helper
   `_find_pivot()` to select pivot elements.
3. `_find_pivot()` at line 178-182 iterates column values and returns the first
   truthy one: `if val:` — this performs a boolean test on a symbolic expression.
4. For certain symbolic expressions, intermediate Bareiss elimination produces
   expressions that simplify to NaN (e.g., 0/0 from cancellation).
5. When `_find_pivot` encounters a NaN value, `if val:` evaluates `bool(NaN)`.
6. `bool(NaN)` in SymPy raises `TypeError: Invalid NaN comparison` because NaN
   has no definite truth value.
7. The exception propagates up, crashing `det()`.

Expected: Determinant computation handles intermediate NaN values gracefully.
Actual: `_find_pivot` crashes on `if val:` when `val` is symbolic NaN.

ROOT CAUSE: `_find_pivot` uses Python truthiness test (`if val:`) on symbolic
expressions, which raises TypeError when the expression is NaN.

WHY PREVIOUS VERSION WAS WRONG: Described it vaguely as "NaN comparison in determinant"
without identifying the specific `if val:` truthiness test in `_find_pivot` as the
crash site.

---

CASE: sympy__sympy-20438

TYPE: REAL BUG

MECHANISM:

1. User calls `FiniteSet(1, 2).is_subset(ProductSet(S.Reals, S.Reals))`.
2. `is_subset` dispatches to handlers in `handlers/issubset.py`.
3. The FiniteSet-to-ProductSet handler checks if each element of the FiniteSet
   is contained in the ProductSet.
4. FiniteSet(1, 2) contains integers (Expr instances), but ProductSet(S.Reals, S.Reals)
   contains tuples.
5. The containment check calls `Eq(element, product_element).simplify()`.
6. `Eq(1, (x, y))` dispatches to `_eval_is_eq` in relational.py.
7. The `@dispatch(Tuple, Expr)` handler at line 1082 returns `False` unconditionally.
8. But `Eq(integer, ProductSet_element)` can also reach the `@dispatch(Basic, Basic)`
   fallback which returns `None` (unknown), creating inconsistent results.
9. `b.is_subset(c)` returns `None` (unknown) while `c.is_subset(b)` returns `True`,
   even though `b == c` as sets.

Expected: `b.is_subset(c)` returns `True` when b and c are equal sets.
Actual: Returns `None` because element-wise equality dispatch produces inconsistent
results when comparing Expr with Tuple types.

ROOT CAUSE: `_eval_is_eq` dispatch in relational.py returns `False` for Tuple-vs-Expr
comparison instead of `None`, and the issubset handler doesn't account for
FiniteSet elements being scalar Expr while ProductSet elements are Tuples.

WHY PREVIOUS VERSION WAS WRONG: Described it generically as "subset handler doesn't
properly check membership" without identifying the specific dispatch mismatch between
Expr and Tuple types in _eval_is_eq.

---

CASE: matplotlib__matplotlib-24870

TYPE: NOT A BUG

The problem statement is titled "[ENH]: Auto-detect bool arrays passed to contour()?"
and the user says: "I find myself fairly regularly calling
`plt.contour(boolean_2d_array, levels=[.5], ...)` to draw the boundary line."

This is an enhancement request. The current behavior is technically correct — contour()
treats boolean arrays as numeric (0/1) and applies the default 8 levels. The output
is technically valid, just not what the user wants for the boolean case. The user is
requesting smart auto-detection of boolean input, not reporting a crash or wrong output.

UNCERTAIN: One could argue the default levels for a [0,1] range are suboptimal (8 levels
all drawn on top of each other at the single boundary), which could be considered a
usability bug. But there is no crash, no exception, and the mathematical output is correct.

WHY PREVIOUS VERSION WAS WRONG: Described "missing type coercion" as if boolean arrays
cause errors. They don't — they produce valid but visually redundant contours.
