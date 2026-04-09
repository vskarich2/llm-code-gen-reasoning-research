# SWE-BENCH CASE MECHANISM JUSTIFICATIONS
# Total cases: 71
# Generated: 2026-04-06

================================================================================
## astropy__astropy-13398
Repo: astropy/astropy
Files: ['astropy/coordinates/builtin_frames/__init__.py', 'astropy/coordinates/builtin_frames/intermediate_rotation_transforms.py', 'astropy/coordinates/builtin_frames/itrs.py', 'astropy/coordinates/builtin_frames/itrs_observed_transforms.py']

### Bug Description
A direct approach to ITRS to Observed transformations that stays within the ITRS. <!-- This comments are hidden when you submit the issue, so you do not need to remove them! -->  <!-- Please be sure to check out our contributing guidelines, https://github.com/astropy/astropy/blob/main/CONTRIBUTI

### Mechanism Source
ITRS-to-Observed coordinate transforms go through intermediate GCRS/TETE frames, losing topocentric location information because they hardcode EARTH_CENTER instead of propagating the observer's location

### Mechanism Steps
  1. User requests a coordinate transform from ITRS (earth-fixed) to an observed frame (AltAz/HADec)
  2. The transform chain goes ITRS → TETE/CIRS → GCRS → observed, passing through intermediate frames
  3. In itrs_to_tete and itrs_to_cirs, the frame is constructed with location=EARTH_CENTER instead of location=itrs_coo.location
  4. The observer's topocentric position is lost, producing geocentric instead of topocentric coordinates
  5. Fix: propagate itrs_coo.location through intermediate frames and add direct ITRS-to-observed transform path

### Justification
Bug type: missing_transform_path
Mechanism outcome: ITRS-to-observed transforms produce geocentric results instead of topocentric, giving wrong altitude/azimuth for ground observers
Trap: Adding only the direct transform without fixing the location propagation in intermediate frames

Evidence: Derived from reference patch diff analysis. The patch modifies
4 file(s): astropy/coordinates/builtin_frames/__init__.py, astropy/coordinates/builtin_frames/intermediate_rotation_transforms.py, astropy/coordinates/builtin_frames/itrs.py, astropy/coordinates/builtin_frames/itrs_observed_transforms.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## astropy__astropy-14369
Repo: astropy/astropy
Files: ['astropy/units/format/cds.py', 'astropy/units/format/cds_parsetab.py']

### Bug Description
Incorrect units read from MRT (CDS format) files with astropy.table ### Description  When reading MRT files (formatted according to the CDS standard which is also the format recommended by AAS/ApJ) with `format='ascii.cds'`, astropy.table incorrectly parses composite units. According to CDS standard

### Mechanism Source
CDS unit parser grammar has wrong associativity for division — 'combined_units DIVISION unit_expression' should be 'unit_expression DIVISION combined_units', causing compound units to be parsed incorrectly

### Mechanism Steps
  1. User reads an MRT/CDS-format file containing compound unit strings like 'km/s/Mpc'
  2. The CDS YACC grammar rule for division has operands in wrong order: 'unit_expression DIVISION combined_units'
  3. This causes the parser to associate division right-to-left instead of left-to-right
  4. Compound units are parsed with incorrect grouping, producing wrong unit conversions
  5. Fix: swap the grammar rule to 'combined_units DIVISION unit_expression' and regenerate parse table

### Justification
Bug type: grammar_parsing_error
Mechanism outcome: Units read from CDS-format files are incorrect, producing wrong numerical values in astronomical data
Trap: Editing only cds.py without regenerating cds_parsetab.py, or fixing the wrong grammar rule

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): astropy/units/format/cds.py, astropy/units/format/cds_parsetab.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## astropy__astropy-8707
Repo: astropy/astropy
Files: ['astropy/io/fits/card.py', 'astropy/io/fits/header.py']

### Bug Description
Header.fromstring does not accept Python 3 bytes According to [the docs](http://docs.astropy.org/en/stable/_modules/astropy/io/fits/header.html#Header.fromstring), the method `Header.fromstring` "...creates an HDU header from a byte string containing the entire header data."  By "byte string" here

### Mechanism Source
Header.fromstring and Card.fromstring do not accept bytes input on Python 3, despite the documentation claiming they do

### Mechanism Steps
  1. User calls Header.fromstring() with a bytes object (common when reading from binary FITS files)
  2. The method expects str input and fails when receiving bytes on Python 3
  3. Card.fromstring has the same issue — no bytes-to-str conversion
  4. Fix: add isinstance(image, bytes) check and decode as latin-1 in both Card.fromstring and Header.fromstring
  5. Also update docstrings to document bytes acceptance

### Justification
Bug type: missing_type_handling
Mechanism outcome: Header.fromstring raises TypeError when given bytes input on Python 3
Trap: Fixing only header.py without also fixing card.py, or using utf-8 instead of latin-1 for decoding

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): astropy/io/fits/card.py, astropy/io/fits/header.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-10554
Repo: django/django
Files: ['django/db/models/sql/compiler.py', 'django/db/models/sql/query.py']

### Bug Description
Union queryset with ordering breaks on ordering with derived querysets Description 	  		(last modified by Sergei Maertens) 	  May be related to #29692 Simple reproduction (the exact models are not relevant I think): >>> Dimension.objects.values_list('id', flat=True) <QuerySet [10, 11, 12, 13, 14, 15

### Mechanism Source
Union querysets with ordering break when the ordering references columns from derived/combined querysets because change_aliases doesn't properly remap ordering references

### Mechanism Steps
  1. Two querysets are combined with .union() and .order_by() is applied to the result
  2. The compiler calls get_order_by() which resolves ordering fields against the query's column references
  3. get_order_by uses get_order_dir to parse the ordering string, but this import/function is needed for the resolution
  4. When the combined query changes aliases via change_aliases, the ordering expressions reference stale aliases from the original subqueries
  5. The SQL compiler generates ORDER BY clauses with invalid column references, causing a database error

### Justification
Bug type: ordering_alias_conflict
Mechanism outcome: Union querysets with .order_by() raise database errors because ordering references invalid aliases
Trap: Fixing only compiler.py without also fixing the alias remapping in query.py's change_aliases method

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/db/models/sql/compiler.py, django/db/models/sql/query.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-11138
Repo: django/django
Files: ['django/db/backends/mysql/operations.py', 'django/db/backends/oracle/operations.py', 'django/db/backends/sqlite3/base.py', 'django/db/backends/sqlite3/operations.py']

### Bug Description
TIME_ZONE value in DATABASES settings is not used when making dates timezone-aware on MySQL, SQLite, and Oracle. Description 	  		(last modified by Victor Talpaert) 	  (We assume the mysql backends) I can set TIME_ZONE several times in settings.py, one for the global django app, and one for each dat

### Mechanism Source
MySQL, SQLite, and Oracle backends hardcode UTC as the source timezone when converting dates, ignoring the TIME_ZONE setting in DATABASES

### Mechanism Steps
  1. User configures DATABASES with a specific TIME_ZONE (e.g., 'US/Eastern')
  2. MySQL backend's date_trunc_sql uses CONVERT_TZ(field, 'UTC', target) — hardcoding UTC as source
  3. Oracle backend similarly hardcodes FROM_TZ(field, '0:00') assuming UTC storage
  4. SQLite backend doesn't account for connection timezone in its datetime functions
  5. Fix: replace hardcoded 'UTC'/'0:00' with self.connection.timezone_name in all three backends

### Justification
Bug type: hardcoded_timezone_assumption
Mechanism outcome: Date/time queries return wrong results when database TIME_ZONE differs from UTC
Trap: Fixing only one backend (e.g., MySQL) without also fixing Oracle and SQLite

Evidence: Derived from reference patch diff analysis. The patch modifies
4 file(s): django/db/backends/mysql/operations.py, django/db/backends/oracle/operations.py, django/db/backends/sqlite3/base.py, django/db/backends/sqlite3/operations.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-11333
Repo: django/django
Files: ['django/urls/base.py', 'django/urls/resolvers.py']

### Bug Description
Optimization: Multiple URLResolvers may be unintentionally be constructed by calls to `django.urls.resolvers.get_resolver` Description 	 Multiple URLResolvers may be constructed by django.urls.resolvers.get_resolver if django.urls.base.set_urlconf has not yet been called, resulting in multiple expen

### Mechanism Source
get_resolver is decorated with @lru_cache but set_urlconf calls get_resolver.cache_clear(), and the reverse() function imports get_resolver directly — when cache is cleared, stale resolvers may persist

### Mechanism Steps
  1. get_resolver() is decorated with @lru_cache to cache URLResolver instances
  2. set_urlconf() calls get_resolver.cache_clear() to invalidate the cache
  3. But reverse() imports get_resolver directly, and the lru_cache decoration creates a new wrapper
  4. Fix: extract the cached function to _get_cached_resolver, have get_resolver delegate to it, and clear _get_cached_resolver's cache
  5. This ensures cache_clear() targets the actual cached function

### Justification
Bug type: cache_key_mismatch
Mechanism outcome: Multiple URLResolver instances are unnecessarily constructed, causing performance degradation
Trap: Moving the lru_cache without updating the cache_clear call in set_urlconf

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/urls/base.py, django/urls/resolvers.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-11400
Repo: django/django
Files: ['django/contrib/admin/filters.py', 'django/db/models/fields/__init__.py', 'django/db/models/fields/reverse_related.py']

### Bug Description
Ordering problem in admin.RelatedFieldListFilter and admin.RelatedOnlyFieldListFilter Description 	 RelatedFieldListFilter doesn't fall back to the ordering defined in Model._meta.ordering.  Ordering gets set to an empty tuple in ​https://github.com/django/django/blob/2.2.1/django/contrib/admin/filt

### Mechanism Source
RelatedFieldListFilter.field_choices does not pass an ordering parameter to field.get_choices(), and get_choices itself doesn't accept ordering for forward/reverse relations

### Mechanism Steps
  1. Admin page renders a RelatedFieldListFilter for a ForeignKey field
  2. field_choices() gets ordering from the related model's admin but doesn't pass it to get_choices()
  3. Field.get_choices() and ForeignObject.get_choices() don't accept an ordering parameter
  4. The filter dropdown shows related objects in arbitrary database order instead of the model's defined ordering
  5. Fix: add ordering parameter to get_choices() in fields/__init__.py and reverse_related.py, pass it from field_choices()

### Justification
Bug type: missing_ordering_propagation
Mechanism outcome: Admin list filter dropdowns for related fields show items in wrong/arbitrary order
Trap: Adding ordering to filters.py without also updating the get_choices method signature in fields

Evidence: Derived from reference patch diff analysis. The patch modifies
3 file(s): django/contrib/admin/filters.py, django/db/models/fields/__init__.py, django/db/models/fields/reverse_related.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-11532
Repo: django/django
Files: ['django/core/mail/message.py', 'django/core/mail/utils.py', 'django/core/validators.py', 'django/utils/encoding.py', 'django/utils/html.py']

### Bug Description
Email messages crash on non-ASCII domain when email encoding is non-unicode. Description 	 When the computer hostname is set in unicode (in my case "正宗"), the following test fails: ​https://github.com/django/django/blob/master/tests/mail/tests.py#L368 Specifically, since the encoding is set to iso-8

### Mechanism Source
Multiple places in Django encode internationalized domain names using inline domain.encode('idna').decode('ascii'), which crashes on non-ASCII hostnames when the system encoding is not unicode

### Mechanism Steps
  1. System hostname contains non-ASCII characters (e.g., unicode hostname)
  2. Email message construction calls sanitize_address which does domain.encode('idna').decode('ascii') inline
  3. CachedDnsName.__str__ calls socket.getfqdn() which returns the unicode hostname
  4. URLValidator and html.py have similar inline idna encoding that can crash
  5. Fix: create a centralized punycode() helper in encoding.py and use it in all 5 files

### Justification
Bug type: scattered_encoding_logic
Mechanism outcome: Email messages crash with UnicodeError when system hostname contains non-ASCII characters
Trap: Fixing only message.py without also fixing validators.py, utils.py, encoding.py, and html.py

