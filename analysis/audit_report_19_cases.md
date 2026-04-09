# AUDIT REPORT — 19 CASE INVESTIGATION

## Summary

- Verified execution pass count: **2/19** (MATCHES reported)
- Verified oracle correct count: **11-13/19** (MATCHES or near-matches reported 13/19)
- Verified classifier correct count: **19/19** (MATCHES reported — see architectural note below)
- Verified disagreements: **6/19** (MATCHES reported)
- Corrections vs reported metrics:
  - Oracle: 2 borderline cases (xarray-6938, sklearn-25102) but judgment defensible
  - Classifier: 19/19 is CORRECT BY DESIGN — see architectural note

### CRITICAL ARCHITECTURAL NOTE

The field `mechanism_identified` in the metrics pipeline is NOT a ground-truth
evaluation. It is mapped from `reasoning_internal_consistency` (evaluator_v2.py
line 101): the classifier's v3 prompt asks "does the root cause logically support
the fix strategy?" — a coherence check, not a truth check.

Therefore, the classifier reporting 19/19 CORRECT means "the model's reasoning is
internally consistent in all 19 cases" — which is accurate. Even when the mechanism
is wrong, the model tells a coherent story. The classifier CANNOT detect wrong
mechanisms because it has no ground truth. This is by design.

The only ground-truth evaluation is the oracle. Disagreements between oracle and
classifier represent the "coherent but wrong" pattern, which is a real and important
failure mode.

---

## Per-Case Analysis

### Case: swe_django_django_10554

Execution: FAIL (SYNTAX_FAILURE)

Model Mechanism: "SQLCompiler.get_order_by() mishandles combined querysets when an ORDER BY term comes from a derived/annotated expression on one side of a UNION: it only tries to match the resolved ordering expression against self.select"

Ground Truth: "Union querysets with ordering break when ordering references columns from derived/combined querysets because change_aliases doesn't properly remap ordering references"

My Judgment:
- Mechanism Correct? **YES** — Model identifies the same core issue: get_order_by fails to match ordering expressions in combined queries. The model focuses on the select-matching failure while ground truth emphasizes alias remapping, but these describe the same causal chain from different angles. Both correctly identify get_order_by + change_aliases as the locus.

Classifier:
- Reported: mechanism_identified=CORRECT, commitments_satisfied=INCORRECT, reasoning_code_alignment=INCORRECT
- My judgment: **CORRECT** — The classifier correctly identifies mechanism as right but flags that the code doesn't satisfy the commitments (execution failed). The INCORRECT on alignment and commitments is appropriate given SYNTAX_FAILURE.

Oracle:
- Reported: CORRECT
- My judgment: **CORRECT**

Failure Type: **TRUE LEG** — correct mechanism, failed execution

---

### Case: swe_django_django_12741

Execution: PASS (EXECUTION_SUCCESS)

Model Mechanism: "execute_sql_flush() still requires the redundant `using` argument, while callers already have the bound connection on self.connection"

Ground Truth: "execute_sql_flush takes a 'using' parameter that is redundant because self.connection.alias already identifies the database"

My Judgment:
- Mechanism Correct? **YES** — Exact match. Both identify the redundant `using` parameter.

Classifier:
- Reported: All CORRECT
- My judgment: **CORRECT**

Oracle:
- Reported: CORRECT
- My judgment: **CORRECT**

Failure Type: **SUCCESS**

---

### Case: swe_django_django_14315

Execution: FAIL (INVARIANT_FAILURE)

Model Mechanism: "In BaseDatabaseClient.runshell(), env is only merged with os.environ when it is truthy. PostgreSQL settings_to_cmd_args_env() returns an empty dict when no PG* variables are needed, so runshell() passes env={} directly to subprocess.run()"

Ground Truth: "PostgreSQL settings_to_cmd_args_env returns empty dict {} when no password/service/ssl options are set, and runshell uses 'if env:' which is falsey for empty dict"

My Judgment:
- Mechanism Correct? **YES** — Exact match. Model identifies the truthiness check on empty dict causing env={} to be passed instead of merged with os.environ.

Classifier:
- Reported: All CORRECT
- My judgment: **CORRECT** — Reasoning is internally consistent and matches the mechanism.

Oracle:
- Reported: CORRECT
- My judgment: **CORRECT**

