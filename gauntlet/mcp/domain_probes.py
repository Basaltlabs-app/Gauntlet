"""Domain-specific task competence probes.

Each probe asks the model to produce real code/config and verifies it
deterministically using regex, keyword matching, or structural checks.
NO LLM-as-judge -- every verify function is fully deterministic.

Probe format matches probes.py:
    name:        Human-readable test name
    category:    Scoring category (prefixed with domain_)
    description: What it tests
    severity:    HIGH / MEDIUM / LOW
    step_count:  Number of conversation steps
    steps:       List of step dicts with 'prompt' key
    verify:      callable(responses) -> (score, passed, details)
"""

from __future__ import annotations

import re


def _extract_text(responses: list[str]) -> str:
    """Get the last response as a single string for analysis."""
    return responses[-1] if responses else ""


def _count_pattern(text: str, pattern: str, flags: int = re.IGNORECASE | re.DOTALL) -> int:
    """Count non-overlapping matches of a regex pattern."""
    return len(re.findall(pattern, text, flags))


# ---------------------------------------------------------------------------
# DATABASE PROBES
# ---------------------------------------------------------------------------

def _verify_multi_tenant_migration(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    # Must have 3 CREATE TABLE statements
    ct_count = _count_pattern(text, r"CREATE\s+TABLE")
    checks["create_table_count"] = ct_count
    if ct_count >= 3:
        score += 0.25
    elif ct_count >= 2:
        score += 0.15

    # Must have REFERENCES (foreign keys)
    has_refs = bool(re.search(r"REFERENCES", text, re.IGNORECASE))
    checks["has_foreign_keys"] = has_refs
    if has_refs:
        score += 0.25

    # Must have indexes
    has_index = bool(re.search(r"(CREATE\s+INDEX|INDEX\s*\()", text, re.IGNORECASE))
    checks["has_indexes"] = has_index
    if has_index:
        score += 0.25

    # Must have timestamp columns
    has_timestamps = bool(
        re.search(r"created_at", text, re.IGNORECASE)
        and re.search(r"updated_at", text, re.IGNORECASE)
    )
    checks["has_timestamps"] = has_timestamps
    if has_timestamps:
        score += 0.25

    passed = score >= 0.75
    return score, passed, checks


def _verify_rls_policy(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    has_create_policy = bool(re.search(r"CREATE\s+POLICY", text, re.IGNORECASE))
    checks["has_create_policy"] = has_create_policy
    if has_create_policy:
        score += 0.3

    has_using = bool(re.search(r"USING\s*\(", text, re.IGNORECASE))
    checks["has_using_clause"] = has_using
    if has_using:
        score += 0.3

    has_auth = bool(re.search(r"(auth\.uid\(\)|current_user|current_setting)", text, re.IGNORECASE))
    checks["has_auth_reference"] = has_auth
    if has_auth:
        score += 0.2

    has_permission = bool(re.search(r"(SELECT|ALL|INSERT|UPDATE|DELETE)", text, re.IGNORECASE))
    checks["has_permission_type"] = has_permission
    if has_permission:
        score += 0.2

    passed = score >= 0.7
    return score, passed, checks


def _verify_top_customers_query(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    has_select = bool(re.search(r"\bSELECT\b", text, re.IGNORECASE))
    checks["has_select"] = has_select
    if has_select:
        score += 0.15

    join_count = _count_pattern(text, r"\bJOIN\b")
    checks["join_count"] = join_count
    if join_count >= 2:
        score += 0.25
    elif join_count >= 1:
        score += 0.1

    has_group_by = bool(re.search(r"GROUP\s+BY", text, re.IGNORECASE))
    checks["has_group_by"] = has_group_by
    if has_group_by:
        score += 0.2

    has_order_by = bool(re.search(r"ORDER\s+BY", text, re.IGNORECASE))
    checks["has_order_by"] = has_order_by
    if has_order_by:
        score += 0.2

    has_limit = bool(re.search(r"\bLIMIT\b", text, re.IGNORECASE))
    checks["has_limit"] = has_limit
    if has_limit:
        score += 0.2

    passed = score >= 0.7
    return score, passed, checks


def _verify_query_optimization(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    mentions_index = bool(re.search(r"\bindex\b", text, re.IGNORECASE))
    checks["mentions_index"] = mentions_index
    if mentions_index:
        score += 0.4

    # Check for composite/compound index suggestion
    composite = bool(re.search(
        r"(composite|compound|multi.?column|CREATE\s+INDEX\s+\w+\s+ON\s+\w+\s*\([^)]*,\s*[^)]*\))",
        text,
        re.IGNORECASE,
    ))
    checks["suggests_composite_index"] = composite
    if composite:
        score += 0.4

    # Mentions relevant columns in index
    mentions_cols = bool(
        re.search(r"customer_id", text, re.IGNORECASE)
        and re.search(r"status", text, re.IGNORECASE)
    )
    checks["references_relevant_columns"] = mentions_cols
    if mentions_cols:
        score += 0.2

    passed = score >= 0.6
    return score, passed, checks


# ---------------------------------------------------------------------------
# API / BACKEND PROBES
# ---------------------------------------------------------------------------

def _verify_rate_limiter(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    has_store = bool(re.search(r"(dict|Dict|counter|Counter|cache|store|defaultdict|\{\}|redis)", text, re.IGNORECASE))
    checks["has_counter_or_store"] = has_store
    if has_store:
        score += 0.3

    has_429 = bool(re.search(r"(429|rate.?limit|too.?many)", text, re.IGNORECASE))
    checks["has_rate_limit_response"] = has_429
    if has_429:
        score += 0.35

    has_time = bool(re.search(r"(60|minute|time\.time|datetime|timedelta|ttl)", text, re.IGNORECASE))
    checks["has_time_logic"] = has_time
    if has_time:
        score += 0.35

    passed = score >= 0.65
    return score, passed, checks


def _verify_input_validation(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    has_pattern = bool(re.search(r"(regex|re\.|pattern|validate|validator|pydantic|Depends)", text, re.IGNORECASE))
    checks["has_validation_logic"] = has_pattern
    if has_pattern:
        score += 0.2

    has_email = bool(re.search(r"(email|@.*\.)", text, re.IGNORECASE))
    checks["checks_email"] = has_email
    if has_email:
        score += 0.2

    has_password = bool(re.search(r"(password|passwd)", text, re.IGNORECASE) and re.search(r"(8|length|min)", text, re.IGNORECASE))
    checks["checks_password_length"] = has_password
    if has_password:
        score += 0.3

    has_username = bool(re.search(r"(username|user.?name)", text, re.IGNORECASE))
    checks["checks_username"] = has_username
    if has_username:
        score += 0.3

    passed = score >= 0.6
    return score, passed, checks


def _verify_webhook_hmac(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    has_hmac = bool(re.search(r"\bhmac\b", text, re.IGNORECASE))
    checks["has_hmac"] = has_hmac
    if has_hmac:
        score += 0.3

    has_sha256 = bool(re.search(r"sha256|SHA256|sha-256", text, re.IGNORECASE))
    checks["has_sha256"] = has_sha256
    if has_sha256:
        score += 0.25

    has_compare = bool(re.search(r"(compare_digest|constant.?time|secure.?compare|timing.?safe)", text, re.IGNORECASE))
    checks["has_constant_time_compare"] = has_compare
    if has_compare:
        score += 0.25

    has_header = bool(re.search(r"(header|X-Signature|request\.headers|get_header)", text, re.IGNORECASE))
    checks["has_header_extraction"] = has_header
    if has_header:
        score += 0.2

    passed = score >= 0.7
    return score, passed, checks


def _verify_rest_api_design(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    methods = {"GET", "POST"}
    update_methods = {"PUT", "PATCH"}
    has_get_post = all(re.search(rf"\b{m}\b", text) for m in methods)
    has_update = any(re.search(rf"\b{m}\b", text) for m in update_methods)
    has_delete = bool(re.search(r"\bDELETE\b", text))
    checks["has_crud_methods"] = has_get_post and has_update and has_delete
    if has_get_post:
        score += 0.15
    if has_update:
        score += 0.1
    if has_delete:
        score += 0.1

    has_task_route = bool(re.search(r"/tasks", text, re.IGNORECASE))
    has_project_route = bool(re.search(r"/projects", text, re.IGNORECASE))
    checks["has_resource_paths"] = has_task_route and has_project_route
    if has_task_route:
        score += 0.15
    if has_project_route:
        score += 0.15

    status_codes = _count_pattern(text, r"\b(200|201|204|400|401|403|404|409|422|500)\b")
    checks["status_code_count"] = status_codes
    if status_codes >= 3:
        score += 0.35
    elif status_codes >= 1:
        score += 0.15

    passed = score >= 0.6
    return score, passed, checks


# ---------------------------------------------------------------------------
# AUTH / SECURITY PROBES
# ---------------------------------------------------------------------------

def _verify_jwt_tokens(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    has_jwt = bool(re.search(r"\bjwt\b", text, re.IGNORECASE))
    checks["has_jwt"] = has_jwt
    if has_jwt:
        score += 0.2

    has_access = bool(re.search(r"\baccess", text, re.IGNORECASE))
    has_refresh = bool(re.search(r"\brefresh", text, re.IGNORECASE))
    checks["has_both_token_types"] = has_access and has_refresh
    if has_access and has_refresh:
        score += 0.3

    has_expiry = bool(re.search(r"(expire|exp|expiration|expires_in|timedelta)", text, re.IGNORECASE))
    checks["has_expiry_logic"] = has_expiry
    if has_expiry:
        score += 0.2

    has_15 = bool(re.search(r"\b15\b", text))
    has_7 = bool(re.search(r"\b7\b", text))
    checks["has_correct_durations"] = has_15 and has_7
    if has_15 and has_7:
        score += 0.3

    passed = score >= 0.7
    return score, passed, checks


def _verify_csrf_protection(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    has_csrf = bool(re.search(r"(csrf|CSRF|xsrf|XSRF|token)", text, re.IGNORECASE))
    checks["has_csrf_token"] = has_csrf
    if has_csrf:
        score += 0.35

    has_cookie = bool(re.search(r"\bcookie\b", text, re.IGNORECASE))
    checks["has_cookie"] = has_cookie
    if has_cookie:
        score += 0.35

    has_compare = bool(re.search(r"(compare|verify|validate|match|===|==)", text, re.IGNORECASE))
    checks["has_comparison"] = has_compare
    if has_compare:
        score += 0.3

    passed = score >= 0.65
    return score, passed, checks


def _verify_oauth_flow(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    has_redirect = bool(re.search(r"(redirect|authorize|authorization_url|auth_url)", text, re.IGNORECASE))
    checks["has_redirect"] = has_redirect
    if has_redirect:
        score += 0.25

    has_callback = bool(re.search(r"(callback|redirect_uri|redirect_url)", text, re.IGNORECASE))
    checks["has_callback"] = has_callback
    if has_callback:
        score += 0.25

    has_code = bool(re.search(r"(authorization.?code|\bcode\b)", text, re.IGNORECASE))
    checks["has_code"] = has_code
    if has_code:
        score += 0.25

    has_token_exchange = bool(re.search(r"(access_token|token.?exchange|grant_type|token_url)", text, re.IGNORECASE))
    checks["has_token_exchange"] = has_token_exchange
    if has_token_exchange:
        score += 0.25

    passed = score >= 0.7
    return score, passed, checks


# ---------------------------------------------------------------------------
# FRONTEND PROBES
# ---------------------------------------------------------------------------

def _verify_accessible_form(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    has_label = bool(re.search(r"<label", text, re.IGNORECASE))
    has_for = bool(re.search(r'(for=|htmlFor)', text, re.IGNORECASE))
    checks["has_label_with_for"] = has_label and has_for
    if has_label and has_for:
        score += 0.3

    has_aria = bool(re.search(r"aria-", text, re.IGNORECASE))
    checks["has_aria_attributes"] = has_aria
    if has_aria:
        score += 0.25

    has_validation = bool(re.search(r"(required|pattern=|validate|novalidate)", text, re.IGNORECASE))
    checks["has_validation"] = has_validation
    if has_validation:
        score += 0.2

    has_error = bool(re.search(r"(error|invalid|alert|warning|message)", text, re.IGNORECASE))
    checks["has_error_display"] = has_error
    if has_error:
        score += 0.25

    passed = score >= 0.6
    return score, passed, checks


def _verify_infinite_scroll(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    has_observer = bool(re.search(r"(IntersectionObserver|scroll\s*event|addEventListener.*scroll|onscroll)", text, re.IGNORECASE))
    checks["has_scroll_detection"] = has_observer
    if has_observer:
        score += 0.35

    has_loading = bool(re.search(r"(loading|isLoading|spinner|indicator|skeleton)", text, re.IGNORECASE))
    checks["has_loading_state"] = has_loading
    if has_loading:
        score += 0.3

    has_fetch = bool(re.search(r"(fetch|axios|XMLHttpRequest|api|request|getData|\$http)", text, re.IGNORECASE))
    checks["has_api_call"] = has_fetch
    if has_fetch:
        score += 0.35

    passed = score >= 0.65
    return score, passed, checks


def _verify_debounced_search(responses: list[str]):
    text = _extract_text(responses)
    checks = {}
    score = 0.0

    has_timeout = bool(re.search(r"(setTimeout|debounce|useDebounce|_\.debounce|lodash)", text, re.IGNORECASE))
    checks["has_debounce_mechanism"] = has_timeout
    if has_timeout:
        score += 0.3

    has_clear = bool(re.search(r"(clearTimeout|cancel|abort|cleanup)", text, re.IGNORECASE))
    checks["has_cleanup"] = has_clear
    if has_clear:
        score += 0.25

    has_300 = bool(re.search(r"\b300\b", text))
    checks["has_300ms_delay"] = has_300
    if has_300:
        score += 0.2

    has_fetch = bool(re.search(r"(fetch|axios|api|request|search|query)", text, re.IGNORECASE))
    checks["has_api_call"] = has_fetch
    if has_fetch:
        score += 0.25

    passed = score >= 0.65
    return score, passed, checks


# ---------------------------------------------------------------------------
# PROBE LIST
# ---------------------------------------------------------------------------

_DOMAIN_PROBES: list[dict] = [
    # --- Database (4) ---
    {
        "name": "Multi-tenant SaaS migration",
        "category": "domain_database",
        "description": "Write a PostgreSQL CREATE TABLE migration for a multi-tenant SaaS with proper foreign keys, indexes, and timestamps.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "Write a PostgreSQL CREATE TABLE migration for a multi-tenant SaaS "
                    "with users, organizations, and memberships tables. Include foreign keys, "
                    "indexes, and created_at/updated_at timestamps."
                ),
            },
        ],
        "verify": _verify_multi_tenant_migration,
    },
    {
        "name": "Supabase RLS policy",
        "category": "domain_database",
        "description": "Write a Supabase row-level security policy scoped to user organizations.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "Write a Supabase row-level security policy that ensures users can only "
                    "read rows belonging to their organization."
                ),
            },
        ],
        "verify": _verify_rls_policy,
    },
    {
        "name": "Top customers aggregation query",
        "category": "domain_database",
        "description": "Write a SQL query joining three tables with GROUP BY, ORDER BY, and LIMIT.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "Write a SQL query that returns the top 5 customers by total order value, "
                    "joining customers, orders, and order_items tables."
                ),
            },
        ],
        "verify": _verify_top_customers_query,
    },
    {
        "name": "Slow query optimization",
        "category": "domain_database",
        "description": "Diagnose a slow query on a large table and suggest index-based fixes.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "A query on a 10M row orders table is slow: "
                    "SELECT * FROM orders WHERE customer_id = 123 AND status = 'pending' "
                    "ORDER BY created_at DESC. Suggest how to fix it."
                ),
            },
        ],
        "verify": _verify_query_optimization,
    },
    # --- API / Backend (4) ---
    {
        "name": "Rate limiting middleware",
        "category": "domain_api",
        "description": "Implement a rate limiter allowing 100 requests per minute per IP.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "Implement a rate limiting middleware in Python (any framework) that "
                    "allows 100 requests per minute per IP address."
                ),
            },
        ],
        "verify": _verify_rate_limiter,
    },
    {
        "name": "Input validation for registration",
        "category": "domain_api",
        "description": "Validate email, password complexity, and username format for user registration.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "Write input validation for a user registration endpoint that validates "
                    "email, password (min 8 chars, 1 uppercase, 1 number), and username "
                    "(3-20 chars, alphanumeric)."
                ),
            },
        ],
        "verify": _verify_input_validation,
    },
    {
        "name": "Webhook HMAC verification",
        "category": "domain_api",
        "description": "Verify HMAC-SHA256 webhook signatures with constant-time comparison.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "Implement a webhook handler that verifies the HMAC-SHA256 signature "
                    "from the X-Signature header before processing the payload."
                ),
            },
        ],
        "verify": _verify_webhook_hmac,
    },
    {
        "name": "RESTful API design",
        "category": "domain_api",
        "description": "Design RESTful routes with proper HTTP methods and status codes.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "Design a RESTful API with routes for a task management system "
                    "(CRUD operations on tasks and projects)."
                ),
            },
        ],
        "verify": _verify_rest_api_design,
    },
    # --- Auth / Security (3) ---
    {
        "name": "JWT access + refresh tokens",
        "category": "domain_auth",
        "description": "Implement JWT token generation with proper expiration for access and refresh tokens.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "Implement JWT access + refresh token generation and validation. "
                    "Access token expires in 15 minutes, refresh token in 7 days."
                ),
            },
        ],
        "verify": _verify_jwt_tokens,
    },
    {
        "name": "CSRF double-submit cookie",
        "category": "domain_auth",
        "description": "Prevent CSRF attacks using the double-submit cookie pattern.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "Write middleware that prevents CSRF attacks using the double-submit "
                    "cookie pattern."
                ),
            },
        ],
        "verify": _verify_csrf_protection,
    },
    {
        "name": "OAuth 2.0 authorization code flow",
        "category": "domain_auth",
        "description": "Implement the full OAuth 2.0 authorization code flow.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "Implement the OAuth 2.0 authorization code flow: redirect to provider, "
                    "handle callback, exchange code for token."
                ),
            },
        ],
        "verify": _verify_oauth_flow,
    },
    # --- Frontend (3) ---
    {
        "name": "Accessible HTML form",
        "category": "domain_frontend",
        "description": "Build an accessible form with labels, aria attributes, and client-side validation.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "Build an accessible HTML form with name, email, and message fields. "
                    "Include proper labels, aria attributes, and client-side validation "
                    "with error messages."
                ),
            },
        ],
        "verify": _verify_accessible_form,
    },
    {
        "name": "Infinite scroll implementation",
        "category": "domain_frontend",
        "description": "Implement infinite scroll that loads items on reaching page bottom.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "Implement infinite scroll in JavaScript that loads more items when "
                    "the user reaches the bottom of the page."
                ),
            },
        ],
        "verify": _verify_infinite_scroll,
    },
    {
        "name": "Debounced search input",
        "category": "domain_frontend",
        "description": "Debounce a search input to wait 300ms before making an API call.",
        "severity": "HIGH",
        "step_count": 1,
        "steps": [
            {
                "prompt": (
                    "Write a debounced search input in JavaScript/TypeScript that waits "
                    "300ms after the user stops typing before making an API call."
                ),
            },
        ],
        "verify": _verify_debounced_search,
    },
]


def get_domain_probes() -> list[dict]:
    """Return all domain-specific competence probes."""
    return list(_DOMAIN_PROBES)
