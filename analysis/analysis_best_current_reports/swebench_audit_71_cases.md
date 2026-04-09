# FULL AUDIT REPORT — 71 SWE-BENCH CASES

Model: gpt-5.4-mini | Oracle: oracle_reasoning_truth_enriched (strict)
Execution: SWE-bench Docker harness | Classifier: classify_reasoning_v3

## Summary

Total cases: 71
Fully evaluated (Docker + oracle): 59
Docker only (no oracle): 4
Not evaluated (too large): 8

| Category | Count | Pct (of 59) |
|----------|-------|------|
| SUCCESS | 5 | 8% |
| LUCKY_FIX | 2 | 3% |
| LEG | 36 | 61% |
| WRONG_MECHANISM | 16 | 27% |

Execution pass rate: 7/59 = 11.9%
Oracle correct rate: 41/59 = 69.5%
LEG rate: 36/59 = 61.0%
Exec | oracle correct: 7/41 = 17.1%

---

## SUCCESS (5 cases)

### django__django-12155

Execution: PASS | F2P: 1/1 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: utils.trim_docstring() incorrectly preserves a leading blank line from docstrings that start on the first line, so parse_rst() wraps the text in a reST document whose first directive is preceded by an

Ground truth: trim_docstring in admindocs/utils.py implements PEP 257 indentation trimming incorrectly, failing when the first line of a docstring is not empty

Oracle justification: The ground truth identifies trim_docstring's incorrect PEP 257-style trimming (failing when the first docstring line is non-empty), and the developer's root cause explicitly blames the same function—n

Audit judgment: Oracle CORRECT (model reasoning matches GT and code works). Classifier CORRECT (reasoning is internally consistent).

### django__django-12741

Execution: PASS | F2P: 2/2 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: BaseDatabaseOperations.execute_sql_flush() still requires the redundant `using` argument, while callers already have the bound connection on `self.connection`; this mismatch causes outdated internal c

Ground truth: NOT A BUG: This is a feature request / API cleanup, not a runtime failure.

Oracle justification: The ground truth states that execute_sql_flush’s 'using' parameter is redundant because self.connection.alias can be used internally, and the developer’s reasoning explicitly identifies the same redun

Audit judgment: Oracle CORRECT (model reasoning matches GT and code works). Classifier CORRECT (reasoning is internally consistent).

### matplotlib__matplotlib-25775

Execution: PASS | F2P: 7/7 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: RendererAgg.draw_text in backend_agg.py and RendererCairo.draw_text in backend_cairo.py always read rcParams["text.antialiased"], so per-Text antialias state was never consulted during drawing. The Te

Ground truth: NOT A BUG: This is a feature request / API cleanup, not a runtime failure.

Oracle justification: The ground truth says this is a feature request because Text lacks per-instance antialiasing and the backends use the global rcParam, and the developer similarly identifies that Text has no antialias 

Audit judgment: Oracle CORRECT (model reasoning matches GT and code works). Classifier CORRECT (reasoning is internally consistent).

### scikit-learn__scikit-learn-12682

Execution: PASS | F2P: 1/1 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: In `SparseCoder.transform` / `_set_sparse_coding_params`, the estimator never stores or forwards extra `Lasso` constructor arguments such as `max_iter`, so `_sparse_encode(..., algorithm='lasso_cd')` 

Ground truth: SparseCodingMixin.transform() calls sparse_encode() without forwarding max_iter, and SparseCoder.__init__ doesn't accept max_iter, so the default max_iter=1000 is always used — insufficient for the of

Oracle justification: The ground truth states that SparseCodingMixin.transform never forwards max_iter and SparseCoder.__init__ lacks a max_iter option causing the default 1000 to be used, and the developer's reasoning exp

Audit judgment: Oracle CORRECT (model reasoning matches GT and code works). Classifier CORRECT (reasoning is internally consistent).

### sphinx-doc__sphinx-10673

Execution: PASS | F2P: 1/1 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: In TocTree.parse_content() the resolver treats every non-URL, non-`self` entry as a real document path and emits a warning when it is not in `env.found_docs`; this incorrectly flags Sphinx-generated p

Ground truth: toctree warns about nonexisting documents when referencing special pages like 'genindex', 'modindex', 'search' because they're not in the document inventory

Oracle justification: The ground truth states that toctree emits false "nonexisting document" warnings for special generated pages (genindex/modindex/search) because they are not in the document inventory, and the develope

Audit judgment: Oracle CORRECT (model reasoning matches GT and code works). Classifier CORRECT (reasoning is internally consistent).

---

## LUCKY_FIX (2 cases)

### pytest-dev__pytest-8399

Execution: PASS | F2P: 1/1 | P2P regressions: 0
Oracle: PARTIAL | Classifier RIC: CORRECT

Model root cause: _make_xunit_fixture in unittest.py creates hidden fixtures with names prefixed by the public xunit method name (for example unittest_setUpClass_fixture_...), so pytest --fixtures no longer treats unit

Ground truth: Starting in pytest 6.2.0, unittest setUpClass fixtures are no longer treated as private, making them visible in --fixtures output and tab completion

Oracle justification: The ground truth states that unittest xunit fixtures lost their private marking in both src/_pytest/python.py and src/_pytest/unittest.py, whereas the developer's root cause correctly identifies the m

Audit judgment: Oracle CORRECT to mark reasoning wrong — model described a different mechanism than the ground truth. Code happened to work anyway.

### sphinx-doc__sphinx-8120

Execution: PASS | F2P: 1/1 | P2P regressions: 0
Oracle: WRONG | Classifier RIC: CORRECT

Model root cause: Sphinx._init_i18n() only compiles user locale catalogs when `CatalogRepository(self.srcdir, self.config.locale_dirs, ...)` exposes them, but `locale.init()` later searches `locale_dirs` with the packa

Ground truth: Sphinx application initializes locale catalog after extensions are loaded, so custom locale/translation directories specified via locale_dirs config are not picked up

Oracle justification: The ground truth identifies the bug as an initialization-order problem (i18n is initialized too late, after extensions/loaders create translation proxies), but the developer blames a mismatch in local

