# EPISTEMIC AUDIT — ALL 71 SWE-BENCH CASES (FINAL)

## SUMMARY

| Status | Count |
|--------|-------|
| VERIFIED (real bugs) | 39 |
| VERIFIED (not-a-bug) | 7 |
| RECONSTRUCTED | 17 |
| SPECULATIVE | 7 |
| AMBIGUOUS | 1 |
| **TOTAL** | **71** |

---

## VERIFIED — REAL BUGS (39)

### astropy__astropy-14369
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read p_division_of_units (cds.py line 182-190). Line 185: grammar rule is 'unit_expression DIVISION combined_units'. Wrong associativity for division.
CONFIDENCE: HIGH

### astropy__astropy-8707
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read Header.fromstring (header.py line 330-338). Parameter is 'data: str'. No isinstance(data, bytes) check. No bytes→str conversion.
CONFIDENCE: HIGH

### django__django-10554
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read change_aliases (query.py line 822-856): remaps self.where, self.group_by, self.select, self.annotations. Does NOT remap ordering expressions. ORDER BY references stale aliases after union.
CONFIDENCE: HIGH

### django__django-11138
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read MySQL operations.py line 73: CONVERT_TZ(%s, 'UTC', '%s') hardcodes 'UTC'. Oracle operations.py line 104: FROM_TZ(%s, '0:00') hardcodes '0:00'.
CONFIDENCE: HIGH

### django__django-11333
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read get_resolver (resolvers.py line 67): @lru_cache. Read set_urlconf (base.py line 127): deletes thread-local. Read base.py line 95: get_resolver.cache_clear() — unconditional on every request.
CONFIDENCE: HIGH

### django__django-11734
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read split_exclude (query.py line 1685-1706). Line 1705: isinstance(filter_rhs, F) catches OuterRef. Line 1706 wraps with OuterRef() incorrectly.
CONFIDENCE: HIGH

### django__django-11885
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read Collector (deletion.py line 64-72). self.data = {} at line 68. self.fast_deletes = [] at line 72. Each relation appends separate queryset.
CONFIDENCE: HIGH

### django__django-12155
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read trim_docstring (utils.py line 27-39). Line 37: indent = min(...) includes first line in calculation. When first line has text, indentation calc is skewed.
CONFIDENCE: HIGH

### django__django-12406
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read ModelChoiceField.__init__ (models.py line 1184-1191). empty_label set by required+initial check. No blank attribute check. ForeignKey.formfield (line 978) doesn't pass blank.
CONFIDENCE: HIGH

### django__django-13121
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read combine_duration_expression (sqlite3/operations.py line 339-345). Uses django_format_dtdelta for ALL duration expressions. No duration+duration special case.
CONFIDENCE: HIGH

### django__django-13195
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read delete_cookie (response.py line 213): def delete_cookie(self, key, path='/', domain=None). NO samesite parameter.
CONFIDENCE: HIGH

### django__django-13512
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read display_for_field (utils.py line 401-403): calls field.get_prep_value(value) which uses json.dumps() with default ensure_ascii=True. Unicode escaped to \uXXXX.
CONFIDENCE: HIGH

### django__django-14170
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read YearLookup (lookups.py line 540-561). year_lookup_bounds calls year_lookup_bounds_for_date_field. No iso_year-specific bounds.
CONFIDENCE: HIGH

### django__django-14315
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read both source files. settings_to_cmd_args_env returns {} (line 44-54 of postgresql/client.py). runshell checks `if env:` (line 26 of base/client.py). Empty dict is falsey. subprocess.run(env={}) strips environment.
CONFIDENCE: HIGH

### django__django-14376
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read MySQL base.py: uses 'db' and 'passwd' kwargs. Deprecated in newer MySQL connectors.
CONFIDENCE: HIGH

### django__django-14631
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read _clean_fields (forms.py line 389-406). Line 394: calls self._field_data_value() directly. Does NOT go through BoundField.value().
CONFIDENCE: HIGH