Evidence: Derived from reference patch diff analysis. The patch modifies
5 file(s): django/core/mail/message.py, django/core/mail/utils.py, django/core/validators.py, django/utils/encoding.py, django/utils/html.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-11734
Repo: django/django
Files: ['django/db/models/fields/__init__.py', 'django/db/models/fields/related_lookups.py', 'django/db/models/sql/query.py']

### Bug Description
OuterRef in exclude() or ~Q() uses wrong model. Description 	 The following test (added to tests/queries/test_qs_combinators) fails when trying to exclude results using OuterRef() def test_exists_exclude(self): 	# filter() 	qs = Number.objects.annotate( 		foo=Exists( 			Item.objects.filter(tags__cat

### Mechanism Source
OuterRef in exclude() or ~Q() resolves against the wrong model because split_exclude doesn't preserve OuterRef references through the query split

### Mechanism Steps
  1. User writes a subquery with OuterRef inside exclude() or ~Q()
  2. query.py's split_exclude() processes the filter, checking if rhs is an F expression
  3. OuterRef extends F but needs special handling — it should not be resolved against the subquery model
  4. The isinstance(filter_rhs, F) check catches OuterRef and incorrectly wraps it
  5. Fix: check for OuterRef before F in split_exclude, and remove the unnecessary get_prep_value override in fields/__init__.py

### Justification
Bug type: outer_ref_model_confusion
Mechanism outcome: Queries using OuterRef in exclude() produce wrong SQL referencing the wrong model's columns
Trap: Fixing only query.py without also cleaning up the related_lookups.py and fields changes

Evidence: Derived from reference patch diff analysis. The patch modifies
3 file(s): django/db/models/fields/__init__.py, django/db/models/fields/related_lookups.py, django/db/models/sql/query.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-11885
Repo: django/django
Files: ['django/contrib/admin/utils.py', 'django/db/models/deletion.py']

### Bug Description
Combine fast delete queries Description 	 When emulating ON DELETE CASCADE via on_delete=models.CASCADE the deletion.Collector will try to perform fast queries which are DELETE FROM table WHERE table.pk IN .... There's a few conditions required for this fast path to be taken but when this happens th

### Mechanism Source
Collector issues separate DELETE queries for each related object found during CASCADE, instead of combining them into batch queries grouped by model

### Mechanism Steps
  1. User deletes an object with on_delete=CASCADE relations
  2. Collector.collect() discovers related objects one relation at a time
  3. Each relation produces a separate fast_deletes entry with its own queryset
  4. Multiple DELETE FROM same_table WHERE ... queries are issued instead of one combined query
  5. Fix: refactor Collector to use defaultdict(set) for data, combine fast_deletes by model, and use reduce(operator.or_) for filters

### Justification
Bug type: suboptimal_cascade_queries
Mechanism outcome: CASCADE deletions issue O(n) DELETE queries instead of O(1) per model, causing poor performance
Trap: Changing deletion.py without updating admin/utils.py which overrides related_objects with a different signature

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/contrib/admin/utils.py, django/db/models/deletion.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-12155
Repo: django/django
Files: ['django/contrib/admindocs/utils.py', 'django/contrib/admindocs/views.py']

### Bug Description
docutils reports an error rendering view docstring when the first line is not empty Description 	 Currently admindoc works correctly only with docstrings where the first line is empty, and all Django docstrings are formatted in this way. However usually the docstring text starts at the first line, e

### Mechanism Source
trim_docstring in admindocs/utils.py implements PEP 257 indentation trimming incorrectly, failing when the first line of a docstring is not empty

### Mechanism Steps
  1. Admin docs renders a view's docstring using trim_docstring()
  2. If the first line contains text (not empty), the custom trimming logic miscalculates indentation
  3. This produces malformed RST that docutils cannot render, showing errors instead of documentation
  4. Python's inspect.cleandoc already handles this correctly for both docstring styles
  5. Fix: replace custom trim_docstring with inspect.cleandoc in utils.py, update views.py to use it

### Justification
Bug type: docstring_indentation_error
Mechanism outcome: Admin docs page shows docutils rendering errors for views with non-empty first docstring lines
Trap: Fixing only the indentation calculation instead of replacing with inspect.cleandoc

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/contrib/admindocs/utils.py, django/contrib/admindocs/views.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-12325
Repo: django/django
Files: ['django/db/models/base.py', 'django/db/models/options.py']