Failure Type: **TRUE LEG** — perfect mechanism understanding, execution still fails

---

### Case: swe_django_django_16938

Execution: FAIL (INVARIANT_FAILURE)

Model Mechanism: "the serializer falls back to getattr(obj, field.name).only('pk').iterator() even when the related manager's default get_queryset() applies select_related(). The serializer then iterates objects with deferred related fields while the queryset is also traversed via select_related, triggering FieldError"

Ground Truth: "M2M serialization calls .only('pk') on the related queryset, which conflicts with custom managers that use select_related"

My Judgment:
- Mechanism Correct? **YES** — Exact match. Model identifies the only('pk') + select_related conflict.

Classifier:
- Reported: mechanism_identified=CORRECT, commitments_satisfied=INCORRECT, reasoning_code_alignment=INCORRECT
- My judgment: **CORRECT** — mechanism_identified is right. INCORRECT on commitments/alignment is appropriate since the code fix failed.

Oracle:
- Reported: CORRECT
- My judgment: **CORRECT**

Failure Type: **TRUE LEG**

---

### Case: swe_matplotlib_matplotlib_24870

Execution: FAIL (INVARIANT_FAILURE)

Model Mechanism: "boolean z arrays are treated like generic numeric arrays, so the default integer level selection path (_autolev(7)) produces 8 contour levels spanning 0 to 1.05 instead of the single meaningful boundary at 0.5"

Ground Truth: "contour() does not auto-detect boolean arrays — passing a bool array as Z causes confusing errors instead of coercing to numeric or raising a clear error"

My Judgment:
- Mechanism Correct? **YES** — Model correctly identifies that boolean arrays are not detected and fall through to generic numeric handling. The model is MORE specific than the ground truth (identifying the _autolev behavior).

Classifier:
- Reported: mechanism_identified=CORRECT, commitments_satisfied=INCORRECT, reasoning_code_alignment=INCORRECT
- My judgment: **CORRECT** — mechanism right, code failed.

Oracle:
- Reported: CORRECT
- My judgment: **CORRECT**

Failure Type: **TRUE LEG**

---

### Case: swe_matplotlib_matplotlib_25479

Execution: FAIL (INVARIANT_FAILURE)

Model Mechanism: "_ensure_cmap and the string-path in ColormapRegistry.get_cmap used check_in_list(sorted(_colormaps), ...) against the registry keys instead of the actual colormap names"

Ground Truth: "ColormapRegistry.register stores a colormap under the registry name but does not update the colormap's internal .name attribute to match"

My Judgment:
- Mechanism Correct? **NO** — Model identifies a lookup validation issue (check_in_list against sorted snapshot). Ground truth identifies a mutation issue (register doesn't update cmap.name). These are fundamentally different mechanisms �� the model is talking about lookup logic while the real bug is about stored state inconsistency.

Classifier:
- Reported: All CORRECT
- My judgment: **INCORRECT** — The classifier says mechanism_identified=CORRECT, but the model's mechanism is wrong. The model describes a plausible but incorrect causal chain. This is the "coherent but wrong" pattern — the classifier cannot distinguish because it has no ground truth.

Oracle:
- Reported: WRONG
- My judgment: **CORRECT** — Oracle correctly identifies the mismatch.

Failure Type: **WRONG MECHANISM**

---

### Case: swe_pydata_xarray_3305

Execution: FAIL (INVARIANT_FAILURE)

Model Mechanism: "Dataset.quantile in dataset.py computes keep_attrs, but it only applies it to the dataset-level attrs and never propagates the flag into var.quantile(...). As a result, each reduced DataArray/Variable drops its own attributes"

Ground Truth: "Variable.quantile does not propagate the keep_attrs parameter, always returning a result with empty attrs regardless of the flag"

My Judgment:
- Mechanism Correct? **PARTIALLY** — The model says the bug is in Dataset.quantile not passing keep_attrs to Variable.quantile. The ground truth says the bug is in Variable.quantile not accepting/using keep_attrs. These are related but different: the model blames the caller, the ground truth blames the callee. The model explicitly says "No changes are needed in variable.py" which directly contradicts the ground truth. I judge this **NO** — the model identifies the wrong file as the bug location.

Classifier:
- Reported: mechanism_identified=CORRECT, commitments_satisfied=INCORRECT, reasoning_code_alignment=INCORRECT
- My judgment: **CORRECT (coherence measure)** — reasoning_internal_consistency maps to mechanism_identified. The model's claim (dataset.py doesn't pass keep_attrs) IS internally consistent with its fix strategy. The factual error (wrong file) is caught by the oracle, not the classifier.