### django__django-16256
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read RelatedManager.create (line 788): sets kwargs[self.field.name] = self.instance. Confirmed acreate NOT defined on RelatedManager. Patch adds it, confirming inherited version bypasses override.
CONFIDENCE: HIGH

### django__django-16631
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read get_session_auth_hash (base_user.py line 134-143): uses salted_hmac with no SECRET_KEY_FALLBACKS logic. Only current SECRET_KEY.
CONFIDENCE: HIGH

### django__django-16938
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read handle_m2m_field in python.py (line 82): `.only('pk')`. Custom manager with select_related conflicts with only(). Django raises FieldError.
CONFIDENCE: HIGH

### matplotlib__matplotlib-24870
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read _process_contour_level_args (contour.py line 1120). Line 1126: levels_arg=7 hardcoded. For zmin=0,zmax=1 (boolean), produces 7 identical boundary contours.
CONFIDENCE: HIGH

### matplotlib__matplotlib-25479
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read ColormapRegistry.register (cm.py line 103-142). Line 130: name = name or cmap.name. Stores copy but never updates copy's .name attribute.
CONFIDENCE: HIGH

### mwaskom__seaborn-3187
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read Continuous._get_formatter (scales.py line 615-652). Line 650: default case returns ScalarFormatter() with no set_useOffset(False). Offset enabled by default for large ranges.
CONFIDENCE: HIGH

### pydata__xarray-3305
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read Variable.quantile (variable.py line 1595): signature is quantile(self, q, dim=None, interpolation='linear'). NO keep_attrs parameter. Constructs result without self.attrs.
CONFIDENCE: HIGH

### pydata__xarray-6938
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read swap_dims (dataset.py line 3770-3776). Line 3775: var = v.to_index_variable(). Line 3776: var.dims = dims. If to_index_variable returns same object, this mutates original.
CONFIDENCE: HIGH

### pylint-dev__pylint-6528
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read expand_modules (line 49-69). Ignore check at line 64-68 only applies to top-level entries. Recursively discovered files bypass ignore patterns.
CONFIDENCE: HIGH

### pylint-dev__pylint-8898
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read _regexp_csv_transfomer (argument.py line 114-119): calls _csv_transformer → _check_csv → _splitstrip which splits on comma naively. Regex quantifiers like {1,2} are mangled.
CONFIDENCE: HIGH

### scikit-learn__scikit-learn-12682
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read transform (line 899-903): calls sparse_encode without max_iter. Read sparse_encode (line 187): accepts max_iter=1000 default. SparseCoder.__init__ has no max_iter parameter.
CONFIDENCE: HIGH

### scikit-learn__scikit-learn-25102
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read SelectorMixin._transform (_base.py line 92-104). Line 104: return X[:, safe_mask(X, mask)]. DataFrame→ndarray conversion erases per-column dtypes.
CONFIDENCE: HIGH

### sphinx-doc__sphinx-7462
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read unparse (ast.py line 61). No ast.Tuple handler in elif chain. Empty tuple annotation falls through, causing IndexError on element access.
CONFIDENCE: HIGH

### sphinx-doc__sphinx-8548
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read get_class_members (importer.py line 254-298). Line 296: inherited attrs get ClassAttribute(None, ...). None class tag breaks docstring lookup for inherited data attrs.
CONFIDENCE: HIGH

### sphinx-doc__sphinx-8551
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read PyXrefMixin.make_xref (python.py line 269): sets result['refspecific']=True but does NOT set py:module on the pending_xref node.
CONFIDENCE: HIGH

### sphinx-doc__sphinx-9461
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read isclassmethod (inspect.py line 248-255). Checks isinstance(obj, classmethod) and ismethod. @classmethod @property creates classmethod_descriptor — neither check catches it.
CONFIDENCE: HIGH

### sympy__sympy-13091
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read Basic.__eq__ (basic.py line 282-316). Line 314: _sympify(other). Line 316: return False on SympifyError. Should return NotImplemented.
CONFIDENCE: HIGH