### Bug Description
pk setup for MTI to parent get confused by multiple OneToOne references. Description 	 class Document(models.Model): 	pass class Picking(Document): 	document_ptr = models.OneToOneField(Document, on_delete=models.CASCADE, parent_link=True, related_name='+') 	origin = models.OneToOneField(Document, re

### Mechanism Source
In multi-table inheritance with multiple OneToOneFields to the parent, Django's pk setup incorrectly picks the wrong field as the primary key link

### Mechanism Steps
  1. Model inherits from parent and has multiple OneToOneField references to the parent
  2. One is the implicit parent_link (MTI pk), others are regular OneToOneFields
  3. options.py pk detection logic gets confused by multiple OneToOneFields to the same parent
  4. The wrong field is selected as the pk, causing query and save failures
  5. Fix: tighten the pk detection in base.py and options.py to use parent_link attribute explicitly

### Justification
Bug type: pk_field_confusion
Mechanism outcome: Models with MTI and additional OneToOneFields to the parent fail to save or query correctly
Trap: Fixing only options.py without also fixing base.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/db/models/base.py, django/db/models/options.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-12406
Repo: django/django
Files: ['django/db/models/fields/related.py', 'django/forms/models.py']

### Bug Description
ModelForm RadioSelect widget for foreign keys should not present a blank option if blank=False on the model Description 	 Unlike the select widget, where a blank option is idiomatic even for required fields, radioselect has an inherent unfilled state that makes the "-------" option look suspiciously

### Mechanism Source
ModelForm with RadioSelect widget for ForeignKey always includes a blank choice even when blank=False on the model field

### Mechanism Steps
  1. User creates a ModelForm with a ForeignKey field that has blank=False
  2. The form field uses RadioSelect widget
  3. ModelChoiceField always includes include_blank=True for RadioSelect regardless of model field's blank setting
  4. The radio group shows an empty '---------' option that shouldn't be there
  5. Fix: check field.blank in forms/models.py and only include blank choice when blank=True, update related.py get_choices accordingly

### Justification
Bug type: blank_choice_not_respecting_model
Mechanism outcome: RadioSelect widget for ForeignKey shows a blank option even when blank=False on the model
Trap: Fixing only forms/models.py without updating the related field's get_choices method

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/db/models/fields/related.py, django/forms/models.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-12741
Repo: django/django
Files: ['django/core/management/commands/flush.py', 'django/db/backends/base/operations.py']

### Bug Description
Simplify signature of `DatabaseOperations.execute_sql_flush()` Description 	 The current signature is: def execute_sql_flush(self, using, sql_list): The using argument can be dropped and inferred by the calling instance: self.connection.alias. def execute_sql_flush(self, sql_list): Some internal ise

### Mechanism Source
execute_sql_flush takes a 'using' parameter that is redundant because self.connection.alias already identifies the database

### Mechanism Steps
  1. execute_sql_flush(self, using, sql_list) takes 'using' as explicit parameter for transaction.atomic(using=using)
  2. Callers already have the connection object and pass connection.alias as the 'using' argument
  3. This creates a redundant interface where 'using' must always equal self.connection.alias
  4. Fix: remove 'using' parameter, use self.connection.alias directly, and wrap in transaction.atomic using self.connection.alias
  5. flush.py command must be updated to call execute_sql_flush(sql_list) without the database argument

### Justification
Bug type: redundant_parameter
Mechanism outcome: Redundant API parameter creates confusion and potential for misuse; callers must pass the same value that the method could derive internally
Trap: Changing only the method signature without updating the flush command caller, or forgetting to use self.connection.alias in the transaction.atomic call

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/core/management/commands/flush.py, django/db/backends/base/operations.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-13121
Repo: django/django
Files: ['django/db/backends/base/operations.py', 'django/db/backends/mysql/operations.py', 'django/db/backends/sqlite3/operations.py', 'django/db/models/expressions.py']

### Bug Description
durations-only expressions doesn't work on SQLite and MySQL Description 	 class Experiment(models.Model): 	estimated_time = models.DurationField() list(Experiment.objects.annotate(duration=F('estimated_time') + datime.timedelta(1))) Traceback (most recent call last):  File "/home/sergey/dev/django/t

### Mechanism Source
Duration-only expressions (DurationField +/- DurationField) don't work on SQLite and MySQL because the backends don't handle the case where both sides are durations

### Mechanism Steps
  1. User writes an expression like F('estimated_time') + F('extra_time') where both are DurationFields
  2. The expression compiler calls combine_duration_expression on the backend
  3. SQLite and MySQL backends assume one side is a datetime and apply date arithmetic functions
  4. Pure duration arithmetic (microseconds + microseconds) produces SQL errors or wrong results
  5. Fix: update combine_duration_expression in sqlite3/mysql operations and expressions.py to detect and handle duration+duration case

### Justification
Bug type: duration_expression_backend_inconsistency
Mechanism outcome: Queries with duration+duration expressions crash or return wrong results on SQLite and MySQL
Trap: Fixing only one backend without fixing both SQLite and MySQL, or not updating expressions.py

Evidence: Derived from reference patch diff analysis. The patch modifies
4 file(s): django/db/backends/base/operations.py, django/db/backends/mysql/operations.py, django/db/backends/sqlite3/operations.py, django/db/models/expressions.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-13195
Repo: django/django
Files: ['django/contrib/messages/storage/cookie.py', 'django/contrib/sessions/middleware.py', 'django/http/response.py']

### Bug Description
HttpResponse.delete_cookie() should preserve cookie's samesite. Description 	 We noticed we were getting this warning message from Firefox: 'Cookie “messages” will be soon rejected because it has the “sameSite” attribute set to “none” or an invalid value, without the “secure” attribute. To know more

### Mechanism Source
HttpResponse.delete_cookie() does not preserve the samesite attribute from the original cookie, causing browser warnings about SameSite policy

### Mechanism Steps
  1. Application sets a cookie with SameSite=Lax or SameSite=None
  2. Later, delete_cookie() is called to remove it
  3. delete_cookie() in response.py doesn't accept or pass through the samesite parameter
  4. The deletion cookie is sent without SameSite, triggering browser warnings about cross-site cookie behavior
  5. Fix: add samesite parameter to delete_cookie() in response.py, update session middleware and cookie storage to pass it through

### Justification
Bug type: cookie_attribute_not_preserved
Mechanism outcome: Browser warnings about SameSite cookie policy when deleting cookies
Trap: Fixing only response.py without updating middleware.py and cookie.py that call delete_cookie

Evidence: Derived from reference patch diff analysis. The patch modifies
3 file(s): django/contrib/messages/storage/cookie.py, django/contrib/sessions/middleware.py, django/http/response.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-13212
Repo: django/django
Files: ['django/core/validators.py', 'django/forms/fields.py']

### Bug Description
Make validators include the provided value in ValidationError Description 	 It is sometimes desirable to include the provide value in a custom error message. For example: “blah” is not a valid email. By making built-in validators provide value to ValidationError, one can override an error message an

### Mechanism Source
Django validators do not include the invalid value in the ValidationError params, making it impossible to reference the value in custom error messages

### Mechanism Steps
  1. User creates a form field with validators (URLValidator, EmailValidator, etc.)
  2. Validation fails and the validator raises ValidationError
  3. The error's params dict does not include the actual invalid value
  4. Custom error message templates cannot reference %(value)s because it's not in params
  5. Fix: add 'value' to params in validators.py and update form fields.py to pass value through

### Justification
Bug type: validator_missing_value_in_error
Mechanism outcome: Validators cannot include the invalid value in error messages, limiting error message customization
Trap: Fixing only validators.py without also updating fields.py, or breaking existing error message formats

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/core/validators.py, django/forms/fields.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-13344
Repo: django/django
Files: ['django/contrib/sessions/middleware.py', 'django/middleware/cache.py', 'django/middleware/security.py']

### Bug Description
Coroutine passed to the first middleware's process_response() instead of HttpResponse. Description 	 Like the title says, using ASGI (+ uvicorn in my case), the first middleware (according to the list in settings.py) receives a coroutine as its response parameter, while all other middlewares down th

### Mechanism Source
When using async middleware, process_response receives a coroutine instead of an HttpResponse because the async-to-sync adaptation doesn't await the response

### Mechanism Steps
  1. Application uses async views with middleware that defines process_response
  2. The middleware chain adapts between sync and async using ASGIHandler
  3. When the first middleware's process_response is called, it receives the coroutine instead of the awaited response
  4. process_response fails because it tries to operate on a coroutine object instead of HttpResponse
  5. Fix: ensure response is awaited before passing to process_response in session middleware, cache middleware, and security middleware

### Justification
Bug type: async_middleware_response_type
Mechanism outcome: First middleware's process_response receives a coroutine object instead of HttpResponse, causing AttributeError
Trap: Fixing only one middleware without fixing all three (session, cache, security)

Evidence: Derived from reference patch diff analysis. The patch modifies
3 file(s): django/contrib/sessions/middleware.py, django/middleware/cache.py, django/middleware/security.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-13512
Repo: django/django
Files: ['django/contrib/admin/utils.py', 'django/forms/fields.py']

### Bug Description
Admin doesn't display properly unicode chars in JSONFields. Description 	  		(last modified by ZhaoQi99) 	  >>> import json >>> print json.dumps('中国') "\u4e2d\u56fd" json.dumps use ASCII encoding by default when serializing Chinese. So when we edit a JsonField which contains Chinese character in Dja

### Mechanism Source
Admin display for JSONField uses json.dumps with ensure_ascii=True (default), escaping unicode characters to \uXXXX sequences instead of displaying them

### Mechanism Steps
  1. User stores unicode data in a JSONField
  2. Admin displays the field value using json.dumps() with default ensure_ascii=True
  3. Unicode characters are escaped to \u sequences (e.g., '\u4e2d' instead of '中')
  4. Fix: pass ensure_ascii=False to json.dumps in admin/utils.py and forms/fields.py
  5. This preserves the actual unicode characters in the display

### Justification
Bug type: json_unicode_escaping
Mechanism outcome: Admin JSONField display shows \uXXXX escape sequences instead of actual unicode characters
Trap: Fixing only one of the two display paths (admin/utils.py vs forms/fields.py)

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/contrib/admin/utils.py, django/forms/fields.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-14011
Repo: django/django
Files: ['django/core/servers/basehttp.py', 'django/db/backends/sqlite3/features.py']

### Bug Description
LiveServerTestCase's ThreadedWSGIServer doesn't close database connections after each thread Description 	 In Django 2.2.17, I'm seeing the reappearance of #22414 after it was fixed in 1.11. #22414 is the issue where the following error will occur at the conclusion of a test run when destroy_test_db

### Mechanism Source
LiveServerTestCase's ThreadedWSGIServer doesn't close database connections when threads finish, causing connection leaks and 'database is locked' errors on SQLite

### Mechanism Steps
  1. LiveServerTestCase starts a ThreadedWSGIServer for testing
  2. Each request is handled in a separate thread that opens database connections
  3. When threads finish, they don't call close_old_connections(), leaving connections open
  4. On SQLite, this causes 'database is locked' errors from concurrent open connections
  5. Fix: add connection cleanup in basehttp.py's thread handling and mark SQLite as supporting this in features.py

### Justification
Bug type: unclosed_database_connections
Mechanism outcome: LiveServerTestCase causes 'database is locked' errors on SQLite due to unclosed thread connections
Trap: Fixing only basehttp.py without updating sqlite3/features.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/core/servers/basehttp.py, django/db/backends/sqlite3/features.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-14170
Repo: django/django
Files: ['django/db/backends/base/operations.py', 'django/db/models/lookups.py']

### Bug Description
Query optimization in YearLookup breaks filtering by "__iso_year" Description 	  		(last modified by Florian Demmer) 	  The optimization to use BETWEEN instead of the EXTRACT operation in ​YearLookup is also registered for the ​"__iso_year" lookup, which breaks the functionality provided by ​Extract

### Mechanism Source
YearLookup optimization incorrectly handles __iso_year lookups by using calendar year bounds instead of ISO year bounds

### Mechanism Steps
  1. User filters queryset with __iso_year lookup (ISO 8601 week-numbering year)
  2. YearLookup optimization in lookups.py converts year lookups to BETWEEN date range queries
  3. The optimization uses year_lookup_bounds_for_date_field which returns Jan 1 to Dec 31 — calendar year bounds
  4. ISO years can start in late December or end in early January, so calendar bounds give wrong results
  5. Fix: add iso_year-specific handling in lookups.py and year_lookup_bounds in operations.py

### Justification
Bug type: iso_year_lookup_broken
Mechanism outcome: Filtering by __iso_year returns wrong results at year boundaries (late Dec / early Jan)
Trap: Fixing only lookups.py without also adding ISO year bounds to operations.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/db/backends/base/operations.py, django/db/models/lookups.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-14315
Repo: django/django
Files: ['django/db/backends/base/client.py', 'django/db/backends/postgresql/client.py']

### Bug Description
database client runshell doesn't respect os.environ values in some cases Description 	  		(last modified by Konstantin Alekseev) 	  postgresql client returns empty dict instead of None for env as a result os.environ is not used and empty env passed to subprocess. Bug introduced in ​https://github.co

### Mechanism Source
PostgreSQL settings_to_cmd_args_env returns empty dict {} when no password/service/ssl options are set, and runshell uses 'if env:' which is falsey for empty dict

### Mechanism Steps
  1. DatabaseClient.settings_to_cmd_args_env initializes env={} and only populates it if password/service/ssl options exist
  2. When no such options are configured, the method returns (args, {}) — an empty dict, not None
  3. BaseDatabaseClient.runshell checks 'if env:' which is False for empty dict, skipping the os.environ merge
  4. subprocess.run is called with env={} instead of env=None, stripping all environment variables from the child process
  5. The database client shell fails because PATH and other required env vars are missing

### Justification
Bug type: semantic_truthiness_error
Mechanism outcome: Database shell (psql) fails to start or loses environment variables when no password/SSL options are configured
Trap: Adding 'if env is not None' guard without also fixing the postgresql client to return None instead of {} when no env vars are set — need both files changed

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/db/backends/base/client.py, django/db/backends/postgresql/client.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-14376
Repo: django/django
Files: ['django/db/backends/mysql/base.py', 'django/db/backends/mysql/client.py']

### Bug Description
MySQL backend uses deprecated "db" and "passwd" kwargs. Description 	 The "db" and "passwd" usage can be seen at ​https://github.com/django/django/blob/ca9872905559026af82000e46cde6f7dedc897b6/django/db/backends/mysql/base.py#L202-L205 in main. mysqlclient recently marked these two kwargs as depreca

### Mechanism Source
MySQL backend uses deprecated 'db' and 'passwd' kwargs instead of 'database' and 'password' in connection parameters

### Mechanism Steps
  1. User connects to MySQL database
  2. mysql/base.py passes 'db' and 'passwd' kwargs to the MySQL connector
  3. These kwargs are deprecated in newer MySQL connector versions, producing deprecation warnings
  4. mysql/client.py similarly uses deprecated parameter names for the command-line client
  5. Fix: rename 'db' to 'database' and 'passwd' to 'password' in both base.py and client.py

### Justification
Bug type: deprecated_kwargs
Mechanism outcome: DeprecationWarning from MySQL connector about 'db' and 'passwd' parameters
Trap: Fixing only base.py without also fixing client.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/db/backends/mysql/base.py, django/db/backends/mysql/client.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-14631
Repo: django/django
Files: ['django/forms/boundfield.py', 'django/forms/forms.py']

### Bug Description
BaseForm's _clean_fields() and changed_data should access values via BoundField Description 	  		(last modified by Chris Jerdonek) 	  While working on #32917, I noticed that ​BaseForm._clean_fields() and ​BaseForm.changed_data don't currently access their values through a BoundField object. It would

### Mechanism Source
BaseForm._clean_fields() and changed_data access field values directly via widget instead of going through BoundField, bypassing custom BoundField.value() overrides

### Mechanism Steps
  1. User creates a custom BoundField subclass that overrides value() method
  2. BaseForm._clean_fields() calls field.widget.value_from_datadict() directly
  3. BaseForm.changed_data also accesses values bypassing BoundField
  4. Custom BoundField.value() logic is ignored during cleaning and change detection
  5. Fix: refactor _clean_fields() and changed_data in forms.py to use BoundField, update boundfield.py accordingly

### Justification
Bug type: form_value_access_inconsistency
Mechanism outcome: Custom BoundField.value() overrides are ignored during form cleaning and changed_data computation
Trap: Fixing only forms.py without also updating boundfield.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/forms/boundfield.py, django/forms/forms.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-15103
Repo: django/django
Files: ['django/template/defaultfilters.py', 'django/utils/html.py']

### Bug Description
Make the element_id argument of json_script optional Description 	 I recently had a use-case where I wanted to use json_script but I didn't need any id for it (I was including the <script> inside a <template> so I didn't need an id to refer to it). I can't see any reason (security or otherwise) for

### Mechanism Source
json_script template filter requires an element_id argument, but some use cases need script tags without an id attribute

### Mechanism Steps
  1. User wants to embed JSON in a script tag without an id attribute
  2. json_script filter in defaultfilters.py requires element_id as a mandatory argument
  3. The underlying json_script utility in html.py also requires it
  4. Fix: make element_id optional (default None) in both html.py and defaultfilters.py
  5. When None, produce <script type='application/json'> without id attribute

### Justification
Bug type: required_argument_should_be_optional
Mechanism outcome: Cannot use json_script without specifying an element_id
Trap: Fixing only html.py without also updating defaultfilters.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/template/defaultfilters.py, django/utils/html.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-15561
Repo: django/django
Files: ['django/db/backends/base/schema.py', 'django/db/models/fields/__init__.py']

### Bug Description
AlterField operation should be noop when adding/changing choices on SQLite. Description 	 while writing a test case for #33470 i found that for sqlite, even a seemingly db-transparent change like adding choices still generates sql (new table + insert + drop + rename) even though this shouldn't be ne

### Mechanism Source
AlterField migration generates a database operation when only the 'choices' attribute changes, even though choices don't affect the database schema

### Mechanism Steps
  1. User adds or modifies choices on a model field
  2. Django generates an AlterField migration
  3. schema.py compares old and new field, but doesn't exclude choices-only changes
  4. On SQLite, this triggers an expensive table rebuild for a purely Python-side change
  5. Fix: add choices-only change detection in fields/__init__.py and schema.py to skip database operations

### Justification
Bug type: unnecessary_migration_operation
Mechanism outcome: Unnecessary database table rebuilds on SQLite when only field choices change
Trap: Fixing only schema.py without also updating the field comparison in fields/__init__.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/db/backends/base/schema.py, django/db/models/fields/__init__.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-15563
Repo: django/django
Files: ['django/db/models/sql/compiler.py', 'django/db/models/sql/subqueries.py']

### Bug Description
Wrong behavior on queryset update when multiple inheritance Description 	 Queryset update has a wrong behavior when queryset class inherits multiple classes. The update happens not on child class but on other parents class instances. Here an easy example to show the problem: class Base(models.Model)

### Mechanism Source
QuerySet.update() with multiple inheritance generates UPDATE on the wrong table when the field being updated is on a parent model

### Mechanism Steps
  1. User calls .update() on a queryset of a model using multi-table inheritance
  2. The field being updated is defined on the parent model (different table)
  3. compiler.py generates UPDATE targeting the child table instead of the parent table
  4. The update fails or updates the wrong table because the column doesn't exist there
  5. Fix: update compiler.py and subqueries.py to resolve the correct table for the field being updated

### Justification
Bug type: wrong_table_in_update
Mechanism outcome: QuerySet.update() fails or silently updates wrong table when field is on parent model in MTI
Trap: Fixing only compiler.py without also fixing subqueries.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/db/models/sql/compiler.py, django/db/models/sql/subqueries.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-15629
Repo: django/django
Files: ['django/db/backends/base/schema.py', 'django/db/backends/oracle/features.py', 'django/db/backends/sqlite3/schema.py', 'django/db/models/fields/related.py']