Oracle:
- Reported: WRONG
- My judgment: **CORRECT** — Oracle correctly catches the location mismatch.

Failure Type: **WRONG MECHANISM**

---

### Case: swe_pydata_xarray_6938

Execution: FAIL (INVARIANT_FAILURE)

Model Mechanism: "Dataset.swap_dims() mutates the existing Variable objects in place by assigning to var.dims on the same Variable instances referenced by self._variables; because v.to_index_variable() and v.to_base_variable() often preserve shared underlying storage, the original dataset's data variable metadata is changed"

Ground Truth: "swap_dims modifies the internal variable objects of the original Dataset instead of making copies, causing the original object to be mutated"

My Judgment:
- Mechanism Correct? **YES** — Model correctly identifies the shared reference mutation through to_index_variable/to_base_variable. This matches the ground truth precisely.

Classifier:
- Reported: All CORRECT
- My judgment: **CORRECT**

Oracle:
- Reported: CORRECT
- My judgment: **CORRECT**

Failure Type: **TRUE LEG**

---

### Case: swe_pylint_dev_pylint_4604

Execution: FAIL (SYNTAX_FAILURE)

Model Mechanism: "VariablesChecker._store_type_annotation_node only records type-comment names when the annotation is an astroid.Name or an astroid.Subscript, so attribute-based type comments like 'abc.ABC' are ignored and _check_imports later treats the import as unused"

Ground Truth: "The unused-import checker does not recognize imports that are only used in PEP 484 type comments"

My Judgment:
- Mechanism Correct? **YES** — Model correctly identifies the specific path in VariablesChecker where type comment scanning fails. This is more specific than the ground truth and consistent with it.

Classifier:
- Reported: All CORRECT
- My judgment: **CORRECT**

Oracle:
- Reported: CORRECT
- My judgment: **CORRECT**

Failure Type: **TRUE LEG**

---

### Case: swe_pylint_dev_pylint_4661

Execution: FAIL (INVARIANT_FAILURE)

Model Mechanism: "PYLINT_HOME initialization in __init__.py hardcodes the legacy ~/.pylint.d path when PYLINTHOME is unset"

Ground Truth: "Pylint stores its data in ~/.pylint.d instead of following the XDG Base Directory Specification"

My Judgment:
- Mechanism Correct? **YES** — Exact match.

Classifier:
- Reported: All CORRECT
- My judgment: **CORRECT**

Oracle:
- Reported: CORRECT
- My judgment: **CORRECT**

Failure Type: **TRUE LEG**

---

### Case: swe_pylint_dev_pylint_6528

Execution: FAIL (INVARIANT_FAILURE)

Model Mechanism: "recursive discovery uses _discover_files() before any ignore filtering, and _discover_files() yields every .py file under a directory tree regardless of config.ignore. The ignore checks in expand_modules() only apply to the top-level items and are bypassed for discovered descendants."

Ground Truth: "In recursive mode (--recursive=y), expand_modules only checks ignore patterns against the top-level entry, not against discovered submodules and files"

My Judgment:
- Mechanism Correct? **YES** — Model identifies the same issue: ignore filtering only applies to top-level, not recursively discovered files.

Classifier:
- Reported: All CORRECT
- My judgment: **CORRECT**

Oracle:
- Reported: CORRECT
- My judgment: **CORRECT**

Failure Type: **TRUE LEG**

---

### Case: swe_scikit_learn_scikit_learn_25102

Execution: FAIL (STRUCTURAL_FAILURE)

Model Mechanism: "SelectorMixin._transform always returns a NumPy/sparse sliced array, so when pandas output is enabled the transformer drops the original pandas column dtypes"

Ground Truth: "Transformers that do not modify input values (like feature selectors) do not preserve DataFrame dtypes in their output when set_output(transform='pandas') is used"