### sympy__sympy-13877
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read _find_pivot (matrices.py line 178-182): `if val:` on line 180. Bareiss elimination can produce NaN intermediates. bool(NaN) raises TypeError.
CONFIDENCE: HIGH

### sympy__sympy-14248
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read _print_MatAdd: str.py line 314-316 uses ' + '.join(); latex.py line 1479-1482 uses ' + '.join(). Neither checks for negative coefficients.
CONFIDENCE: HIGH

### sympy__sympy-17318
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read split_surds (radsimp.py line 1062-1100). Line 1078: surds = [x[1]**2 for x in coeff_muls if x[1].is_Pow]. Line 1080: _split_gcd(*surds). Empty surds list causes IndexError.
CONFIDENCE: HIGH

### sympy__sympy-19783
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read Operator.__mul__ (operator.py line 179-184): checks isinstance(other, IdentityOperator). Dagger extends adjoint (not Operator), so Dagger.__mul__ does not exist. Falls through to generic Mul.
CONFIDENCE: HIGH

### sympy__sympy-20438
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read comparison.py: no @dispatch(FiniteSet, ProductSet) handler. Read issubset.py: no (FiniteSet, ProductSet) handler. Fallback @dispatch(Set, Set) returns None. Asymmetric results.
CONFIDENCE: HIGH

### sympy__sympy-22080
TYPE: REAL BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Read _print_Mul (codeprinter.py line 454-503). Line 458: as_coeff_Mul() can absorb coefficient into Mod. No Mod in PRECEDENCE dict. as_ordered_factors at line 471 rearranges.
CONFIDENCE: HIGH

---

## VERIFIED — NOT A BUG (7)

### django__django-12741
TYPE: NOT A BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Issue says 'The using argument can be dropped and inferred.' No runtime failure. API cleanup.
CONFIDENCE: HIGH

### django__django-15103
TYPE: NOT A BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Issue says 'I wanted to use json_script but I didn't need any id.' Feature request.
CONFIDENCE: HIGH

### django__django-16560
TYPE: NOT A BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Issue says 'Allow to customize the code attribute.' Feature request.
CONFIDENCE: HIGH

### matplotlib__matplotlib-25775
TYPE: NOT A BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Issue title: '[ENH]: Add get/set_antialiased to Text objects.' Enhancement.
CONFIDENCE: HIGH

### pydata__xarray-3993
TYPE: NOT A BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Issue: 'just a minor gripe' about dim vs coord parameter naming. API cleanup.
CONFIDENCE: HIGH

### pylint-dev__pylint-4551
TYPE: NOT A BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Issue: 'Use Python type hints for UML generation.' Feature request.
CONFIDENCE: HIGH

### pylint-dev__pylint-4661
TYPE: NOT A BUG
EPISTEMIC STATUS: VERIFIED
EVIDENCE: Issue: 'Make pylint XDG Base Directory Specification compliant.' Standards compliance request.
CONFIDENCE: HIGH

---

## RECONSTRUCTED (17)

### django__django-11400
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: field_choices gets ordering from admin but the exact propagation to get_choices not fully traced in RelatedOnlyFieldListFilter subclass.
CONFIDENCE: MEDIUM

### django__django-11532
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: sanitize_address crash on non-ASCII domain. Inline .encode('idna') pattern confirmed from patch but exact crash path through sanitize_address not traced.
CONFIDENCE: MEDIUM

### django__django-13344
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: process_response receives coroutine instead of HttpResponse. Async middleware chain not fully traced.
CONFIDENCE: MEDIUM

### django__django-14011
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: ThreadedWSGIServer thread cleanup. Missing close_old_connections in thread handling inferred but exact thread lifecycle not traced.
CONFIDENCE: MEDIUM

### django__django-15561
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: choices-only AlterField triggering table rebuild. Schema comparison logic in _alter_field too complex to pinpoint exact choices-skip logic.
CONFIDENCE: MEDIUM

### django__django-15563
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: UPDATE targeting wrong table in MTI. Compiler's UPDATE path and table resolution not traced.
CONFIDENCE: MEDIUM