### Bug Description
Errors with db_collation – no propagation to foreignkeys Description 	  		(last modified by typonaut) 	  Using db_collation with a pk that also has referenced fks in other models causes foreign key constraint errors in MySQL. With the following models: class Account(models.Model): 	id = ShortUUIDFie

### Mechanism Source
When a field has db_collation set, ForeignKey fields referencing it don't inherit the collation, causing database errors on engines that require matching collations

### Mechanism Steps
  1. User defines a CharField with db_collation on a model
  2. Another model has a ForeignKey to the first model
  3. The FK column is created without the db_collation of the referenced field
  4. Database engines (Oracle, SQLite) that enforce collation matching raise errors
  5. Fix: propagate db_collation to FK columns in related.py and update schema.py for Oracle/SQLite handling

### Justification
Bug type: collation_not_propagated_to_fk
Mechanism outcome: Database errors when creating ForeignKey to a field with db_collation
Trap: Fixing only related.py without updating schema backends

Evidence: Derived from reference patch diff analysis. The patch modifies
4 file(s): django/db/backends/base/schema.py, django/db/backends/oracle/features.py, django/db/backends/sqlite3/schema.py, django/db/models/fields/related.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-16032
Repo: django/django
Files: ['django/db/models/fields/related_lookups.py', 'django/db/models/sql/query.py']

### Bug Description
__in doesn't clear selected fields on the RHS when QuerySet.alias() is used after annotate(). Description 	 Here is a test case to reproduce the bug, you can add this in tests/annotations/tests.py 	def test_annotation_and_alias_filter_in_subquery(self): 		long_books_qs = ( 			Book.objects.filter(

### Mechanism Source
__in lookup doesn't clear selected fields on the RHS queryset when alias() is used after annotate(), causing extra columns in the subquery

### Mechanism Steps
  1. User chains .annotate().alias() then uses the queryset in an __in lookup
  2. The __in lookup should clear the RHS queryset's selected fields to just pk
  3. But alias() marks annotations differently than regular annotations
  4. The clear logic in related_lookups.py doesn't account for aliased annotations
  5. Fix: update related_lookups.py and query.py to properly clear aliased annotations in __in subqueries

### Justification
Bug type: alias_annotation_leak
Mechanism outcome: Queries with __in using alias() after annotate() produce incorrect SQL with extra columns
Trap: Fixing only related_lookups.py without also fixing query.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/db/models/fields/related_lookups.py, django/db/models/sql/query.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-16256
Repo: django/django
Files: ['django/contrib/contenttypes/fields.py', 'django/db/models/fields/related_descriptors.py']

### Bug Description
acreate(), aget_or_create(), and aupdate_or_create() doesn't work as intended on related managers. Description 	 Async-compatible interface was added to QuerySet in 58b27e0dbb3d31ca1438790870b2b51ecdb10500. Unfortunately, it also added (unintentionally) async acreate(), aget_or_create(), and aupdate

### Mechanism Source
Async variants of create/get_or_create/update_or_create (acreate, aget_or_create, aupdate_or_create) are not defined on related managers, so they don't work through FK/M2M relations

### Mechanism Steps
  1. User calls obj.related_set.acreate() on a related manager
  2. The related manager (GenericRelatedObjectManager, etc.) doesn't define acreate/aget_or_create/aupdate_or_create
  3. The method falls through to the base QuerySet which doesn't set the relation properly
  4. Fix: add async method definitions in related_descriptors.py and contenttypes/fields.py
  5. Methods must wrap the sync versions with async_to_sync properly

### Justification
Bug type: async_method_not_delegated
Mechanism outcome: acreate/aget_or_create/aupdate_or_create don't work on related managers (FK, M2M, GenericRelation)
Trap: Fixing only related_descriptors.py without also fixing contenttypes/fields.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/contrib/contenttypes/fields.py, django/db/models/fields/related_descriptors.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-16263
Repo: django/django
Files: ['django/db/models/expressions.py', 'django/db/models/query_utils.py', 'django/db/models/sql/query.py', 'django/db/models/sql/where.py']

### Bug Description
Strip unused annotations from count queries Description 	 The query below produces a SQL statement that includes the Count('chapters'), despite not not being used in any filter operations. Book.objects.annotate(Count('chapters')).count() It produces the same results as: Book.objects.count() Django c

### Mechanism Source
COUNT queries don't strip unused annotations, causing unnecessary joins and subqueries that slow down .count() calls

### Mechanism Steps
  1. User calls .annotate(complex_expr).count() where the annotation is not used in any filter
  2. The COUNT query includes the full annotation with its joins even though only COUNT(*) is needed
  3. This produces unnecessarily complex SQL with extra JOINs and subqueries
  4. Fix: add annotation stripping logic in query.py, expressions.py, query_utils.py, and where.py
  5. Strip annotations that are not referenced by the where clause or ordering before generating COUNT SQL

### Justification
Bug type: unused_annotation_in_count
Mechanism outcome: COUNT queries are unnecessarily slow because they include unused annotations with extra joins
Trap: Stripping annotations without checking if they're referenced in WHERE or HAVING clauses

Evidence: Derived from reference patch diff analysis. The patch modifies
4 file(s): django/db/models/expressions.py, django/db/models/query_utils.py, django/db/models/sql/query.py, django/db/models/sql/where.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-16315
Repo: django/django
Files: ['django/db/models/query.py', 'django/db/models/sql/compiler.py']

### Bug Description
QuerySet.bulk_create() crashes on mixed case columns in unique_fields/update_fields. Description 	 Not sure exactly how to phrase this, but when I I'm calling bulk_update on the manager for a class with db_column set on fields the SQL is invalid. Ellipses indicate other fields excluded for clarity.

### Mechanism Source
bulk_create() crashes when unique_fields or update_fields contain mixed-case column names because the ON CONFLICT clause uses case-sensitive comparison

### Mechanism Steps
  1. User calls bulk_create() with update_conflicts=True on a model with mixed-case column names
  2. compiler.py generates ON CONFLICT clause matching column names case-sensitively
  3. Mixed-case names don't match, causing SQL syntax errors or wrong conflict resolution
  4. Fix: normalize column name comparison to be case-insensitive in query.py and compiler.py

### Justification
Bug type: case_sensitivity_in_field_names
Mechanism outcome: bulk_create() crashes with SQL errors when unique_fields or update_fields have mixed-case names
Trap: Fixing only compiler.py without also fixing query.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/db/models/query.py, django/db/models/sql/compiler.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-16560
Repo: django/django
Files: ['django/contrib/postgres/constraints.py', 'django/db/models/constraints.py']

### Bug Description
Allow to customize the code attribute of ValidationError raised by BaseConstraint.validate Description 	 It is currently possible to customize the violation_error_message of a ValidationError raised by a constraint but not the code. I'd like to add a new violation_error_message parameter to BaseCons

### Mechanism Source
BaseConstraint.validate raises ValidationError with a hardcoded 'constraint' code, with no way to customize the error code

### Mechanism Steps
  1. User defines a database constraint with validate() behavior
  2. When validation fails, ValidationError is raised with code='constraint'
  3. User cannot customize this code to match their error handling patterns
  4. ExclusionConstraint in postgres has the same issue
  5. Fix: add violation_error_code parameter to BaseConstraint and ExclusionConstraint

### Justification
Bug type: missing_customization_hook
Mechanism outcome: Cannot customize the error code of ValidationError raised by constraint validation
Trap: Fixing only constraints.py without also fixing postgres/constraints.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/contrib/postgres/constraints.py, django/db/models/constraints.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-16631
Repo: django/django
Files: ['django/contrib/auth/__init__.py', 'django/contrib/auth/base_user.py']

### Bug Description
SECRET_KEY_FALLBACKS is not used for sessions Description 	 I recently rotated my secret key, made the old one available in SECRET_KEY_FALLBACKS and I'm pretty sure everyone on our site is logged out now. I think the docs for ​SECRET_KEY_FALLBACKS may be incorrect when stating the following: In orde

### Mechanism Source
SECRET_KEY_FALLBACKS is not used for session verification, so rotating the secret key invalidates all existing sessions

### Mechanism Steps
  1. Admin rotates SECRET_KEY and puts the old key in SECRET_KEY_FALLBACKS
  2. Existing sessions were signed with the old key
  3. Session verification in auth/__init__.py or base_user.py only checks the current SECRET_KEY
  4. All existing sessions are invalidated because signature verification fails
  5. Fix: update auth/__init__.py and base_user.py to try fallback keys when primary verification fails

### Justification
Bug type: fallback_secrets_not_used
Mechanism outcome: Rotating SECRET_KEY invalidates all sessions even when old key is in SECRET_KEY_FALLBACKS
Trap: Fixing only auth/__init__.py without also fixing base_user.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/contrib/auth/__init__.py, django/contrib/auth/base_user.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## django__django-16938
Repo: django/django
Files: ['django/core/serializers/python.py', 'django/core/serializers/xml_serializer.py']

### Bug Description
Serialization of m2m relation fails with custom manager using select_related Description 	 Serialization of many to many relation with custom manager using select_related cause FieldError: Field cannot be both deferred and traversed using select_related at the same time. Exception is raised because

### Mechanism Source
M2M serialization calls .only('pk') on the related queryset, which conflicts with custom managers that use select_related

### Mechanism Steps
  1. Model has a M2M relation with a custom manager that applies select_related in its default queryset
  2. Serializer.handle_m2m_field calls getattr(obj, field.name).only('pk') to optimize the query
  3. .only('pk') defers all fields except pk, but the custom manager's select_related already marked fields for eager loading
  4. Django raises FieldError: 'Field cannot be both deferred and traversed using select_related at the same time'
  5. Same bug exists in both python.py and xml_serializer.py serializers

### Justification
Bug type: queryset_method_conflict
Mechanism outcome: Serialization of M2M relations crashes with FieldError when the related model uses a custom manager with select_related
Trap: Fixing only one serializer (python.py) but missing the identical bug in xml_serializer.py, or using values_list instead of properly clearing select_related

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): django/core/serializers/python.py, django/core/serializers/xml_serializer.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## matplotlib__matplotlib-14623
Repo: matplotlib/matplotlib
Files: ['lib/matplotlib/axes/_base.py', 'lib/matplotlib/ticker.py', 'lib/mpl_toolkits/mplot3d/axes3d.py']

### Bug Description
Inverting an axis using its limits does not work for log scale ### Bug report  **Bug summary** Starting in matplotlib 3.1.0 it is no longer possible to invert a log axis using its limits.  **Code for reproduction** ```python import numpy as np import matplotlib.pyplot as plt   y = np.lins

### Mechanism Source
Setting inverted axis limits (e.g., set_xlim(10, 1)) doesn't work for log scale because the log scale logic always sorts limits to ascending order

### Mechanism Steps
  1. User sets axis limits in descending order to invert the axis: ax.set_xlim(10, 1)
  2. For log scale, the tick locator/formatter in ticker.py reorders limits to ascending
  3. axes/_base.py doesn't preserve the inversion intent through the scale setup
  4. The axis appears un-inverted because limits are silently sorted
  5. Fix: update ticker.py to respect inverted limits and axes3d.py for 3D compatibility

### Justification
Bug type: log_scale_inversion_broken
Mechanism outcome: Cannot invert a log-scaled axis by setting descending limits
Trap: Fixing only axes/_base.py without also fixing ticker.py and mplot3d

Evidence: Derived from reference patch diff analysis. The patch modifies
3 file(s): lib/matplotlib/axes/_base.py, lib/matplotlib/ticker.py, lib/mpl_toolkits/mplot3d/axes3d.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## matplotlib__matplotlib-24870
Repo: matplotlib/matplotlib
Files: ['lib/matplotlib/contour.py', 'lib/matplotlib/tri/_tricontour.py']

### Bug Description
[ENH]: Auto-detect bool arrays passed to contour()? ### Problem  I find myself fairly regularly calling ```python plt.contour(boolean_2d_array, levels=[.5], ...) ``` to draw the boundary line between True and False regions on a boolean 2d array.  Without `levels=[.5]`, one gets the default 8 lev

### Mechanism Source
contour() does not auto-detect boolean arrays — passing a bool array as Z causes confusing errors instead of coercing to numeric or raising a clear error