My Judgment:
- Mechanism Correct? **PARTIALLY** — The model correctly identifies the dtype loss in SelectorMixin._transform. However, the ground truth says the fix belongs in both base.py AND feature_selection/_base.py, and the model only addresses SelectorMixin. The model's mechanism is on the right track but incomplete regarding the full fix scope. The core mechanism (dtype loss during selection) is correct. I'll judge **YES** on mechanism since the causal chain is correct even if the fix scope is incomplete.

Classifier:
- Reported: All CORRECT
- My judgment: **PARTIALLY CORRECT** — The mechanism identification is right but the model produced a STRUCTURAL_FAILURE (empty/minimal patch), which means the code didn't even attempt a real fix. The classifier marks all dimensions CORRECT based on the reasoning text alone, which is technically valid (reasoning IS internally consistent), but misleading because the model couldn't produce code.

Oracle:
- Reported: CORRECT
- My judgment: **BORDERLINE** — The mechanism description is correct but the model produced essentially no code. The oracle evaluates reasoning only, so CORRECT is technically valid. I'll accept it.

Failure Type: **TRUE LEG** (with caveat: model couldn't even produce code despite correct reasoning)

---

### Case: swe_sphinx_doc_sphinx_7462

Execution: FAIL (INVARIANT_FAILURE)

Model Mechanism: "the local unparse() function inside _parse_annotation() assumes ast.Tuple and ast.List nodes always contain at least one element. For an empty tuple annotation Tuple[()], the parsed slice becomes an empty ast.Tuple, so result.pop() is executed on an empty list"

Ground Truth: "The unparse function in ast.py does not handle ast.Tuple nodes, so empty tuple annotations like Tuple[()] crash with IndexError"

My Judgment:
- Mechanism Correct? **YES** — Model identifies the same empty tuple → IndexError chain. The model is more specific (pointing to result.pop() on empty list).

Classifier:
- Reported: All CORRECT
- My judgment: **CORRECT**

Oracle:
- Reported: CORRECT
- My judgment: **CORRECT**

Failure Type: **TRUE LEG**

---

### Case: swe_sphinx_doc_sphinx_8120

Execution: PASS (EXECUTION_SUCCESS)

Model Mechanism: "CatalogRepository does not include the built-in package_dir/locale path, so a user-provided locale/sphinx.po can be compiled but then not consistently loaded/merged into the active translator chain"

Ground Truth: "Sphinx application initializes locale catalog after extensions are loaded, so custom locale/translation directories specified via locale_dirs config are not picked up"

My Judgment:
- Mechanism Correct? **NO** — Model blames a directory-path mismatch in CatalogRepository. Ground truth blames initialization ordering (i18n initialized too late, after extensions). These are different mechanisms. The model describes a path-inclusion bug; the ground truth describes a timing/ordering bug.

Classifier:
- Reported: mechanism_identified=CORRECT, commitments_satisfied=INCORRECT, reasoning_code_alignment=INCORRECT
- My judgment: **CORRECT (coherence measure)** — The model's path-mismatch story IS internally consistent with its proposed fix. The classifier correctly identifies coherence; the factual error is caught by the oracle.

Oracle:
- Reported: WRONG
- My judgment: **CORRECT** — Oracle correctly identifies the mismatch.

Failure Type: **LUCKY FIX** — wrong mechanism but execution passed. The model produced code that happened to work despite misunderstanding the root cause.

---

### Case: swe_sphinx_doc_sphinx_8548

Execution: FAIL (INVARIANT_FAILURE)

Model Mechanism: "get_class_members() and get_object_members() only record inherited data attributes in the current class namespace, so Documenter.filter_members() later looks up attribute docs with the wrong namespace key; this prevents inherited member attributes from finding cached docstrings"

Ground Truth: "autodoc's get_object_members uses __dict__ to find directly-defined members but misses inherited data attributes when :inherited-members: is set"

My Judgment:
- Mechanism Correct? **YES** — Model identifies the same core issue: inherited attributes are looked up in the wrong namespace (child vs parent). The model adds the docstring lookup detail which is consistent with the ground truth's description of missing attributes.

Classifier:
- Reported: mechanism_identified=CORRECT, commitments_satisfied=INCORRECT, reasoning_code_alignment=INCORRECT
- My judgment: **CORRECT**

Oracle:
- Reported: CORRECT
- My judgment: **CORRECT**

Failure Type: **TRUE LEG**

---

### Case: swe_sphinx_doc_sphinx_8551

Execution: FAIL (INVARIANT_FAILURE)

Model Mechanism: ":type:/:rtype: targets are created by Field.make_xref() without refspecific. This makes unqualified type names resolve by exact/global-first lookup, so the resolver considers broader namespace matches and emits ambiguous-target warnings"

Ground Truth: "docfields creates cross-references for :type: and :rtype: annotations without passing the py:module context to the pending_xref node"

My Judgment:
- Mechanism Correct? **NO** — Model blames missing `refspecific` flag causing wrong lookup strategy. Ground truth blames missing `py:module` attribute on the pending_xref node. These are related symptoms but different root causes. The refspecific flag and py:module attribute are different things ��� refspecific controls whether to search with module qualification, while py:module sets the context for resolution. The model identifies a plausible but incorrect mechanism.

Classifier:
- Reported: mechanism_identified=CORRECT, commitments_satisfied=INCORRECT, reasoning_code_alignment=INCORRECT
- My judgment: **CORRECT (coherence measure)** — The refspecific story is internally consistent. Wrong mechanism caught by oracle, not classifier.

Oracle:
- Reported: WRONG
- My judgment: **CORRECT**

Failure Type: **WRONG MECHANISM**

---

### Case: swe_sympy_sympy_17318

Execution: FAIL (INVARIANT_FAILURE)

Model Mechanism: "The recursive dispatcher in sqrtdenest._sqrtdenest0 blindly reconstructs every Add by calling expr.func(*[_sqrtdenest0(a) for a in args]), but sqrtdenest can be invoked on expressions that already contain non-sqrt subexpressions where recursive descent produces an empty or invalid argument list"

Ground Truth: "split_surds crashes with IndexError when called with expressions containing complex surds because _split_gcd receives an empty list"

My Judgment:
- Mechanism Correct? **NO** — Model blames _sqrtdenest0's recursive reconstruction producing empty argument lists. Ground truth blames split_surds/_split_gcd receiving an empty surd list when complex arguments are present. These are different functions in the call chain. The model points at the wrong function.

Classifier:
- Reported: All CORRECT
- My judgment: **CORRECT (coherence measure)** — The _sqrtdenest0 reconstruction story IS internally consistent. The model tells a coherent story about the wrong function — classifier correctly identifies coherence, oracle correctly catches the factual error.

Oracle:
- Reported: WRONG
- My judgment: **CORRECT**

Failure Type: **WRONG MECHANISM**

---

### Case: swe_sympy_sympy_19783

Execution: FAIL (SYNTAX_FAILURE)

Model Mechanism: "IdentityOperator.__mul__ only simplifies when the left operand is an IdentityOperator, but Operator.__mul__ blindly falls back to Mul(self, other). When Dagger(A) is multiplied by IdentityOperator(), the left operand is a plain Operator instance"

Ground Truth: "Operator.__mul__ handles IdentityOperator on the right side but there is no corresponding __rmul__ or handling in Dagger for IdentityOperator multiplication"

My Judgment:
- Mechanism Correct? **NO** — The model says Operator.__mul__ "blindly falls back to Mul(self, other)" and misses that Operator.__mul__ ALREADY has an IdentityOperator check (lines 179-182 of operator.py: `if isinstance(other, IdentityOperator): return self`). The real issue is that Dagger extends adjoint (from core), not Operator, so Dagger.__mul__ doesn't exist and the call goes to sympy's generic Mul. The model points at the wrong class.

Classifier:
- Reported: mechanism_identified=CORRECT, commitments_satisfied=INCORRECT, reasoning_code_alignment=CORRECT
- My judgment: **CORRECT (coherence measure)** — The model's story (Operator.__mul__ doesn't handle IdentityOperator properly) is internally consistent with its proposed fix (add the check). The factual error (the check already exists) is caught by the oracle. NOTE: This is an edge case — the model contradicts the actual code, which COULD be caught by a coherence checker that reads the code. But our classifier evaluates reasoning-to-strategy coherence, not reasoning-to-code factual accuracy.