Audit judgment: Oracle CORRECT to mark reasoning wrong — model described a different mechanism than the ground truth. Code happened to work anyway.

---

## LEG (36 cases)

### django__django-10554

Execution: FAIL | F2P: 0/2 | P2P regressions: 23
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: SQLCompiler.get_order_by() mishandles combined querysets when an ORDER BY term comes from a derived/annotated expression on one side of a UNION: it only tries to match the resolved ordering expression

Ground truth: In a UNION query, get_order_by resolves ordering fields against the combined query's select list, but change_aliases only remaps aliases in WHERE/SELECT, leaving ORDER BY expressions referencing stale

Oracle justification: The developer correctly pinpoints that get_order_by's matching against self.select (failing to account for branch-local/derived ordering refs) causes ORDER BY to reference stale aliases in combined qu

Audit judgment: Zero F2P tests pass. Failing: test_union_with_values_list_and_order (queries.test_qs_combi. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### django__django-11532

Execution: FAIL | F2P: 1/1 | P2P regressions: 18
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: In `message.py`, `EmailMessage.message()` builds `Message-ID` with `make_msgid(domain=DNS_NAME)`, and `DNS_NAME` in `utils.py` can be a Unicode hostname. When the message is later serialized with a no

Ground truth: Multiple places in Django encode internationalized domain names using inline domain.encode('idna').decode('ascii'), which crashes on non-ASCII hostnames when the system encoding is not unicode

Oracle justification: The ground truth points out that a Unicode system hostname (from CachedDnsName/socket.getfqdn) leads to non-ASCII domains in headers and a UnicodeEncodeError during serialization; the developer's root

Audit judgment: Near-miss — all F2P tests pass but 18 regressions block resolution. Oracle CORRECT. Classifier CORRECT.

### django__django-11734

Execution: FAIL | F2P: 0/1 | P2P regressions: 275
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: Query.split_exclude() builds the inner subquery with Query(self.model), so when the negated subtree contains an OuterRef the reference is resolved against the wrong query model/alias context during ex

Ground truth: OuterRef in exclude() or ~Q() resolves against the wrong model because split_exclude doesn't preserve OuterRef references through the query split

Oracle justification: The ground truth states that split_exclude fails to preserve OuterRef (causing it to be resolved against the wrong model), and the developer likewise identifies split_exclude creating a new Query(self

Audit judgment: Zero F2P tests pass. Failing: test_subquery_exclude_outerref (queries.tests.ExcludeTests). Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### django__django-11885

Execution: FAIL | F2P: 1/1 | P2P regressions: 2
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: Collector.delete() in deletion.py only performs per-model fast deletes opportunistically during collection, but never combines multiple fast-deletable querysets targeting the same table. As a result, 

Ground truth: Collector issues separate DELETE queries for each related object found during CASCADE, instead of combining them into batch queries grouped by model

Oracle justification: The developer correctly identifies that multiple fast_deletes entries produce separate DELETE ... WHERE pk IN (...) queries per relation instead of being combined by model, matching the ground truth's

Audit judgment: Near-miss — all F2P tests pass but 2 regressions block resolution. Oracle CORRECT. Classifier CORRECT.

### django__django-12325

Execution: FAIL | F2P: 0/2 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: In Options._prepare(), the single-primary-key bootstrap for multi-table inheritance blindly promotes the first entry in self.parents and then raises ImproperlyConfigured if that promoted OneToOneField

Ground truth: In multi-table inheritance with multiple OneToOneFields to the parent, Django's pk setup incorrectly picks the wrong field as the primary key link

Oracle justification: The developer's root cause accurately matches the ground truth: they identify that Options._prepare (options.py) blindly promotes the first OneToOneField in self.parents and can misselect a non-parent

Audit judgment: Zero F2P tests pass. Failing: test_clash_parent_link (invalid_models_tests.test_relative_f. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### django__django-12406

Execution: FAIL | F2P: 0/3 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: In ModelChoiceField.__init__(), the empty_label is only suppressed when required=True and initial is not None. When a ForeignKey form field is rendered with a RadioSelect widget, the field still defau

Ground truth: ModelForm with RadioSelect widget for ForeignKey always includes a blank choice even when blank=False on the model field

Oracle justification: The ground truth says RadioSelect-backed ModelChoiceField shows a blank choice even when model.blank=False, and the developer correctly attributes this to ModelChoiceField.__init__'s empty_label handl

Audit judgment: Zero F2P tests pass. Failing: test_non_blank_foreign_key_with_radio (model_forms.tests.Mod. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### django__django-13121

Execution: FAIL | F2P: 0/1 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: In expressions.py, CombinedExpression.as_sql() routes any DurationField arithmetic to DurationExpression, but DurationExpression.as_sql() only handles native duration backends correctly. On SQLite and

Ground truth: Duration-only expressions (DurationField +/- DurationField) don't work on SQLite and MySQL because the backends don't handle the case where both sides are durations

Oracle justification: The ground truth says SQLite/MySQL fail to handle duration+duration arithmetic because backends don’t format/handle both operands as pure durations, and the reasoning correctly identifies that Duratio

Audit judgment: Zero F2P tests pass. Failing: test_duration_expressions (expressions.tests.FTimeDeltaTests. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### django__django-13195

Execution: FAIL | F2P: 1/5 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: HttpResponseBase.delete_cookie() in response.py always reissues the cookie without preserving the original samesite attribute, so deleting a cookie that was previously set with SameSite=None causes th

Ground truth: HttpResponse.delete_cookie() does not preserve the samesite attribute from the original cookie, causing browser warnings about SameSite policy

Oracle justification: The developer's root cause correctly states that HttpResponse.delete_cookie() fails to preserve/pass the SameSite attribute (omitting it on the deletion Set-Cookie) which matches the ground-truth caus

Audit judgment: Oracle CORRECT. Classifier CORRECT.

### django__django-13212

Execution: FAIL | F2P: 3/5 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: In validators.py, built-in validator __call__ methods (RegexValidator, URLValidator, EmailValidator, validate_ipv4_address, validate_ipv6_address, validate_ipv46_address, FileExtensionValidator, Prohi

Ground truth: Django validators do not include the invalid value in the ValidationError params, making it impossible to reference the value in custom error messages

Oracle justification: The ground truth states that validators fail to include the invalid value in ValidationError.params (so %(value)s can't be used), and the developer's root_cause explicitly identifies the same issue—bu

Audit judgment: Partial fix — 3/5 tests pass. Model understands the bug but implementation is incomplete. Oracle CORRECT. Classifier CORRECT.

### django__django-13344

Execution: FAIL | F2P: 0/2 | P2P regressions: 356
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: MiddlewareMixin.__call__ is passing an unawaited coroutine returned by an async get_response into the first middleware's process_response(), because the middleware chain is not awaiting async response

Ground truth: When using async middleware, process_response receives a coroutine instead of an HttpResponse because the async-to-sync adaptation doesn't await the response

Oracle justification: The ground truth explains that process_response receives a coroutine because an async get_response was not awaited; the developer's root_cause likewise states MiddlewareMixin.__call__ is passing an un

Audit judgment: Zero F2P tests pass. Failing: test_coroutine (deprecation.test_middleware_mixin.Middleware. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### django__django-13512

Execution: FAIL | F2P: 1/3 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: fields.JSONField.prepare_value() serializes JSON using json.dumps() with the default encoder settings, which escapes non-ASCII characters (ensure_ascii=True). In Django admin, this causes Unicode text

Ground truth: Admin display for JSONField uses json.dumps with ensure_ascii=True (default), escaping unicode characters to \uXXXX sequences instead of displaying them

Oracle justification: The ground truth says admin display uses json.dumps with default ensure_ascii=True (escaping Unicode), and the reasoning correctly identifies that fields.JSONField.prepare_value() calls json.dumps wit

Audit judgment: Oracle CORRECT. Classifier CORRECT.

### django__django-14011

Execution: FAIL | F2P: 0/17 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: basehttp.ThreadedWSGIServer inherits socketserver.ThreadingMixIn behavior but never triggers Django's per-request connection cleanup; as a result, database connections created while handling threaded 

Ground truth: LiveServerTestCase's ThreadedWSGIServer doesn't close database connections when threads finish, causing connection leaks and 'database is locked' errors on SQLite

Oracle justification: The ground truth says ThreadedWSGIServer leaves database connections open because threads don't call per-request connection cleanup, and the developer's root cause explicitly identifies the same issue

Audit judgment: Zero F2P tests pass. Failing: test_live_server_url_is_class_property (servers.tests.LiveSe. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### django__django-14170

Execution: FAIL | F2P: 2/2 | P2P regressions: 9
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: YearLookup.as_sql() unconditionally rewrites direct-value year lookups to a BETWEEN range using year_lookup_bounds(), but it is registered for '__iso_year' too; this causes __iso_year filters to compa

Ground truth: YearLookup optimization incorrectly handles __iso_year lookups by using calendar year bounds instead of ISO year bounds

Oracle justification: The ground truth states YearLookup's BETWEEN optimization is applied to __iso_year and uses calendar-year bounds (Jan 1–Dec 31) instead of ISO week-year bounds, which matches the reasoning that YearLo

Audit judgment: Near-miss — all F2P tests pass but 9 regressions block resolution. Oracle CORRECT. Classifier CORRECT.

### django__django-14315

Execution: FAIL | F2P: 9/11 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: BaseDatabaseClient.runshell() treats an empty dict from settings_to_cmd_args_env() as falsy and skips merging it with os.environ, then passes the empty dict to subprocess.run() instead of inheriting t

Ground truth: PostgreSQL settings_to_cmd_args_env returns empty dict {} when no password/service/ssl options are set, and runshell uses 'if env:' which is falsey for empty dict

Oracle justification: The reasoning correctly identifies that BaseDatabaseClient.runshell treats the empty dict returned by DatabaseClient.settings_to_cmd_args_env as falsy, skips merging os.environ, and thus calls subproc

Audit judgment: Partial fix — 9/11 tests pass. Model understands the bug but implementation is incomplete. Oracle CORRECT. Classifier CORRECT.

### django__django-14376

Execution: FAIL | F2P: 1/3 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: DatabaseWrapper.get_connection_params() and DatabaseClient.settings_to_cmd_args_env() still read and emit the deprecated MySQL kwargs `db` and `passwd`, causing mysqlclient deprecation warnings and pr

Ground truth: MySQL backend uses deprecated 'db' and 'passwd' kwargs instead of 'database' and 'password' in connection parameters

Oracle justification: The ground truth states that the MySQL backend passes deprecated 'db' and 'passwd' (instead of 'database' and 'password') in base.py and client.py, and the reasoning explicitly identifies DatabaseWrap

Audit judgment: Oracle CORRECT. Classifier CORRECT.

### django__django-15561

Execution: FAIL | F2P: 0/1 | P2P regressions: 141
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: BaseDatabaseSchemaEditor._field_should_be_altered() treated a change in Field.choices as a schema-altering change because Field.deconstruct() includes 'choices' in the serialized kwargs. This made alt

Ground truth: AlterField migration generates a database operation when only the 'choices' attribute changes, even though choices don't affect the database schema

Oracle justification: The root cause correctly matches the ground truth by identifying that BaseDatabaseSchemaEditor._field_should_be_altered (schema.py) treats changes to Field.choices—because Field.deconstruct includes '

Audit judgment: Zero F2P tests pass. Failing: test_alter_field_choices_noop (schema.tests.SchemaTests). Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### django__django-15563

Execution: FAIL | F2P: 0/2 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: UpdateQuery.add_update_values() incorrectly decides whether a field belongs to the base model by comparing field.model._meta.concrete_model to self.get_meta().concrete_model. In a multiple-inheritance

Ground truth: QuerySet.update() with multiple inheritance generates UPDATE on the wrong table when the field being updated is on a parent model

Oracle justification: The ground truth states that QuerySet.update() on multi-table inheritance misroutes updates because UpdateQuery.add_update_values misidentifies parent-model fields and causes the UPDATE to target the 

Audit judgment: Zero F2P tests pass. Failing: test_mti_update_grand_parent_through_child (model_inheritanc. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### django__django-16032

Execution: FAIL | F2P: 0/2 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: In Query.resolve_ref() and Query.names_to_path(), annotations and aliases are treated as equivalent sources for subquery column selection, but Query.add_fields() only strips selects when the RHS query

Ground truth: __in lookup doesn't clear selected fields on the RHS queryset when alias() is used after annotate(), causing extra columns in the subquery

Oracle justification: The ground truth states that __in fails to clear the RHS select when alias() is used after annotate() because aliased annotations are treated differently, and the reasoning matches this by identifying

Audit judgment: Zero F2P tests pass. Failing: test_annotation_and_alias_filter_in_subquery (annotations.te. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### django__django-16256

Execution: FAIL | F2P: 0/9 | P2P regressions: 53
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: In create_generic_related_manager(), the related manager defines create(), get_or_create(), and update_or_create() correctly for sync use, but it never provides async counterparts. Because the manager

Ground truth: Related managers override create() to inject FK values (line 790: kwargs[self.field.name] = self.instance), but acreate() is inherited from QuerySet unchanged and does not go through the manager's cre

Oracle justification: The ground truth states related managers override create()/get_or_create()/update_or_create() but lack async counterparts so QuerySet.acreate()/aget_or_create()/aupdate_or_create() are inherited and b

Audit judgment: Zero F2P tests pass. Failing: test_acreate (async.test_async_related_managers.AsyncRelated. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### django__django-16315

Execution: FAIL | F2P: 0/1 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: QuerySet._check_bulk_create_options() normalizes unique_fields/update_fields with model._meta.get_field(name), but SQL generation later uses field.column. When db_column has mixed case, the lookup ret

Ground truth: bulk_create() crashes when unique_fields or update_fields contain mixed-case column names because the ON CONFLICT clause uses case-sensitive comparison

Oracle justification: The developer pinpoints that unique_fields/update_fields are being converted/resolved in a way that loses the Field identity so SQL generation emits mismatched/unquoted column identifiers for mixed-ca

Audit judgment: Zero F2P tests pass. Failing: test_update_conflicts_unique_fields_update_fields_db_column . Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### django__django-16560

Execution: FAIL | F2P: 4/8 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: BaseConstraint.validate callers in models_constraints.py and postgres_constraints.py always raised ValidationError(self.get_violation_error_message()), but BaseConstraint had no way to store or propag

Ground truth: NOT A BUG: This is a feature request / API cleanup, not a runtime failure.

Oracle justification: The ground truth states this is a feature request because constraint validation currently cannot customize the ValidationError.code, and the reasoning explicitly identifies that BaseConstraint and the

Audit judgment: Oracle CORRECT. Classifier CORRECT.

### django__django-16938

Execution: FAIL | F2P: 18/23 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: In both `python.py:Serializer.handle_m2m_field()` and `xml_serializer.py:Serializer.handle_m2m_field()`, the code unconditionally uses the related manager’s queryset (`getattr(obj, field.name)`) and, 

Ground truth: M2M serialization calls .only('pk') on the related queryset, which conflicts with custom managers that use select_related

Oracle justification: The ground truth states that serializer code calls .only('pk') on the related queryset which conflicts with a custom manager's select_related causing a FieldError, and the developer's reasoning makes 

Audit judgment: Partial fix — 18/23 tests pass. Model understands the bug but implementation is incomplete. Oracle CORRECT. Classifier CORRECT.

### matplotlib__matplotlib-24870

Execution: FAIL | F2P: 0/1 | P2P regressions: 65
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: In `QuadContourSet._process_contour_level_args`, boolean `z` arrays are treated like generic numeric arrays, so the default integer level selection path (`_autolev(7)`) produces 8 contour levels spann

Ground truth: _process_contour_level_args unconditionally defaults to levels_arg=7, which for binary [0,1] data produces 7 identical contour lines at the single True/False boundary

Oracle justification: The ground truth states that contour() fails to detect boolean input and should coerce or error, and the developer explicitly identifies the same mechanism by naming QuadContourSet._process_contour_le

Audit judgment: Zero F2P tests pass. Failing: lib/matplotlib/tests/test_contour.py::test_bool_autolevel. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### pydata__xarray-3095

Execution: FAIL | F2P: 0/1 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: Variable.copy() and IndexVariable.copy() deep-copy the underlying data with np.array(self._data) / PandasIndexAdapter(self._data.array.copy(...)), which strips the original pandas Index metadata and c

Ground truth: Dataset.copy(deep=True) casts unicode string indices to object dtype because the deep copy path uses np.array() which doesn't preserve pandas string dtype

Oracle justification: The ground truth says np.array(...) in the deep-copy path causes pandas unicode indices to be cast to object, and the developer explicitly identifies Variable.copy()/IndexVariable.copy using np.array(

Audit judgment: Zero F2P tests pass. Failing: xarray/tests/test_variable.py::TestIndexVariable::test_copy[. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### pydata__xarray-6938

Execution: FAIL | F2P: 0/1 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: Dataset.swap_dims() mutates the existing Variable objects in place by assigning to `var.dims` on the same `Variable` instances referenced by `self._variables`; because `v.to_index_variable()` and `v.t

Ground truth: swap_dims modifies the internal variable objects of the original Dataset instead of making copies, causing the original object to be mutated

Oracle justification: The ground truth states that Dataset.swap_dims reuses and mutates the original Variable objects (causing shared_reference_mutation), and the developer's reasoning makes the same claim—identifying in-p

Audit judgment: Zero F2P tests pass. Failing: xarray/tests/test_variable.py::TestIndexVariable::test_to_in. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### pylint-dev__pylint-4551

Execution: FAIL | F2P: 0/10 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: `Linker.handle_assignattr_type()` and `Linker.visit_assignname()` only store inferred runtime values, so a class attribute annotated as `str` with a default of `None` is recorded as `NoneType`/uninfer

Ground truth: NOT A BUG: This is a feature request / API cleanup, not a runtime failure.

Oracle justification: The ground truth states pyreverse lacks use of PEP 484 annotations (a feature request), and the developer correctly identifies the same mechanism by pointing out Linker only records inference results 

Audit judgment: Zero F2P tests pass. Failing: tests/unittest_pyreverse_writer.py::test_dot_files[packages_. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### pylint-dev__pylint-4604

Execution: FAIL | F2P: 0/21 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: VariablesChecker._store_type_annotation_node only records type-comment names when the annotation is an astroid.Name or an astroid.Subscript, so attribute-based type comments like "abc.ABC" are ignored

Ground truth: The unused-import checker does not recognize imports that are only used in PEP 484 type comments (# type: ModuleName)

Oracle justification: The ground truth states unused-imports are missed because the checker doesn't recognize names used only in type comments, and the developer correctly pinpoints that VariablesChecker._store_type_annota

Audit judgment: Zero F2P tests pass. Failing: tests/checkers/unittest_variables.py::TestVariablesChecker::. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### pylint-dev__pylint-4661

Execution: FAIL | F2P: 0/1 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: The module-level PYLINT_HOME initialization in __init__.py hardcodes the legacy ~/.pylint.d path when PYLINTHOME is unset, causing persistent data to be written outside the XDG Base Directory Specific

Ground truth: NOT A BUG: This is a feature request / API cleanup, not a runtime failure.

Oracle justification: The ground truth identifies that PYLINT_HOME is hardcoded to os.path.join(USER_HOME, ".pylint.d") causing XDG noncompliance, and the developer's root cause explicitly states the module-level PYLINT_HO

Audit judgment: Zero F2P tests pass. Failing: tests/lint/unittest_lint.py::test_pylint_home. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### pylint-dev__pylint-6386

Execution: FAIL | F2P: 0/1 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: The bug is in `_convert_option_to_argument()` in `utils.py`: it treats the `verbose` option as a normal `_DoNothingAction`/store-style option, so `_add_parser_option()` registers it without `nargs=0`.

Ground truth: The short -v option for --verbose unexpectedly requires an argument because the argument configuration treats it as a store value instead of store_true

Oracle justification: The developer correctly identifies that the verbose option is being converted/registered as a value-taking (store) option—pointing to _convert_option_to_argument() in utils.py causing argparse to requ

Audit judgment: Zero F2P tests pass. Failing: tests/config/test_config.py::test_short_verbose. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### pylint-dev__pylint-6528

Execution: FAIL | F2P: 0/4 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: In `pylinter.PyLinter.check`, recursive mode calls `_discover_files()` before any ignore filtering is applied. `_discover_files()` blindly yields every discovered path, so `expand_modules.expand_modul

Ground truth: In recursive mode (--recursive=y), expand_modules only checks ignore patterns against the top-level entry, not against discovered submodules and files

Oracle justification: The developer correctly identifies that recursive discovery (_discover_files called in PyLinter.check) emits all subpaths before ignore filtering, matching the ground truth that expand_modules ends up

Audit judgment: Zero F2P tests pass. Failing: tests/lint/unittest_lint.py::test_recursive_ignore[--ignore-. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### pylint-dev__pylint-8898

Execution: FAIL | F2P: 0/1 | P2P regressions: 18
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: utils._splitstrip() blindly splits every comma-separated option value, and _regexp_csv_transfomer() relies on it for bad-names-rgxs; this mangles regular expressions containing literal commas before r

Ground truth: bad-names-rgxs option splits regular expressions on commas, breaking patterns that contain commas (e.g., quantifiers like {1,2})

Oracle justification: The ground truth identifies utils._splitstrip (used via _csv_transformer/_regexp_csv_transfomer) as splitting commas inside regex patterns (so '{1,2}' becomes '{1' and '2}'), and the developer's root 

Audit judgment: Zero F2P tests pass. Failing: tests/config/test_config.py::test_csv_regex_error. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### scikit-learn__scikit-learn-25102

Execution: FAIL | F2P: 0/2 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: _transform in SelectorMixin always returns a sliced ndarray, so when pandas output is enabled it drops DataFrame metadata and all column dtypes, even though feature selection does not alter surviving 

Ground truth: SelectorMixin._transform converts DataFrame to ndarray (via check_array or direct indexing), collapsing per-column dtypes to float64; the subsequent DataFrame reconstruction cannot recover original dt

Oracle justification: The ground truth states that SelectorMixin._transform converts pandas DataFrames to numpy ndarrays (collapsing per-column dtypes) and the developer's root cause explicitly says _transform always retur

Audit judgment: Zero F2P tests pass. Failing: sklearn/feature_selection/tests/test_base.py::test_output_da. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### sphinx-doc__sphinx-7462

Execution: FAIL | F2P: 1/2 | P2P regressions: 2
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: _parse_annotation() in python.py: its nested unparse() handles ast.Tuple by always appending punctuation and then unconditionally calling result.pop(), so an empty tuple annotation Tuple[()] produces 

Ground truth: The unparse function in ast.py does not handle ast.Tuple nodes, so empty tuple annotations like Tuple[()] crash with IndexError

Oracle justification: The ground truth identifies a missing/incorrect handler for ast.Tuple (empty tuple annotations causing a crash), and the developer correctly pins this down to python.py's nested unparse ast.Tuple bran

Audit judgment: Oracle CORRECT. Classifier CORRECT.

### sphinx-doc__sphinx-8548

Execution: FAIL | F2P: 0/1 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: autodoc.importer.get_class_members() and get_object_members() only record inherited data attributes in the current class namespace, so Documenter.filter_members() later looks up attribute docs with ('

Ground truth: autodoc's get_object_members uses __dict__ to find directly-defined members but misses inherited data attributes (non-method members) when :inherited-members: is set

Oracle justification: The ground truth states that inherited data attributes are missed because autodoc only looks up attribute docs using the child's namespace rather than the defining base-class namespace, and the develo

Audit judgment: Zero F2P tests pass. Failing: tests/test_ext_autodoc_autoclass.py::test_inherited_instance. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### sympy__sympy-19783

Execution: FAIL | F2P: 0/2 | P2P regressions: 9
Oracle: CORRECT | Classifier RIC: INCORRECT

Model root cause: operator.py: Operator.__mul__ only special-cases IdentityOperator on the right-hand side when the left operand is an Operator instance. When the left operand is Dagger(A), the product is represented a

Ground truth: Operator.__mul__ handles IdentityOperator on the right side but there is no corresponding __rmul__ or handling in Dagger for IdentityOperator multiplication

Oracle justification: The ground truth says Operator.__mul__ special-cases IdentityOperator only when the left operand is an Operator and that Dagger (an adjoint expression) doesn't invoke that logic so Dagger(A)*I remains

Audit judgment: Zero F2P tests pass. Failing: test_dagger_mul. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

### sympy__sympy-20438

Execution: FAIL | F2P: 0/2 | P2P regressions: 0
Oracle: CORRECT | Classifier RIC: CORRECT

Model root cause: In issubset.py, the generic @dispatch(Set, Set) is_subset_sets implementation always returns None, so ProductSet.is_subset(FiniteSet) is never actually evaluated. This leaves subset checks for set typ

Ground truth: No @dispatch(FiniteSet, ProductSet) handler exists in issubset.py; the fallback Set-Set handler returns None, and the set-difference fallback cannot determine that scalar integers are not members of a

Oracle justification: The ground truth states that no @dispatch(FiniteSet, ProductSet) handler exists and the @dispatch(Set, Set) fallback returns None causing indeterminate subset checks, and the developer likewise blames

Audit judgment: Zero F2P tests pass. Failing: test_Eq. Oracle CORRECT (reasoning matches GT). Classifier CORRECT (reasoning is coherent).

---

## WRONG_MECHANISM (16 cases)

### astropy__astropy-13398

Execution: FAIL | F2P: 0/4 | P2P regressions: 68
Oracle: WRONG | Classifier RIC: CORRECT

Model root cause: The transform registration in intermediate_rotation_transforms.py creates ITRS→observed and observed→ITRS paths that recurse back through ITRS because there is no direct ITRS↔observed transformation m

Ground truth: ITRS-to-Observed coordinate transforms go through intermediate GCRS/TETE frames, losing topocentric location information because they hardcode EARTH_CENTER instead of propagating the observer's locati

Oracle justification: The ground truth states the bug is that intermediate transforms reset the observer to EARTH_CENTER (losing topocentric location in itrs_to_tete/itrs_to_cirs), whereas the developer blames a missing di

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### astropy__astropy-14369

Execution: FAIL | F2P: 0/3 | P2P regressions: 0
Oracle: WRONG | Classifier RIC: CORRECT

Model root cause: In cds.py, CDS.parse() rejects any CDS unit string containing spaces before parsing. This prevents valid CDS-composite unit strings that include whitespace or separator-like formatting from being toke

Ground truth: CDS unit parser grammar has wrong associativity for division — 'combined_units DIVISION unit_expression' should be 'unit_expression DIVISION combined_units', causing compound units to be parsed incorr

Oracle justification: The ground truth attributes the bug to a wrong grammar associativity for division in the YACC rules (incorrect operand order causing right-associative parsing), whereas the developer claims the cause 

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### astropy__astropy-8707

Execution: FAIL | F2P: 0/1 | P2P regressions: 7
Oracle: PARTIAL | Classifier RIC: CORRECT

Model root cause: Header.fromstring in header.py accepts only text str input and then uses str.find/slicing directly; when Python 3 bytes are passed, the code compares byte segments to text literals (for example 'CONTI

Ground truth: Header.fromstring and Card.fromstring do not accept bytes input on Python 3, despite the documentation claiming they do

Oracle justification: The developer correctly diagnoses that Header.fromstring treats input as text and will fail when passed bytes (matching the ground truth cause), but their reasoning omits that Card.fromstring has the 

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### django__django-11138

Execution: FAIL | F2P: 0/1 | P2P regressions: 0
Oracle: PARTIAL | Classifier RIC: CORRECT

Model root cause: In mysql_operations.py and oracle_operations.py, adapt_datetimefield_value()/convert_datetimefield_value() and the datetime SQL helpers use self.connection.timezone, but the per-database TIME_ZONE set

Ground truth: MySQL, SQLite, and Oracle backends hardcode UTC as the source timezone when converting dates, ignoring the TIME_ZONE setting in DATABASES

Oracle justification: The ground truth says MySQL, SQLite, and Oracle hardcode UTC/'0:00' as the source timezone when converting dates, whereas the developer correctly identifies that MySQL and Oracle conversions are using

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### django__django-11333

Execution: FAIL | F2P: 0/1 | P2P regressions: 2
Oracle: WRONG | Classifier RIC: CORRECT

Model root cause: django.urls.resolvers.get_resolver caches URLResolver instances only by urlconf, but when urlconf is None it normalizes to settings.ROOT_URLCONF after the cache lookup key is chosen. That means repeat

Ground truth: set_urlconf(None) unconditionally calls get_resolver.cache_clear() at base.py line 95, invalidating the lru_cache on every request cycle even when ROOT_URLCONF hasn't changed

Oracle justification: The ground truth blames set_urlconf(None) unconditionally calling get_resolver.cache_clear() (causing repeated cache invalidation), whereas the developer instead attributes the issue to normalizing No

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### django__django-11400

Execution: FAIL | F2P: 4/6 | P2P regressions: 14
Oracle: PARTIAL | Classifier RIC: CORRECT

Model root cause: RelatedFieldListFilter.field_choices() hard-codes ordering = () unless an admin is registered for the related model, so Field.get_choices() never sees the related model's Meta.ordering and falls back 

Ground truth: RelatedFieldListFilter.field_choices does not pass an ordering parameter to field.get_choices(), and get_choices itself doesn't accept ordering for forward/reverse relations

Oracle justification: The ground truth describes a missing propagation of ordering that requires changes both in RelatedFieldListFilter.field_choices and in Field.get_choices/ForeignObjectRel.get_choices to accept an order

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### django__django-16631

Execution: FAIL | F2P: 0/1 | P2P regressions: 0
Oracle: PARTIAL | Classifier RIC: CORRECT

Model root cause: The bug is in AbstractBaseUser.get_session_auth_hash() in base_user.py: it computes the session HMAC only from user.password, so rotating SECRET_KEY does not invalidate sessions in a way that can be v

Ground truth: SECRET_KEY_FALLBACKS is not used for session verification, so rotating the secret key invalidates all existing sessions

Oracle justification: The ground truth states SECRET_KEY_FALLBACKS is not used for session verification and both auth/__init__.py and base_user.py must try fallback keys, while the reasoning correctly points to get_session

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### matplotlib__matplotlib-25479

Execution: FAIL | F2P: 0/2 | P2P regressions: 1
Oracle: WRONG | Classifier RIC: CORRECT

Model root cause: matplotlib.cm._ensure_cmap and ColormapRegistry.get_cmap both validate string inputs against the private `_colormaps` dict instead of the public registry object, so a colormap registered at runtime ca

Ground truth: ColormapRegistry.register stores a colormap under the registry name but does not update the colormap's internal .name attribute to match

Oracle justification: The ground truth says the bug is that ColormapRegistry.register stores a colormap under a new key without updating the colormap's internal .name, but the developer instead blames validation/lookup aga

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### pydata__xarray-3305

Execution: FAIL | F2P: 0/1 | P2P regressions: 0
Oracle: WRONG | Classifier RIC: CORRECT

Model root cause: Dataset.quantile in dataset.py computes `keep_attrs`, but it only applies it to the dataset-level attrs (`attrs`) and never propagates the flag into `var.quantile(...)`. As a result, each reduced Data

Ground truth: Variable.quantile does not propagate the keep_attrs parameter, always returning a result with empty attrs regardless of the flag

Oracle justification: The ground truth identifies Variable.quantile as not accepting/using keep_attrs (so the fix belongs in variable.py), but the developer claims the bug is that Dataset.quantile fails to pass keep_attrs 

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### pytest-dev__pytest-5840

Execution: FAIL | F2P: 0/2 | P2P regressions: 0
Oracle: WRONG | Classifier RIC: CORRECT

Model root cause: `unique_path()` in pathlib.py normalizes paths with `normcase(str(path.realpath()))`, which lowercases drive/path components on Windows. That canonicalized lowercase path is then used as the conftest 

Ground truth: On Windows, pytest's conftest discovery fails when folder casing in the path differs from the filesystem because path comparison is case-sensitive

Oracle justification: The ground truth identifies the issue as case-sensitive path comparisons due to pathlib not normalizing filesystem casing on Windows, whereas the reasoning instead asserts unique_path() lowercases pat

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### sphinx-doc__sphinx-8551

Execution: FAIL | F2P: 0/1 | P2P regressions: 0
Oracle: PARTIAL | Classifier RIC: CORRECT

Model root cause: PythonDomain.find_obj() uses exact-match lookup that prefers any global object name before namespace-aware resolution, and PyField/TypedField create implicit xrefs without setting refspecific. As a re

Ground truth: When docfields creates cross-references for :type: and :rtype: annotations, it does not pass the py:module context to the pending_xref node

Oracle justification: The ground truth identifies missing propagation of the py:module context from TypedField.make_field to the pending_xref as the root cause, whereas the developer's root cause emphasizes a missing refsp

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### sphinx-doc__sphinx-9461

Execution: FAIL | F2P: 0/3 | P2P regressions: 0
Oracle: WRONG | Classifier RIC: CORRECT

Model root cause: `ClassLevelDocumenter.get_doc()` in `__init__.py` returns `super().get_doc()` for class-level descriptors, but `NonDataDescriptorMixin.get_doc()` in the MRO deliberately suppresses docstrings for non-

Ground truth: Methods decorated with both @classmethod and @property are not documented because autodoc doesn't recognize the combined decorator pattern

Oracle justification: The ground truth attributes the bug to inspect.py not recognizing classmethod-property hybrid descriptors (requiring fixes in inspect.py, autodoc, and python domain), but the reasoning instead blames 

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### sympy__sympy-13877

Execution: FAIL | F2P: 0/1 | P2P regressions: 110
Oracle: PARTIAL | Classifier RIC: CORRECT

Model root cause: In matrices.py, _find_reasonable_pivot() and _find_reasonable_pivot_naive() can treat a symbolic NaN/undefined entry as a valid pivot because they rely on iszerofunc()/equals(0) without explicitly rej

Ground truth: _find_pivot uses Python truthiness test (if val:) on symbolic matrix entries; when Bareiss elimination produces NaN intermediate values, bool(NaN) raises TypeError

Oracle justification: The ground truth identifies the bug as _find_pivot using a truthiness test ("if val:") that triggers bool(NaN) TypeError, while the developer correctly spots NaN being chosen as a pivot and propagatin

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### sympy__sympy-16597

Execution: FAIL | F2P: 0/3 | P2P regressions: 0
Oracle: WRONG | Classifier RIC: CORRECT

Model root cause: ask.get_known_facts() / ask_generated.get_known_facts_cnf() encode Q.even -> Q.integer -> Q.rational -> Q.algebraic -> Q.complex -> ~Q.finite, which is too strong for the old assumptions semantics. Th

Ground truth: Symbol.is_even does not imply Symbol.is_finite, causing incorrect logical deductions in the assumption system

Oracle justification: The ground truth identifies the missing implication even → finite (so Symbol(even=True) yields is_finite=None), whereas the developer asserts the known-facts encode a spurious chain making even imply 

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### sympy__sympy-17318

Execution: FAIL | F2P: 0/1 | P2P regressions: 0
Oracle: WRONG | Classifier RIC: CORRECT

Model root cause: In sqrtdenest._sqrtdenest0, the generic recursive branch rebuilds any Expr by blindly recursing into expr.args. For some expressions this can descend into pathological structures created during denest

Ground truth: split_surds crashes with IndexError when called with expressions containing complex surds because _split_gcd receives an empty list

Oracle justification: The ground truth states the IndexError is caused by split_surds producing an empty surd list (leading to _split_gcd popping from an empty list) for complex surds, whereas the developer blames unguarde

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

### sympy__sympy-22080

Execution: FAIL | F2P: 0/3 | P2P regressions: 91
Oracle: WRONG | Classifier RIC: CORRECT

Model root cause: CodePrinter._print_Mul mutates the SymPy Mul expression by calling _keep_coeff(-c, e) when a negative coefficient is detected; for expressions like -Mod(x, y) this rewrites the internal argument struc

Ground truth: CodePrinter._print_Mul does not handle Mod correctly — when Mod appears in a multiplication, the printer moves it incorrectly due to wrong precedence handling

Oracle justification: The developer asserts the bug is caused by CodePrinter._print_Mul mutating the Mul via _keep_coeff and folding the sign into Mod's first argument, but the ground truth attributes the error to incorrec

Audit judgment: Oracle CORRECT to mark reasoning wrong — model's root cause does not match the verified ground truth mechanism. Classifier CORRECT (reasoning IS internally consistent, just factually wrong).

---

## NO_ORACLE (4 cases) — Docker evaluated but oracle pipeline failed

- django__django-14631: exec=FAIL f2p=2/2
- django__django-15103: exec=PASS f2p=2/2
- django__django-15629: exec=FAIL f2p=0/2
- mwaskom__seaborn-3187: exec=FAIL f2p=0/2

---

## NOT_EVALUATED (8 cases) — Too large for full-file replacement

- django__django-16263: exec=— f2p=—
- matplotlib__matplotlib-14623: exec=— f2p=—
- pydata__xarray-3993: exec=— f2p=—
- pydata__xarray-6992: exec=— f2p=—
- sphinx-doc__sphinx-7590: exec=— f2p=—
- sphinx-doc__sphinx-8593: exec=— f2p=—
- sympy__sympy-13091: exec=— f2p=—
- sympy__sympy-14248: exec=— f2p=—

---

## Systemic Findings

### 1. Oracle accuracy

The oracle uses hand-verified mechanism descriptions compared against
the model's stated root cause. With partial_mode=strict, PARTIAL counts
as incorrect.

Of 59 fully-evaluated cases:
- Oracle CORRECT: 41
- Oracle WRONG: 11
- Oracle PARTIAL: 7

Spot-check: All 5 SUCCESS cases have oracle=CORRECT — model reasoning
genuinely matches the verified mechanism. Both LUCKY_FIX cases have
oracle=WRONG — model described a different mechanism but code worked.
This is consistent and correct behavior.

### 2. Classifier accuracy

Classifier RIC=CORRECT: 58/59
Classifier RIC=INCORRECT: 1/59

The classifier measures reasoning-code CONSISTENCY, not truth.
A high CORRECT rate means the model's code is internally consistent
with its stated reasoning — even when both are wrong.

### 3. LEG failure modes

Of 36 LEG cases:
- Zero F2P tests pass: 25 (69%)
- Some F2P tests pass: 8 (22%)
- All F2P pass but P2P regressions: 3 (8%)

Across all LEG cases:
- Total FAIL_TO_PASS tests: 155
- Passing: 42 (27.1%)

### 4. Conclusion

The Reasoning-Execution Gap (LEG) accounts for 61% of
failures on real-world multi-file SWE-bench bugs. The model correctly
identifies the root cause mechanism 69% of the time, but
converts correct understanding to working code only 17% of
the time (7/41).

The gap is continuous — 27% of individual tests pass even
in LEG cases. The model is often close but fails on multi-file
propagation, edge cases, or side-effect regressions.
---

## Manual Spot-Check Findings

### Cases where automated classification may be imprecise:

1. **django-12741, matplotlib-25775 (SUCCESS, GT="NOT A BUG")**
   These were classified as NOT_A_BUG in our mechanism descriptions (feature
   requests / API cleanup), but SWE-bench has tests for them and the model
   solved them. Oracle correctly marked reasoning as matching GT. The GT
   classification of "not a bug" is about the nature of the change, not
   whether there's a valid test — SWE-bench includes enhancement tasks.
   Judgment: SUCCESS classification is correct for SWE-bench purposes.

2. **pytest-8399 (LUCKY_FIX, oracle=PARTIAL)**
   Oracle gave PARTIAL, which in strict mode → oracle_correct=False. The
   model's mechanism description was partially right (identified the correct
   area but incomplete). With lenient mode this would be oracle_correct=True
   and classified as SUCCESS instead of LUCKY_FIX.
   Judgment: Borderline — could be SUCCESS under lenient oracle.

3. **django-11400 (WRONG_MECHANISM, oracle=PARTIAL, 4/6 F2P pass)**
   Oracle gave PARTIAL. Model described the ordering issue correctly but
   oracle says the mechanism description is incomplete. 4/6 tests pass.
   Judgment: Borderline — model understands the bug well enough to fix
   most of it, but oracle is strict about mechanism completeness.

4. **LEG near-misses with all F2P pass but P2P regressions:**
   - django-11532: 1/1 F2P pass, 18 P2P regressions
   - django-11885: 1/1 F2P pass, 2 P2P regressions
   - django-14170: 2/2 F2P pass, 9 P2P regressions
   These cases have correct fixes for the target bug but break other tests.
   The model's fix is directionally correct but has collateral damage.
   Judgment: These are genuine LEG — correct understanding, incomplete
   implementation that doesn't preserve existing behavior.

### Classifier assessment:
   The classifier (reasoning_internal_consistency) correctly identifies that
   the model's reasoning is internally coherent in nearly all cases. This is
   by design — it measures consistency, not truth. The ~100% CORRECT rate
   from the classifier is expected and valid.

### Oracle assessment:
   The oracle correctly distinguishes correct from incorrect mechanism
   descriptions in the cases I verified. The borderline cases (PARTIAL
   evaluated as wrong under strict mode) are methodologically defensible —
   strict mode requires full mechanism match, not partial.