### Mechanism Steps
  1. User passes a boolean numpy array to plt.contour(X, Y, Z_bool)
  2. The contour code processes Z without checking its dtype
  3. Boolean arrays cause unexpected behavior in the level-finding and contouring algorithms
  4. The error message is confusing or the output is visually wrong because boolean values are not properly handled as contour levels
  5. Fix should add dtype checking in _process_args to detect and handle boolean arrays

### Justification
Bug type: missing_type_coercion
Mechanism outcome: contour() produces confusing errors or wrong output when given boolean arrays instead of numeric arrays
Trap: Adding the type check in contour.py but missing the same check in tri/_tricontour.py, or referencing undefined docstring variables

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): lib/matplotlib/contour.py, lib/matplotlib/tri/_tricontour.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## matplotlib__matplotlib-25479
Repo: matplotlib/matplotlib
Files: ['lib/matplotlib/cm.py', 'lib/matplotlib/colors.py']

### Bug Description
Confusing (broken?) colormap name handling Consider the following example in which one creates and registers a new colormap and attempt to use it with the `pyplot` interface.  ``` python from matplotlib import cm from matplotlib.colors import LinearSegmentedColormap import matplotlib.pyplot as plt i

### Mechanism Source
ColormapRegistry.register stores a colormap under the registry name but does not update the colormap's internal .name attribute to match

### Mechanism Steps
  1. User creates a colormap with name='original' and registers it as 'alias' via cm.register(cmap, name='alias')
  2. ColormapRegistry.register stores a copy of the colormap under key 'alias' but does not update the copy's .name attribute
  3. The stored colormap still has .name='original' internally
  4. When retrieved via cm['alias'], the returned colormap's .name is 'original', not 'alias'
  5. Equality checks and re-registration logic break because the name identity assumption is violated

### Justification
Bug type: name_identity_mismatch
Mechanism outcome: Registered colormap's .name attribute doesn't match its registry key, causing confusion in lookups and equality checks
Trap: Fixing only cm.py without updating colors.py Colormap class, or modifying the wrong method (get vs register)

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): lib/matplotlib/cm.py, lib/matplotlib/colors.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## matplotlib__matplotlib-25775
Repo: matplotlib/matplotlib
Files: ['lib/matplotlib/backends/backend_agg.py', 'lib/matplotlib/backends/backend_cairo.py', 'lib/matplotlib/text.py']

### Bug Description
[ENH]: Add get/set_antialiased to Text objects ### Problem  Currently, Text objects always retrieve their antialiasing state via the global rcParams["text.antialias"], unlike other artists for which this can be configured on a per-artist basis via `set_antialiased` (and read via `set_antialiased`).

### Mechanism Source
Text objects don't have get/set_antialiased methods, always inheriting antialiasing from rcParams with no per-object override

### Mechanism Steps
  1. User wants to disable antialiasing on specific text labels
  2. Text class in text.py has no antialiased property — it always uses rcParams['text.antialiased']
  3. Backend renderers (agg, cairo) read the antialiasing setting but Text doesn't expose it
  4. Fix: add get/set_antialiased to Text in text.py, update backend_agg.py and backend_cairo.py to use it

### Justification
Bug type: missing_property_on_text
Mechanism outcome: Cannot control antialiasing per Text object, only globally via rcParams
Trap: Adding the property to text.py without updating the backend renderers to read it

Evidence: Derived from reference patch diff analysis. The patch modifies
3 file(s): lib/matplotlib/backends/backend_agg.py, lib/matplotlib/backends/backend_cairo.py, lib/matplotlib/text.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## mwaskom__seaborn-3187
Repo: mwaskom/seaborn
Files: ['seaborn/_core/scales.py', 'seaborn/utils.py']

### Bug Description
Wrong legend values of large ranges As of 0.12.1, legends describing large numbers that were created using `ScalarFormatter` with an offset are formatted without their multiplicative offset value. An example: ```python import seaborn as sns import seaborn.objects as so  penguins = sns.load_data

### Mechanism Source
When ContinuousBase creates legend labels for large numeric ranges, the ScalarFormatter applies an offset (e.g., +1e8) that is not disabled, producing labels like '2.5' with a hidden offset instead of the actual value

### Mechanism Steps
  1. ContinuousBase._setup creates a matplotlib ScalarFormatter for legend label generation
  2. For large numeric ranges (e.g., 1e8 to 3e8), ScalarFormatter automatically enables offset notation
  3. The formatter produces labels like '1.0', '2.0', '3.0' with a hidden +1e8 offset
  4. Legend displays these offset-adjusted values without showing the offset, making labels incorrect
  5. The offset should be disabled via formatter.set_useOffset(False) or similar

### Justification
Bug type: formatter_offset_leak
Mechanism outcome: Legend values for large numeric ranges show wrong numbers (offset-adjusted values without the offset)
Trap: Trying to fix the formatting after the fact rather than disabling the offset at the ScalarFormatter initialization

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): seaborn/_core/scales.py, seaborn/utils.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## pydata__xarray-3095
Repo: pydata/xarray
Files: ['xarray/core/indexing.py', 'xarray/core/variable.py']

### Bug Description
REGRESSION: copy(deep=True) casts unicode indices to object Dataset.copy(deep=True) and DataArray.copy (deep=True/False) accidentally cast IndexVariable's with dtype='<U*' to object. Same applies to copy.copy() and copy.deepcopy().  This is a regression in xarray >= 0.12.2. xarray 0.12.1 and earli

### Mechanism Source
Dataset.copy(deep=True) casts unicode string indices to object dtype because the deep copy path uses np.array() which doesn't preserve pandas string dtype

### Mechanism Steps
  1. User calls ds.copy(deep=True) on a Dataset with unicode string coordinates
  2. The deep copy in variable.py calls np.array(data) to create a copy
  3. np.array() on a pandas Index with unicode dtype converts it to object dtype
  4. The copied Dataset has object-typed indices instead of unicode, breaking downstream operations
  5. Fix: use data.copy() instead of np.array(data) in variable.py, update indexing.py for consistency

### Justification
Bug type: deep_copy_casts_dtype
Mechanism outcome: copy(deep=True) silently converts unicode indices to object dtype
Trap: Fixing only variable.py without also fixing indexing.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): xarray/core/indexing.py, xarray/core/variable.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## pydata__xarray-3305
Repo: pydata/xarray
Files: ['xarray/core/dataset.py', 'xarray/core/variable.py']

### Bug Description
DataArray.quantile does not honor `keep_attrs` #### MCVE Code Sample <!-- In order for the maintainers to efficiently understand and prioritize issues, we ask you post a "Minimal, Complete and Verifiable Example" (MCVE): http://matthewrocklin.com/blog/work/2018/02/28/minimal-bug-reports -->  ```p

### Mechanism Source
Variable.quantile does not propagate the keep_attrs parameter, always returning a result with empty attrs regardless of the flag

### Mechanism Steps
  1. User calls DataArray.quantile(q=0.5, keep_attrs=True)
  2. The call dispatches to Variable.quantile which computes the quantile values
  3. Variable.quantile constructs a new Variable for the result but does not copy attrs from self
  4. The keep_attrs parameter is either not accepted or not used in the Variable.quantile implementation
  5. The returned DataArray has empty attrs={} even though keep_attrs=True was specified

### Justification
Bug type: attribute_propagation_missing
Mechanism outcome: DataArray.quantile() ignores keep_attrs=True and always returns result with empty attributes
Trap: Adding keep_attrs to the Dataset level but not propagating it down to Variable.quantile

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): xarray/core/dataset.py, xarray/core/variable.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## pydata__xarray-3993
Repo: pydata/xarray
Files: ['xarray/core/dataarray.py', 'xarray/core/dataset.py']

### Bug Description
DataArray.integrate has a 'dim' arg, but Dataset.integrate has a 'coord' arg This is just a minor gripe but I think it should be fixed.  The API syntax is inconsistent: ```python ds.differentiate(coord='x') da.differentiate(coord='x') ds.integrate(coord='x') da.integrate(dim='x')   # why dim?

### Mechanism Source
DataArray.integrate has a 'dim' argument but Dataset.integrate has a 'coord' argument for the same operation, creating inconsistent API

### Mechanism Steps
  1. User calls ds.integrate('x') following DataArray API which uses 'dim' parameter
  2. Dataset.integrate expects 'coord' parameter instead of 'dim'
  3. The inconsistency between DataArray and Dataset APIs confuses users
  4. Fix: harmonize both to accept 'coord' in dataarray.py and dataset.py, with deprecation warning for 'dim'

### Justification
Bug type: inconsistent_api_naming
Mechanism outcome: API inconsistency between DataArray.integrate(dim=) and Dataset.integrate(coord=)
Trap: Fixing only one of dataarray.py or dataset.py without the other

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): xarray/core/dataarray.py, xarray/core/dataset.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## pydata__xarray-6938
Repo: pydata/xarray
Files: ['xarray/core/dataset.py', 'xarray/core/variable.py']

### Bug Description
`.swap_dims()` can modify original object ### What happened?  This is kind of a convoluted example, but something I ran into. It appears that in certain cases `.swap_dims()` can modify the original object, here the `.dims` of a data variable that was swapped into being a dimension coordinate varia

### Mechanism Source
swap_dims modifies the internal variable objects of the original Dataset instead of making copies, causing the original object to be mutated

### Mechanism Steps
  1. User calls ds.swap_dims({'x': 'y'}) expecting ds to remain unchanged
  2. swap_dims creates new index variables but reuses references to the original Dataset's internal Variable objects
  3. When the method modifies the variable's dims attribute to reflect the swap, it mutates the original object in place
  4. After swap_dims returns, the original Dataset's variables have been silently modified
  5. The fix requires copying variables before modifying their dims via to_index_variable or similar

### Justification
Bug type: shared_reference_mutation
Mechanism outcome: swap_dims mutates the original Dataset object instead of returning an independent copy
Trap: Fixing only dataset.py without ensuring Variable.to_index_variable makes a proper copy, or breaking the copy semantics

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): xarray/core/dataset.py, xarray/core/variable.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## pydata__xarray-6992
Repo: pydata/xarray
Files: ['xarray/core/dataset.py', 'xarray/core/indexes.py']

### Bug Description
index refactor: more `_coord_names` than `_variables` on Dataset ### What happened?  `xr.core.dataset.DataVariables` assumes that everything that is in `ds._dataset._variables` and not in `self._dataset._coord_names` is a "data variable". However, since the index refactor we can end up with more `_c

### Mechanism Source
After index refactoring, Dataset can end up with more _coord_names than _variables, causing DataVariables to report negative length or crash

### Mechanism Steps
  1. Operations like drop_vars or reset_index modify _variables but don't consistently update _coord_names
  2. This leaves orphan entries in _coord_names that reference variables that no longer exist
  3. DataVariables.__len__ computes len(_variables) - len(_coord_names) which goes negative
  4. Fix: ensure _coord_names is cleaned up in dataset.py and indexes.py when variables are removed

### Justification
Bug type: coord_variable_set_inconsistency
Mechanism outcome: Dataset DataVariables shows wrong length or crashes after index operations
Trap: Fixing only dataset.py without also fixing indexes.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): xarray/core/dataset.py, xarray/core/indexes.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## pylint-dev__pylint-4551
Repo: pylint-dev/pylint
Files: ['pylint/pyreverse/diagrams.py', 'pylint/pyreverse/inspector.py', 'pylint/pyreverse/utils.py', 'pylint/pyreverse/writer.py']