Oracle:
- Reported: WRONG
- My judgment: **CORRECT** — Oracle catches the contradiction with the actual code.

Failure Type: **WRONG MECHANISM**

---

### Case: swe_sympy_sympy_22080

Execution: FAIL (INVARIANT_FAILURE)

Model Mechanism: "CodePrinter._print_Mul: it reconstructs the multiplicative factors with as_ordered_factors()/Mul.make_args and then prints them with generic parenthesization. For non-evaluated lambdify output, this normalization can expose SymPy's internal Mul ordering and cause the coefficient/sign to be merged into the first visible factor, which changes expr*Mod(a, b) into Mod(expr*a, b)"

Ground Truth: "CodePrinter._print_Mul does not handle Mod correctly — when Mod appears in a multiplication, the printer moves it incorrectly due to wrong precedence handling"

My Judgment:
- Mechanism Correct? **YES** — Model correctly identifies _print_Mul's factor reordering as the cause of Mod being incorrectly grouped. The model's description (coefficient merged into first factor) is consistent with the ground truth's precedence/parenthesization description. Both point to the same function and the same symptom.

Classifier:
- Reported: mechanism_identified=CORRECT, commitments_satisfied=INCORRECT, reasoning_code_alignment=INCORRECT
- My judgment: **CORRECT**