### django__django-15629
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: db_collation not propagated to FK. ForeignKey field creation and collation inheritance not traced.
CONFIDENCE: MEDIUM

### django__django-16032
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: __in not clearing aliased annotations. Subquery clearing logic for alias() not traced.
CONFIDENCE: MEDIUM

### django__django-16263
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: COUNT queries including unused annotations. Annotation stripping logic not traced.
CONFIDENCE: MEDIUM

### django__django-16315
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: bulk_create mixed-case columns in ON CONFLICT. Case-sensitive comparison point not traced.
CONFIDENCE: MEDIUM

### pydata__xarray-3095
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: Deep copy using np.array() casts unicode indices. Variable.copy deep=True path not fully read.
CONFIDENCE: MEDIUM

### pylint-dev__pylint-4604
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: Type comment scanning in VariablesChecker. _store_type_annotation_names function body not fully read.
CONFIDENCE: MEDIUM

### pylint-dev__pylint-6386
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: verbose -v requiring argument. _DoNothingAction interaction with argparse not traced.
CONFIDENCE: MEDIUM

### pytest-dev__pytest-5840
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: Windows path casing in conftest loading. Exact case-sensitive comparison point not found in source.
CONFIDENCE: MEDIUM

### pytest-dev__pytest-8399
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: unittest fixture visibility regression. _inject_setup_class_fixture internals not traced.
CONFIDENCE: MEDIUM

### sphinx-doc__sphinx-10673
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: genindex/modindex/search rejected from toctree. Document validation point not found in TocTree.run excerpt.
CONFIDENCE: MEDIUM

### sphinx-doc__sphinx-8593
TYPE: REAL BUG
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: :meta public: not checked for variables. Variable documenter meta check absence inferred but exact code path not traced.
CONFIDENCE: MEDIUM

---

## SPECULATIVE (7)

### astropy__astropy-13398
TYPE: REAL BUG (assumed)
EPISTEMIC STATUS: SPECULATIVE
UNCERTAINTY: ITRS-to-observed transform. Complex coordinate system. EARTH_CENTER hardcoding inferred from patch, not read in source.
CONFIDENCE: LOW

### django__django-12325
TYPE: REAL BUG (assumed)
EPISTEMIC STATUS: SPECULATIVE
UNCERTAINTY: pk confusion with multiple OneToOneFields. options.py pk detection logic not read.
CONFIDENCE: LOW

### matplotlib__matplotlib-14623
TYPE: REAL BUG (assumed)
EPISTEMIC STATUS: SPECULATIVE
UNCERTAINTY: Log scale axis inversion. ticker.py limit sorting not read.
CONFIDENCE: LOW

### pydata__xarray-6992
TYPE: REAL BUG (assumed)
EPISTEMIC STATUS: SPECULATIVE
UNCERTAINTY: _coord_names/_variables inconsistency after index refactor. Internal state management not traced.
CONFIDENCE: LOW

### sphinx-doc__sphinx-7590
TYPE: REAL BUG (assumed)
EPISTEMIC STATUS: SPECULATIVE
UNCERTAINTY: C++ UDL parser support. Parser behavior on UDL input unknown — crash vs silent skip unclear.
CONFIDENCE: LOW

### sphinx-doc__sphinx-8120
TYPE: REAL BUG (assumed)
EPISTEMIC STATUS: SPECULATIVE
UNCERTAINTY: Locale initialization order. Did not read Sphinx.__init__ to verify order of locale init vs extension loading.
CONFIDENCE: LOW

### sympy__sympy-16597
TYPE: REAL BUG (assumed)
EPISTEMIC STATUS: SPECULATIVE
UNCERTAINTY: is_even → is_finite implication. Assumption rules table not read.
CONFIDENCE: LOW

---

## AMBIGUOUS (1)

### django__django-13212
TYPE: AMBIGUOUS
EPISTEMIC STATUS: RECONSTRUCTED
UNCERTAINTY: Validators not including value in ValidationError params. Debatable: bug (docs recommend including value) vs feature (adding %(value)s support).
CONFIDENCE: MEDIUM