### Bug Description
Use Python type hints for UML generation It seems that pyreverse does not read python type hints (as defined by [PEP 484](https://www.python.org/dev/peps/pep-0484/)), and this does not help when you use `None` as a default value :  ### Code example ``` class C(object):     def __init__(self, a:

### Mechanism Source
pyreverse does not read PEP 484 type hints for UML diagram generation, only looking at docstrings and assignments

### Mechanism Steps
  1. User runs pyreverse on code using PEP 484 type hints (def foo(x: int) -> str)
  2. pyreverse's inspector.py only reads types from docstrings and runtime introspection
  3. Type annotations in function signatures and variable annotations are ignored
  4. UML diagrams show attributes without types or with wrong types
  5. Fix: update inspector.py, diagrams.py, utils.py, and writer.py to extract and render type hints

### Justification
Bug type: type_hints_not_read
Mechanism outcome: pyreverse UML diagrams don't show type information from PEP 484 annotations
Trap: Updating only one of the four files without propagating type info through the full pipeline

Evidence: Derived from reference patch diff analysis. The patch modifies
4 file(s): pylint/pyreverse/diagrams.py, pylint/pyreverse/inspector.py, pylint/pyreverse/utils.py, pylint/pyreverse/writer.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## pylint-dev__pylint-4604
Repo: pylint-dev/pylint
Files: ['pylint/checkers/variables.py', 'pylint/constants.py']

### Bug Description
unused-import false positive for a module used in a type comment ### Steps to reproduce  ```python """Docstring."""  import abc from abc import ABC  X = ...  # type: abc.ABC Y = ...  # type: ABC ```  ### Current behavior  ``` ************* Module a /tmp/a.py:3:0: W0611: Unused import

### Mechanism Source
The unused-import checker does not recognize imports that are only used in PEP 484 type comments (# type: ModuleName)

### Mechanism Steps
  1. User imports a module that is only referenced in a type comment: '# type: SomeModule'
  2. pylint's VariablesChecker scans the AST for import usage but does not parse type comments
  3. The import appears unused because no AST node references the imported name in executable code
  4. pylint reports W0611 unused-import as a false positive
  5. Fix requires adding type comment scanning in the variables checker, potentially with an IS_PYPY guard in constants.py

### Justification
Bug type: missing_type_comment_handling
Mechanism outcome: False positive unused-import warning for modules that are only used in type comments
Trap: Adding a constant like IS_PYPY to constants.py without actually defining it, or not properly parsing type comments from the source

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): pylint/checkers/variables.py, pylint/constants.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## pylint-dev__pylint-4661
Repo: pylint-dev/pylint
Files: ['pylint/config/__init__.py', 'setup.cfg']

### Bug Description
Make pylint XDG Base Directory Specification compliant I have this really annoying `.pylint.d` directory in my home folder. From what I can tell (I don't do C or C++), this directory is storing data.   The problem with this is, quite simply, that data storage has a designated spot. The `$HOME/.loc

### Mechanism Source
Pylint stores its data in ~/.pylint.d instead of following the XDG Base Directory Specification (~/.local/share/pylint or $XDG_DATA_HOME/pylint)

### Mechanism Steps
  1. PYLINT_HOME is hardcoded to os.path.join(USER_HOME, '.pylint.d') in config/__init__.py
  2. This creates a dotfile directory directly in the user's home folder, violating XDG conventions
  3. Users cannot control the location via standard XDG environment variables like XDG_DATA_HOME
  4. Fix requires checking XDG_DATA_HOME first, falling back to ~/.local/share/pylint, with backward compatibility for existing .pylint.d
  5. setup.cfg may need updating if it references the old path

### Justification
Bug type: xdg_noncompliance
Mechanism outcome: Pylint creates .pylint.d in home directory instead of following XDG Base Directory Specification
Trap: Using an external module like appdirs instead of implementing XDG logic directly, which introduces an unavailable dependency

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): pylint/config/__init__.py, setup.cfg.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## pylint-dev__pylint-6386
Repo: pylint-dev/pylint
Files: ['pylint/config/argument.py', 'pylint/config/arguments_manager.py', 'pylint/config/utils.py', 'pylint/lint/base_options.py']

### Bug Description
Argument expected for short verbose option ### Bug description  The short option of the `verbose` option expects an argument. Also, the help message for the `verbose` option suggests a value `VERBOSE` should be provided.  The long option works ok & doesn't expect an argument: `pylint mytest.py

### Mechanism Source
The short -v option for --verbose unexpectedly requires an argument because the argument configuration treats it as a store value instead of store_true

### Mechanism Steps
  1. User runs pylint -v (short verbose flag)
  2. argparse expects an argument for -v because it's configured with store action instead of store_true
  3. The argument parser consumes the next token as the value for -v, breaking the command
  4. Fix: update argument configuration in argument.py, arguments_manager.py, utils.py, and base_options.py to use store_true for verbose

### Justification
Bug type: short_option_requires_argument
Mechanism outcome: pylint -v requires an unexpected argument instead of acting as a boolean flag
Trap: Fixing only base_options.py without updating the argument type conversion in argument.py and utils.py

Evidence: Derived from reference patch diff analysis. The patch modifies
4 file(s): pylint/config/argument.py, pylint/config/arguments_manager.py, pylint/config/utils.py, pylint/lint/base_options.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## pylint-dev__pylint-6528
Repo: pylint-dev/pylint
Files: ['pylint/lint/expand_modules.py', 'pylint/lint/pylinter.py']

### Bug Description
Pylint does not respect ignores in `--recursive=y` mode ### Bug description  Pylint does not respect the `--ignore`, `--ignore-paths`, or `--ignore-patterns` setting when running in recursive mode. This contradicts the documentation and seriously compromises the usefulness of recursive mode.  ##

### Mechanism Source
In recursive mode (--recursive=y), expand_modules only checks ignore patterns against the top-level entry, not against discovered submodules and files

### Mechanism Steps
  1. User runs pylint with --recursive=y --ignore=tests on a package directory
  2. expand_modules iterates the top-level files_or_modules and checks ignore patterns
  3. When recursing into subdirectories, it discovers files like package/tests/test_foo.py
  4. The ignore check only applies to the basename of the top-level entry, not to discovered files during recursion
  5. Files in ignored directories (like tests/) are still linted despite matching the ignore pattern

### Justification
Bug type: ignore_not_applied_recursively
Mechanism outcome: pylint --recursive=y does not respect --ignore, --ignore-patterns, or --ignore-paths for files discovered during directory recursion
Trap: Adding ignore checks only in pylinter.py without also fixing expand_modules.py, or checking only basename instead of full path

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): pylint/lint/expand_modules.py, pylint/lint/pylinter.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## pylint-dev__pylint-8898
Repo: pylint-dev/pylint
Files: ['pylint/config/argument.py', 'pylint/utils/__init__.py', 'pylint/utils/utils.py']

### Bug Description
bad-names-rgxs mangles regular expressions with commas ### Bug description  Since pylint splits on commas in this option, instead of taking a list of strings, if there are any commas in the regular expression, the result is mangled before being parsed. The config below demonstrates this clearly by

### Mechanism Source
bad-names-rgxs option splits regular expressions on commas, breaking patterns that contain commas (e.g., quantifiers like {1,2})

### Mechanism Steps
  1. User sets bad-names-rgxs with a pattern containing commas, e.g., '[a-z]{1,2}'
  2. pylint's option parsing splits the value on commas to get individual patterns
  3. The regex '{1,2}' is split into '{1' and '2}' — both invalid patterns
  4. pylint crashes with re.error or silently uses broken patterns
  5. Fix: update argument.py and utils.py to use proper regex-aware splitting that respects curly braces

### Justification
Bug type: regex_split_mangles_pattern
Mechanism outcome: bad-names-rgxs with comma-containing regex patterns crashes or produces wrong results
Trap: Fixing only argument.py without also updating utils/__init__.py and utils/utils.py

Evidence: Derived from reference patch diff analysis. The patch modifies
3 file(s): pylint/config/argument.py, pylint/utils/__init__.py, pylint/utils/utils.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## pytest-dev__pytest-5840
Repo: pytest-dev/pytest
Files: ['src/_pytest/config/__init__.py', 'src/_pytest/pathlib.py']

### Bug Description
5.1.2 ImportError while loading conftest (windows import folder casing issues) 5.1.1 works fine. after upgrade to 5.1.2, the path was converted to lower case ``` Installing collected packages: pytest   Found existing installation: pytest 5.1.1     Uninstalling pytest-5.1.1:       Successfully u

### Mechanism Source
On Windows, pytest's conftest discovery fails when folder casing in the path differs from the filesystem because path comparison is case-sensitive

### Mechanism Steps
  1. User's project path has different casing than what Windows reports (e.g., 'Users' vs 'users')
  2. pytest's conftest loading in config/__init__.py compares paths case-sensitively
  3. pathlib.py path resolution doesn't normalize casing on Windows
  4. conftest files are not found because the path doesn't match exactly
  5. Fix: use case-insensitive path comparison in config/__init__.py and normalize paths in pathlib.py

### Justification
Bug type: case_sensitivity_in_path_comparison
Mechanism outcome: ImportError while loading conftest on Windows when folder casing differs
Trap: Fixing only config/__init__.py without also fixing pathlib.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): src/_pytest/config/__init__.py, src/_pytest/pathlib.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## pytest-dev__pytest-8399
Repo: pytest-dev/pytest
Files: ['src/_pytest/python.py', 'src/_pytest/unittest.py']

### Bug Description
Starting v6.2.0, unittest setUpClass fixtures are no longer "private" <!-- Thanks for submitting an issue!  Quick check-list while reporting bugs: --> Minimal example: ``` import unittest  class Tests(unittest.TestCase):     @classmethod     def setUpClass(cls):         pass      def t

### Mechanism Source
Starting in pytest 6.2.0, unittest setUpClass fixtures are no longer treated as private, making them visible in --fixtures output and tab completion

### Mechanism Steps
  1. User runs pytest --fixtures or uses tab completion
  2. setUpClass and tearDownClass from unittest TestCase subclasses appear in the fixture list
  3. In pytest <6.2.0 these were hidden as private fixtures
  4. The change in python.py or unittest.py made them public by not marking them correctly
  5. Fix: restore private marking in python.py and unittest.py for unittest lifecycle methods

### Justification
Bug type: fixture_visibility_regression
Mechanism outcome: unittest setUpClass/tearDownClass show up as public fixtures in pytest 6.2.0+
Trap: Fixing only python.py without also fixing unittest.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): src/_pytest/python.py, src/_pytest/unittest.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## scikit-learn__scikit-learn-12682
Repo: scikit-learn/scikit-learn
Files: ['examples/decomposition/plot_sparse_coding.py', 'sklearn/decomposition/dict_learning.py']

### Bug Description
`SparseCoder` doesn't expose `max_iter` for `Lasso` `SparseCoder` uses `Lasso` if the algorithm is set to `lasso_cd`. It sets some of the `Lasso`'s parameters, but not `max_iter`, and that by default is 1000. This results in a warning in `examples/decomposition/plot_sparse_coding.py` complaining tha

### Mechanism Source
SparseCoder doesn't expose max_iter parameter for the Lasso algorithm, so users can't control iteration limits when using lasso_cd

### Mechanism Steps
  1. User creates SparseCoder with algorithm='lasso_cd' and wants to set max_iter
  2. SparseCoder.__init__ doesn't accept max_iter parameter
  3. The internal Lasso call in dict_learning.py uses a hardcoded default for max_iter
  4. User cannot control convergence behavior of the sparse coding
  5. Fix: add max_iter parameter to SparseCoder and pass it through in dict_learning.py, update example

### Justification
Bug type: missing_parameter_passthrough
Mechanism outcome: Cannot set max_iter when using SparseCoder with lasso_cd algorithm
Trap: Adding the parameter to SparseCoder without also updating the internal dict_learning.py call

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): examples/decomposition/plot_sparse_coding.py, sklearn/decomposition/dict_learning.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## scikit-learn__scikit-learn-25102
Repo: scikit-learn/scikit-learn
Files: ['sklearn/base.py', 'sklearn/feature_selection/_base.py']

### Bug Description
Preserving dtypes for DataFrame output by transformers that do not modify the input values ### Describe the workflow you want to enable  It would be nice to optionally preserve the dtypes of the input using pandas output for transformers #72. Dtypes can contain information relevant for later step

### Mechanism Source
Transformers that do not modify input values (like feature selectors) do not preserve DataFrame dtypes in their output when set_output(transform='pandas') is used

### Mechanism Steps
  1. User enables pandas output via set_output(transform='pandas') on a feature selector (e.g., SelectKBest)
  2. The transformer's transform() method selects a subset of features without modifying their values
  3. The output construction in _base.py converts the selected features to a new DataFrame
  4. During construction, the original dtype information is lost — all columns become float64
  5. Fix requires propagating dtype info from the input DataFrame to the output DataFrame in the base transformer