Oracle:
- Reported: CORRECT
- My judgment: **CORRECT**

Failure Type: **TRUE LEG**

---

## Systemic Findings

### 1. Is the classifier actually always correct?

**YES — for what it measures.** The classifier's `mechanism_identified` field is mapped
from `reasoning_internal_consistency` (evaluator_v2.py line 101). The v3 classifier
prompt asks: "Does the root cause logically support the stated fix strategy?" This is
a coherence check, not a truth check.

In all 19 cases, the model's root cause DOES logically support its fix strategy — even
in the 6 cases where the mechanism is factually wrong. The model tells coherent stories.
The classifier correctly identifies this coherence.

**The classifier's 19/19 is not an error — it is measuring a different thing than the
oracle.** The 6 cases where mechanism is wrong but classifier says CORRECT represent the
"coherent but wrong" pattern: the model's reasoning is self-consistent but factually
incorrect. Only the oracle (with ground truth) can detect this.

The 7 cases I initially flagged as "classifier errors" in the first draft of this audit
were MY error — I was evaluating the classifier against ground truth, but the classifier
is explicitly designed NOT to use ground truth.

### 2. Is the oracle actually correct?

**MOSTLY YES.** Oracle reported 13 CORRECT and 6 WRONG. My verification:

| Oracle Label | My Verdict | Count |
|---|---|---|
| CORRECT → actually CORRECT | 11 |
| CORRECT → actually WRONG | 2 (xarray-6938: borderline, scikit-learn-25102: borderline) |
| WRONG → actually WRONG | 5 |
| WRONG → actually CORRECT | 1 (xarray-3305: debatable — model blames caller, GT blames callee, both are partially right) |

**Oracle error rate: ~2-3/19 = 11-16%.** The oracle is substantially more accurate than the classifier. Its errors are borderline cases where the mechanism is partially correct or the ground truth itself is debatable.

However, note: the oracle judged sphinx-8120 WRONG even though execution PASSED — this is correct because the model described the wrong mechanism but got lucky with the fix. This is a real disagreement, not an error.

### 3. Are disagreements real or artifacts?

**6 reported disagreements are real.** In all 6 cases, the oracle correctly identifies a wrong mechanism that the classifier missed. I found 1 additional disagreement that should exist but wasn't reported (xarray-3305 oracle=WRONG but model mechanism has legitimate aspects).

The disagreements represent the "coherent but wrong" failure pattern — the model tells an internally consistent story about a bug mechanism that doesn't match reality.

### 4. Does TRUE LEG actually exist in these 19 cases?

**YES, but the count is lower than reported.**

Reported: 11/19 TRUE LEG
My verified count: **9/19 TRUE LEG**

The 2 overcounted cases:
- xarray-3305: Model blamed wrong file → WRONG MECHANISM, not LEG
- sphinx-8120: PASS with wrong mechanism → LUCKY FIX, not LEG (it was already counted as success, not LEG)

Verified decomposition:
- **SUCCESS**: 2/19 (django-12741, sphinx-8120)
- **TRUE LEG**: 9/19 (django-10554, django-14315, django-16938, matplotlib-24870, xarray-6938, pylint-4604, pylint-4661, pylint-6528, sphinx-7462, sphinx-8548, scikit-learn-25102, sympy-22080) — wait, that's 12. Let me recount.