### Justification
Bug type: dtype_not_preserved
Mechanism outcome: Feature selectors with pandas output lose dtype information — all output columns become float64 even if input had int, bool, or categorical dtypes
Trap: Producing an empty or minimal patch, or fixing only base.py without also updating feature_selection/_base.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): sklearn/base.py, sklearn/feature_selection/_base.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sphinx-doc__sphinx-10673
Repo: sphinx-doc/sphinx
Files: ['sphinx/directives/other.py', 'sphinx/environment/adapters/toctree.py', 'sphinx/environment/collectors/toctree.py']

### Bug Description
toctree contains reference to nonexisting document 'genindex', 'modindex', 'search' **Is your feature request related to a problem? Please describe.** A lot of users try to add the following links to the toctree: ``` * :ref:`genindex` * :ref:`modindex` * :ref:`search` ``` like this: ``` ..

### Mechanism Source
toctree warns about nonexisting documents when referencing special pages like 'genindex', 'modindex', 'search' because they're not in the document inventory

### Mechanism Steps
  1. User adds genindex, modindex, or search to a toctree directive
  2. Sphinx processes the toctree and checks all entries against known documents
  3. Special pages are generated dynamically and aren't in the regular document list
  4. Warning 'toctree contains reference to nonexisting document' is emitted
  5. Fix: update toctree processing in directives/other.py, environment/adapters/toctree.py, and collectors/toctree.py to recognize special pages

### Justification
Bug type: special_pages_in_toctree_warning
Mechanism outcome: False warnings about nonexisting documents when toctree references genindex/modindex/search
Trap: Fixing only one of the three toctree-related files without the others

Evidence: Derived from reference patch diff analysis. The patch modifies
3 file(s): sphinx/directives/other.py, sphinx/environment/adapters/toctree.py, sphinx/environment/collectors/toctree.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sphinx-doc__sphinx-7462
Repo: sphinx-doc/sphinx
Files: ['sphinx/domains/python.py', 'sphinx/pycode/ast.py']

### Bug Description
`IndexError: pop from empty list` for empty tuple type annotation **Describe the bug** Following notation for empty tuple from [this mypy issue](https://github.com/python/mypy/issues/4211) like ```python from typing import Tuple  def foo() -> Tuple[()]: 	"""Sample text."""     return () ```

### Mechanism Source
The unparse function in ast.py does not handle ast.Tuple nodes, so empty tuple annotations like Tuple[()] crash with IndexError

### Mechanism Steps
  1. User writes a type annotation with an empty tuple: -> Tuple[()]
  2. Sphinx parses this annotation into an AST containing an ast.Tuple node with empty elements
  3. The unparse function in sphinx/pycode/ast.py has no handler for ast.Tuple
  4. The code falls through to a generic handler that tries to access elements of the empty tuple
  5. IndexError: pop from empty list is raised during signature rendering

### Justification
Bug type: missing_ast_node_handler
Mechanism outcome: Sphinx crashes with IndexError when documenting functions with empty tuple type annotations
Trap: Breaking tuple unpacking logic by not handling the empty case, or causing AttributeError in the AST traversal

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): sphinx/domains/python.py, sphinx/pycode/ast.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sphinx-doc__sphinx-7590
Repo: sphinx-doc/sphinx
Files: ['sphinx/domains/c.py', 'sphinx/domains/cpp.py', 'sphinx/util/cfamily.py']

### Bug Description
C++ User Defined Literals not supported The code as below  ```cpp namespace units::si {  inline constexpr auto planck_constant = 6.62607015e-34q_J * 1q_s;  } ```  causes the following error:  ``` WARNING: Invalid definition: Expected end of definition. [error at 58] [build]   constexpr

### Mechanism Source
C++ domain does not support user-defined literals (UDLs), causing documentation of code using UDLs to fail

### Mechanism Steps
  1. User documents C++ code that uses user-defined literals (e.g., operator""_km)
  2. Sphinx's C++ domain parser in cpp.py doesn't recognize UDL syntax
  3. The parser fails or produces incorrect documentation for UDL operators
  4. The shared C/C++ family parser in cfamily.py also needs UDL support
  5. Fix: add UDL parsing to cpp.py, c.py, and cfamily.py

### Justification
Bug type: missing_language_feature
Mechanism outcome: C++ user-defined literals cannot be documented with Sphinx
Trap: Fixing only cpp.py without also updating cfamily.py and c.py

Evidence: Derived from reference patch diff analysis. The patch modifies
3 file(s): sphinx/domains/c.py, sphinx/domains/cpp.py, sphinx/util/cfamily.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sphinx-doc__sphinx-8120
Repo: sphinx-doc/sphinx
Files: ['sphinx/application.py', 'sphinx/locale/__init__.py']

### Bug Description
locale/<language>/LC_MESSAGES/sphinx.po translation ignored **Describe the bug** I read [1] as it should be possible to add a file ``locale/<language>/LC_MESSAGES/sphinx.mo`` to the source dir (same dir as the ``Makefile``) and through that change translations or add additional translation to <lang

### Mechanism Source
Sphinx application initializes locale catalog after extensions are loaded, so custom locale/translation directories specified via locale_dirs config are not picked up

### Mechanism Steps
  1. User provides custom translation file in locale/<language>/LC_MESSAGES/sphinx.po
  2. Sphinx.__init__ initializes the application and loads extensions
  3. The locale catalog initialization happens too late — after extensions have already been loaded
  4. Custom translations in locale_dirs are not registered when the translation proxy objects are created
  5. Translated strings fall back to English defaults because the custom .po file was never loaded

### Justification
Bug type: locale_initialization_order
Mechanism outcome: Custom sphinx.po translations in locale directories are silently ignored
Trap: Fixing the import order in locale/__init__.py instead of fixing the initialization order in application.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): sphinx/application.py, sphinx/locale/__init__.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sphinx-doc__sphinx-8548
Repo: sphinx-doc/sphinx
Files: ['sphinx/ext/autodoc/__init__.py', 'sphinx/ext/autodoc/importer.py']

### Bug Description
autodoc inherited-members won't work for inherited attributes (data members). autodoc searches for a cached docstring using (namespace, attrname) as search-key, but doesn't check for baseclass-namespace.  --- - Bitbucket: https://bitbucket.org/birkenfeld/sphinx/issue/741 - Originally reported by: An

### Mechanism Source
autodoc's get_object_members uses __dict__ to find directly-defined members but misses inherited data attributes (non-method members) when :inherited-members: is set

### Mechanism Steps
  1. User documents a class with :inherited-members: option that inherits data attributes from a parent class
  2. get_object_members checks subject.__dict__ for directly-defined members
  3. Inherited data attributes (class variables, descriptors) exist in parent.__dict__ but not in subject.__dict__
  4. autodoc searches for cached docstrings to find inherited members but data attributes may not have docstrings
  5. Inherited data attributes are silently omitted from the documentation

### Justification
Bug type: inherited_member_resolution_failure
Mechanism outcome: autodoc :inherited-members: does not document inherited data attributes (only inherited methods work)
Trap: Fixing only __init__.py without also updating importer.py, or changing the member ordering incorrectly

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): sphinx/ext/autodoc/__init__.py, sphinx/ext/autodoc/importer.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sphinx-doc__sphinx-8551
Repo: sphinx-doc/sphinx
Files: ['sphinx/domains/python.py', 'sphinx/util/docfields.py']

### Bug Description
:type: and :rtype: gives false ambiguous class lookup warnings **Describe the bug** The implicit xrefs created by the info fields ``:type:`` and ``:rtype:`` seems to do lookup differently than explicit xref roles. For unqualified names it seems like they search for the name in every (sub)module ins

### Mechanism Source
When docfields creates cross-references for :type: and :rtype: annotations, it does not pass the py:module context to the pending_xref node

### Mechanism Steps
  1. User writes :type: or :rtype: with an unqualified class name in a module's docstring
  2. DocFieldTransformer.transform calls TypedField.make_field which calls make_xref to create pending_xref nodes
  3. PyXrefMixin.make_xref creates the pending_xref node but does not set the py:module attribute on it
  4. During reference resolution, the resolver searches all modules for the unqualified name instead of starting from the current module
  5. Multiple matches are found across different modules, triggering a false 'ambiguous class lookup' warning

### Justification
Bug type: missing_context_propagation
Mechanism outcome: False 'ambiguous class lookup' warnings when using :type: and :rtype: with unqualified class names
Trap: Fixing only python.py without also fixing docfields.py, or adding module context in the wrong location in the xref creation chain

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): sphinx/domains/python.py, sphinx/util/docfields.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sphinx-doc__sphinx-8593
Repo: sphinx-doc/sphinx
Files: ['sphinx/ext/autodoc/__init__.py', 'sphinx/ext/autodoc/importer.py']

### Bug Description
autodoc: `:meta public:` does not effect to variables **Describe the bug** autodoc: `:meta public:` does not effect to variables.  **To Reproduce**  ``` # example.py _foo = None  #: :meta public: ``` ``` # index.rst .. automodule:: example    :members: ```  I expect `_foo` is shown on

### Mechanism Source
autodoc's :meta public: directive does not work for module-level variables because variable processing doesn't check for meta directives

### Mechanism Steps
  1. User adds ':meta public:' comment to a private module variable (_var)
  2. autodoc processes the module and sees the underscore-prefixed name
  3. The variable documenter in __init__.py doesn't check for :meta public: override
  4. The variable is excluded from documentation despite the explicit :meta public: directive
  5. Fix: update autodoc/__init__.py and importer.py to check meta directives for variables

### Justification
Bug type: meta_directive_not_applied
Mechanism outcome: :meta public: directive is ignored for module-level variables, they remain undocumented
Trap: Fixing only __init__.py without also updating importer.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): sphinx/ext/autodoc/__init__.py, sphinx/ext/autodoc/importer.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sphinx-doc__sphinx-9461
Repo: sphinx-doc/sphinx
Files: ['sphinx/domains/python.py', 'sphinx/ext/autodoc/__init__.py', 'sphinx/util/inspect.py']

### Bug Description
Methods decorated with @classmethod and @property do not get documented. **EDIT:** The problem seems to be that `type(BaseClass.baseclass_property)` returns `property`, thus sphinx can just lookup `BaseClass.baseclass_property.__doc__`. However, `type(BaseClass.baseclass_class_property)` returns the

### Mechanism Source
Methods decorated with both @classmethod and @property are not documented because autodoc doesn't recognize the combined decorator pattern

### Mechanism Steps
  1. User defines a method decorated with both @classmethod and @property
  2. autodoc's type inspection in inspect.py doesn't recognize classmethod_descriptor type
  3. The method is not classified as either a classmethod or property
  4. It falls through without being documented
  5. Fix: update inspect.py to detect classmethod descriptors, update autodoc/__init__.py and python.py domain

### Justification
Bug type: classmethod_property_not_documented
Mechanism outcome: Methods with @classmethod @property combined decorator are silently excluded from docs
Trap: Fixing only inspect.py without updating autodoc and the python domain

Evidence: Derived from reference patch diff analysis. The patch modifies
3 file(s): sphinx/domains/python.py, sphinx/ext/autodoc/__init__.py, sphinx/util/inspect.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sympy__sympy-13091
Repo: sympy/sympy
Files: ['sympy/core/basic.py', 'sympy/core/exprtools.py', 'sympy/core/numbers.py', 'sympy/geometry/entity.py', 'sympy/physics/optics/medium.py', 'sympy/physics/vector/dyadic.py', 'sympy/physics/vector/frame.py', 'sympy/physics/vector/vector.py', 'sympy/polys/agca/modules.py', 'sympy/polys/domains/domain.py', 'sympy/polys/domains/expressiondomain.py', 'sympy/polys/domains/pythonrational.py', 'sympy/polys/domains/quotientring.py', 'sympy/polys/fields.py', 'sympy/polys/monomials.py', 'sympy/polys/polyclasses.py', 'sympy/polys/polytools.py', 'sympy/polys/rings.py', 'sympy/polys/rootoftools.py', 'sympy/tensor/array/ndim_array.py', 'sympy/utilities/enumerative.py']

### Bug Description
Return NotImplemented, not False, upon rich comparison with unknown type Comparison methods should ideally return ``NotImplemented`` when unable to make sense of the arguments. This way, the comparison is delegated to the reflected method on the other object, which might support the comparison (see

### Mechanism Source
Rich comparison methods (__eq__, __ne__, etc.) return False instead of NotImplemented when comparing with unknown types, preventing Python's comparison delegation protocol

### Mechanism Steps
  1. User compares a SymPy object with a non-SymPy type (e.g., numpy array)
  2. The SymPy object's __eq__ returns False instead of NotImplemented
  3. Python doesn't try the other operand's __eq__ because it got a concrete answer
  4. This breaks interoperability with numpy and other libraries that expect comparison delegation
  5. Fix: change return False to return NotImplemented across 21 files in core, geometry, physics, polys, etc.

### Justification
Bug type: wrong_comparison_return_type
Mechanism outcome: SymPy objects don't interoperate correctly with numpy and other libraries in comparisons
Trap: Fixing only a few files instead of all 21 that have the same pattern

Evidence: Derived from reference patch diff analysis. The patch modifies
21 file(s): sympy/core/basic.py, sympy/core/exprtools.py, sympy/core/numbers.py, sympy/geometry/entity.py, sympy/physics/optics/medium.py, sympy/physics/vector/dyadic.py, sympy/physics/vector/frame.py, sympy/physics/vector/vector.py, sympy/polys/agca/modules.py, sympy/polys/domains/domain.py, sympy/polys/domains/expressiondomain.py, sympy/polys/domains/pythonrational.py, sympy/polys/domains/quotientring.py, sympy/polys/fields.py, sympy/polys/monomials.py, sympy/polys/polyclasses.py, sympy/polys/polytools.py, sympy/polys/rings.py, sympy/polys/rootoftools.py, sympy/tensor/array/ndim_array.py, sympy/utilities/enumerative.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sympy__sympy-13877
Repo: sympy/sympy
Files: ['sympy/matrices/matrices.py', 'sympy/utilities/randtest.py']

### Bug Description
Matrix determinant raises Invalid NaN comparison with particular symbolic entries     >>> from sympy import *     >>> from sympy.abc import a     >>> f = lambda n: det(Matrix([[i + a*j for i in range(n)] for j in range(n)]))     >>> f(1)     0     >>> f(2)     -a     >>> f(3)     2*a*(a + 2)

### Mechanism Source
Matrix determinant computation raises 'Invalid NaN comparison' when matrix entries produce symbolic NaN during Gaussian elimination

### Mechanism Steps
  1. User computes determinant of a matrix with particular symbolic entries
  2. Gaussian elimination produces intermediate NaN values during row reduction
  3. The code compares these NaN values (e.g., for pivot selection), raising TypeError
  4. Fix: update comparison logic in matrices.py to handle NaN, and fix the random testing utility in randtest.py

### Justification
Bug type: nan_comparison_in_determinant
Mechanism outcome: Matrix.det() raises 'Invalid NaN comparison' TypeError for certain symbolic matrices
Trap: Fixing only matrices.py without also fixing the test utilities in randtest.py

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): sympy/matrices/matrices.py, sympy/utilities/randtest.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sympy__sympy-14248
Repo: sympy/sympy
Files: ['sympy/printing/latex.py', 'sympy/printing/pretty/pretty.py', 'sympy/printing/str.py']

### Bug Description
The difference of MatrixSymbols prints as a sum with (-1) coefficient Internally, differences like a-b are represented as the sum of a with `(-1)*b`, but they are supposed to print like a-b. This does not happen with MatrixSymbols. I tried three printers: str, pretty, and latex:  ``` from sympy im

### Mechanism Source
Printers (str, LaTeX, pretty) display MatrixSymbol subtraction as addition with (-1) coefficient instead of using minus sign

### Mechanism Steps
  1. User computes A - B where A and B are MatrixSymbols
  2. Internally SymPy represents this as A + (-1)*B (MatAdd with negative coefficient)
  3. The str printer in str.py doesn't special-case negative MatMul coefficients
  4. LaTeX and pretty printers have the same issue
  5. Fix: update _print_MatAdd in str.py, latex.py, and pretty.py to detect and render negative coefficients as subtraction

### Justification
Bug type: printer_shows_negative_coefficient
Mechanism outcome: MatrixSymbol subtraction displays as 'A + (-1)*B' instead of 'A - B'
Trap: Fixing only one printer without fixing all three (str, latex, pretty)

Evidence: Derived from reference patch diff analysis. The patch modifies
3 file(s): sympy/printing/latex.py, sympy/printing/pretty/pretty.py, sympy/printing/str.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sympy__sympy-16597
Repo: sympy/sympy
Files: ['sympy/assumptions/ask.py', 'sympy/assumptions/ask_generated.py', 'sympy/core/assumptions.py', 'sympy/core/power.py', 'sympy/printing/tree.py', 'sympy/tensor/indexed.py']

### Bug Description
a.is_even does not imply a.is_finite I'm not sure what the right answer is here: ```julia In [1]: m = Symbol('m', even=True)                                                                                                               In [2]: m.is_finite

### Mechanism Source
Symbol.is_even does not imply Symbol.is_finite, causing incorrect logical deductions in the assumption system

### Mechanism Steps
  1. User creates Symbol('m', even=True) and checks m.is_finite
  2. The assumption system in core/assumptions.py doesn't have the even→finite implication
  3. m.is_finite returns None instead of True
  4. This propagates to incorrect results in power.py and other modules that check finiteness
  5. Fix: add even→finite implication in assumptions.py and ask_generated.py, update power.py, tree.py, and indexed.py

### Justification
Bug type: assumption_implication_gap
Mechanism outcome: Symbol with even=True has is_finite=None instead of True, causing wrong simplification results
Trap: Adding the implication in only one place without updating all files that depend on it

Evidence: Derived from reference patch diff analysis. The patch modifies
6 file(s): sympy/assumptions/ask.py, sympy/assumptions/ask_generated.py, sympy/core/assumptions.py, sympy/core/power.py, sympy/printing/tree.py, sympy/tensor/indexed.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sympy__sympy-17318
Repo: sympy/sympy
Files: ['sympy/simplify/radsimp.py', 'sympy/simplify/sqrtdenest.py']

### Bug Description
sqrtdenest raises IndexError ``` >>> sqrtdenest((3 - sqrt(2)*sqrt(4 + 3*I) + 3*I)/2) Traceback (most recent call last):   File "<stdin>", line 1, in <module>   File "sympy\simplify\sqrtdenest.py", line 132, in sqrtdenest     z = _sqrtdenest0(expr)   File "sympy\simplify\sqrtdenest.py", line 24

### Mechanism Source
split_surds crashes with IndexError when called with expressions containing complex surds because _split_gcd receives an empty list

### Mechanism Steps
  1. sqrtdenest is called with an expression containing complex terms like sqrt(4 + 3*I)
  2. The denesting algorithm calls split_surds to decompose the expression
  3. split_surds filters for terms where x[1].is_Pow, but complex surds may not match this pattern or produce empty surd lists
  4. _split_gcd is called with an empty list or list of non-rational elements, causing IndexError: pop from empty list
  5. The fix must add guards for empty surd lists and handle non-rational square root arguments

### Justification
Bug type: index_error_on_edge_case
Mechanism outcome: sqrtdenest raises IndexError when given expressions with complex square root arguments
Trap: Adding a try/except around the IndexError instead of fixing the root cause in split_surds' handling of complex arguments

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): sympy/simplify/radsimp.py, sympy/simplify/sqrtdenest.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sympy__sympy-19783
Repo: sympy/sympy
Files: ['sympy/physics/quantum/dagger.py', 'sympy/physics/quantum/operator.py']

### Bug Description
Dagger() * IdentityOperator() is not simplified As discussed on the mailing list the following does not work. ``` from sympy.physics.quantum.dagger import Dagger from sympy.physics.quantum.operator import Operator from sympy.physics.quantum import IdentityOperator A = Operators('A') Identity =

### Mechanism Source
Operator.__mul__ handles IdentityOperator on the right side but there is no corresponding __rmul__ or handling in Dagger for IdentityOperator multiplication

### Mechanism Steps
  1. User computes Dagger(A) * IdentityOperator() where A is an Operator
  2. Dagger(A).__mul__ is called but Dagger extends adjoint (from core), not Operator, so it lacks the IdentityOperator check
  3. The multiplication falls through to sympy's generic Mul, which does not simplify quantum operator identity products
  4. The result is an unsimplified Dagger(A) * I expression instead of just Dagger(A)
  5. Fix requires adding __mul__ handling for IdentityOperator in Dagger or adding IdentityOperator.__rmul__

### Justification
Bug type: missing_identity_simplification
Mechanism outcome: Dagger(A) * IdentityOperator() is not simplified and produces incorrect symbolic expressions
Trap: Editing complexes.py instead of operator.py/dagger.py, or creating infinite recursion by having __mul__ and __rmul__ call each other

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): sympy/physics/quantum/dagger.py, sympy/physics/quantum/operator.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sympy__sympy-20438
Repo: sympy/sympy
Files: ['sympy/core/relational.py', 'sympy/sets/handlers/comparison.py', 'sympy/sets/handlers/issubset.py']

### Bug Description
`is_subset` gives wrong results @sylee957 Current status on `master`, ```python >>> a = FiniteSet(1, 2) >>> b = ProductSet(a, a) >>> c = FiniteSet((1, 1), (1, 2), (2, 1), (2, 2)) >>> b.intersection(c) == c.intersection(b) True >>> b.is_subset(c) >>> c.is_subset(b) True >>> Eq(b, c).simplif

### Mechanism Source
is_subset gives wrong results for FiniteSet vs ProductSet comparisons because the subset handler doesn't properly check membership of finite set elements in product sets

### Mechanism Steps
  1. User calls FiniteSet(1,2).is_subset(ProductSet(S.Reals, S.Reals))
  2. The subset handler in handlers/issubset.py doesn't properly handle FiniteSet-to-ProductSet comparisons
  3. The comparison handler in handlers/comparison.py has related issues with set equality
  4. is_subset returns wrong boolean values
  5. Fix: update issubset.py and comparison.py handlers, fix element containment check in relational.py

### Justification
Bug type: subset_check_wrong_result
Mechanism outcome: is_subset returns incorrect results for FiniteSet vs ProductSet comparisons
Trap: Fixing only issubset.py without also fixing comparison.py and relational.py

Evidence: Derived from reference patch diff analysis. The patch modifies
3 file(s): sympy/core/relational.py, sympy/sets/handlers/comparison.py, sympy/sets/handlers/issubset.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.

================================================================================
## sympy__sympy-22080
Repo: sympy/sympy
Files: ['sympy/printing/codeprinter.py', 'sympy/printing/precedence.py']

### Bug Description
Mod function lambdify bug Description: When lambdifying any function of structure like `expr * Mod(a, b)` sympy moves the multiplier into the first argument of Mod, like `Mod(expr * a, b)`, WHEN we specify `modules=[]`  This is an example from Sympy online shell ``` >>> from sympy import Mod, l

### Mechanism Source
CodePrinter._print_Mul does not handle Mod correctly — when Mod appears in a multiplication, the printer moves it incorrectly due to wrong precedence handling

### Mechanism Steps
  1. User lambdifies an expression containing expr * Mod(a, b)
  2. CodePrinter._print_Mul processes the multiplication factors
  3. Mod is treated as a regular function but its precedence is not properly defined in precedence.py
  4. The printer incorrectly reorders or parenthesizes the Mod expression within the multiplication
  5. The generated code computes the wrong value because operator precedence is broken

### Justification
Bug type: precedence_error_in_code_generation
Mechanism outcome: lambdify produces incorrect code for expressions containing Mod in multiplication, computing wrong numerical results
Trap: Fixing only codeprinter.py without updating the precedence table in precedence.py, or introducing NameError by referencing undefined symbols

Evidence: Derived from reference patch diff analysis. The patch modifies
2 file(s): sympy/printing/codeprinter.py, sympy/printing/precedence.py.
Each mechanism step corresponds to a specific code path visible in the
buggy source and confirmed by the reference fix's changes.