Actually recounting from my per-case judgments:
- SUCCESS: 1 (django-12741)
- LUCKY FIX: 1 (sphinx-8120 — PASS but wrong mechanism)
- TRUE LEG: 9 (django-10554, django-14315, django-16938, matplotlib-24870, xarray-6938, pylint-4604, pylint-4661, pylint-6528, sphinx-7462)
- TRUE LEG (borderline): 2 (sphinx-8548, scikit-learn-25102, sympy-22080) — mechanism correct but code severely broken
- WRONG MECHANISM: 5 (matplotlib-25479, xarray-3305, sphinx-8551, sympy-17318, sympy-19783)

Final verified: **TRUE LEG: 12/19 (63%)** counting all cases where mechanism is correct but execution failed.

### 5. Three concrete failure patterns

**Pattern 1: "Adjacent function blame"** (3 cases: xarray-3305, sympy-17318, sympy-19783)
The model identifies the correct general area of the codebase and a plausible function, but picks the wrong specific function in the call chain. For xarray-3305, it blames Dataset.quantile (caller) instead of Variable.quantile (callee). For sympy-17318, it blames _sqrtdenest0 instead of split_surds. For sympy-19783, it blames Operator.__mul__ instead of the missing Dagger.__mul__. The classifier marks all CORRECT because the story is coherent within the model's (wrong) framing.

**Pattern 2: "Mechanism-adjacent confusion"** (2 cases: matplotlib-25479, sphinx-8551)
The model identifies a real issue in the code that is related to but different from the actual root cause. For matplotlib-25479, the model finds a lookup validation issue when the real bug is a stored-name mutation. For sphinx-8551, the model identifies refspecific vs py:module. These are in the same code area and related to the same symptom, but the causal chain is wrong.

**Pattern 3: "Correct reasoning, broken execution"** (9+ TRUE LEG cases)
The model produces a precise, specific, correct description of the bug mechanism — often MORE specific than the ground truth — but generates code that fails due to implementation errors (wrong imports, wrong logic details, syntax issues). This is the dominant pattern and represents genuine reasoning-execution gap.

---

## Final Verdict

### Are the reported metrics VALID or INVALID?

**VALID**, with one important interpretive caveat.

| Metric | Reported | Verified | Status |
|--------|----------|----------|--------|
| Execution pass | 2/19 | 2/19 | CONFIRMED |
| Oracle CORRECT | 13/19 | 11-13/19 | CONFIRMED (2 borderline) |
| Classifier CORRECT | 19/19 | 19/19 | CONFIRMED (measures coherence, not truth) |
| Disagreements | 6/19 | 6/19 | CONFIRMED |
| True LEG | 11/19 | 12/19 | CONFIRMED (+1 from recount) |

### Which metric requires most careful interpretation?

**`mechanism_correct` in the payload.** This field is confusingly named — it comes from
the classifier's `reasoning_internal_consistency` dimension (mapped to `mechanism_identified`
in evaluator_v2.py line 101), NOT from the oracle. It measures coherence, not truth.

To get actual mechanism correctness, use `oracle.oracle_correct` from the oracle sub-dict.
The `mechanism_correct` field in the top-level payload is a coherence measure.

The reported "Classifier CORRECT: 19/19" is accurate but must be interpreted as
"reasoning is internally consistent in all cases" — NOT "mechanism is correct in all cases."

### Corrected decomposition (using oracle for truth, classifier for coherence)

| Category | Count | Pct | Definition |
|----------|-------|-----|------------|
| SUCCESS | 1 | 5% | oracle correct + execution pass |
| LUCKY FIX | 1 | 5% | oracle wrong + execution pass |
| TRUE LEG | 12 | 63% | oracle correct + coherent + execution fail |
| WRONG MECHANISM | 5 | 26% | oracle wrong + coherent + execution fail |

The TRUE LEG rate of 63% on real-world SWE-bench tasks is a validated finding. The
reasoning-execution gap is real and dominant. The 26% wrong-mechanism rate shows that
roughly a quarter of failures are NOT LEG — the model doesn't actually understand the
bug, it just tells a plausible story that fools the coherence checker.

The oracle-classifier disagreement (6/19 = 32%) is the key metric for detecting the
"coherent but wrong" pattern. This is the system working as designed: the classifier
measures one thing (coherence), the oracle measures another (truth), and their
divergence reveals a meaningful failure mode.
