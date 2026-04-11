"""Tests for domain probes and community probe loader."""

from __future__ import annotations

import os
import tempfile
import textwrap
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Domain probes tests
# ---------------------------------------------------------------------------

from gauntlet.mcp.domain_probes import get_domain_probes


class TestGetDomainProbes:
    """Test the domain probe collection."""

    def test_returns_at_least_14_probes(self):
        probes = get_domain_probes()
        assert len(probes) >= 14, f"Expected >= 14 probes, got {len(probes)}"

    def test_each_probe_has_required_keys(self):
        required = {"name", "category", "description", "severity", "step_count", "steps", "verify"}
        for probe in get_domain_probes():
            missing = required - probe.keys()
            assert not missing, f"Probe '{probe.get('name', '?')}' missing keys: {missing}"

    def test_database_category_has_probes(self):
        probes = [p for p in get_domain_probes() if p["category"] == "domain_database"]
        assert len(probes) >= 4, f"Expected >= 4 database probes, got {len(probes)}"

    def test_api_category_has_probes(self):
        probes = [p for p in get_domain_probes() if p["category"] == "domain_api"]
        assert len(probes) >= 4, f"Expected >= 4 API probes, got {len(probes)}"

    def test_auth_category_has_probes(self):
        probes = [p for p in get_domain_probes() if p["category"] == "domain_auth"]
        assert len(probes) >= 3, f"Expected >= 3 auth probes, got {len(probes)}"

    def test_frontend_category_has_probes(self):
        probes = [p for p in get_domain_probes() if p["category"] == "domain_frontend"]
        assert len(probes) >= 3, f"Expected >= 3 frontend probes, got {len(probes)}"


class TestDatabaseProbeVerify:
    """Test database probe verify functions with good and bad responses."""

    def _get_probe(self, name_fragment: str) -> dict:
        for p in get_domain_probes():
            if name_fragment.lower() in p["name"].lower():
                return p
        raise ValueError(f"No probe matching '{name_fragment}'")

    def test_migration_probe_good_response(self):
        probe = self._get_probe("Multi-tenant")
        good_response = textwrap.dedent("""\
            ```sql
            CREATE TABLE organizations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(255) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email VARCHAR(255) UNIQUE NOT NULL,
                name VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE memberships (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                role VARCHAR(50) NOT NULL DEFAULT 'member',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, org_id)
            );

            CREATE INDEX idx_memberships_user ON memberships(user_id);
            CREATE INDEX idx_memberships_org ON memberships(org_id);
            ```
        """)
        score, passed, checks = probe["verify"]([good_response])
        assert passed, f"Good migration should pass: score={score}, checks={checks}"
        assert score >= 0.75

    def test_migration_probe_bad_response(self):
        probe = self._get_probe("Multi-tenant")
        bad_response = "Sure, you should use a database for that."
        score, passed, checks = probe["verify"]([bad_response])
        assert not passed, f"Bad response should fail: score={score}, checks={checks}"
        assert score < 0.75

    def test_rls_probe_good_response(self):
        probe = self._get_probe("RLS")
        good_response = textwrap.dedent("""\
            ```sql
            CREATE POLICY "org_isolation" ON documents
            FOR SELECT
            USING (
                org_id IN (
                    SELECT org_id FROM memberships
                    WHERE user_id = auth.uid()
                )
            );
            ```
        """)
        score, passed, checks = probe["verify"]([good_response])
        assert passed, f"Good RLS policy should pass: score={score}, checks={checks}"

    def test_rls_probe_bad_response(self):
        probe = self._get_probe("RLS")
        bad_response = "You can use RLS for security."
        score, passed, checks = probe["verify"]([bad_response])
        assert not passed, f"Bad RLS response should fail: score={score}, checks={checks}"


class TestApiProbeVerify:
    """Test API/backend probe verify functions."""

    def _get_probe(self, name_fragment: str) -> dict:
        for p in get_domain_probes():
            if name_fragment.lower() in p["name"].lower():
                return p
        raise ValueError(f"No probe matching '{name_fragment}'")

    def test_rate_limiter_good_response(self):
        probe = self._get_probe("Rate limiting")
        good_response = textwrap.dedent("""\
            ```python
            import time
            from collections import defaultdict

            request_counts = defaultdict(list)

            def rate_limit_middleware(request, next_handler):
                ip = request.remote_addr
                now = time.time()
                # Remove entries older than 60 seconds
                request_counts[ip] = [t for t in request_counts[ip] if now - t < 60]
                if len(request_counts[ip]) >= 100:
                    return Response("Too Many Requests", status=429)
                request_counts[ip].append(now)
                return next_handler(request)
            ```
        """)
        score, passed, checks = probe["verify"]([good_response])
        assert passed, f"Good rate limiter should pass: score={score}, checks={checks}"

    def test_webhook_hmac_good_response(self):
        probe = self._get_probe("Webhook HMAC")
        good_response = textwrap.dedent("""\
            ```python
            import hmac
            import hashlib

            def verify_webhook(request):
                signature = request.headers.get("X-Signature")
                payload = request.get_data()
                secret = b"your-webhook-secret"
                expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(signature, expected):
                    abort(401)
                process_payload(payload)
            ```
        """)
        score, passed, checks = probe["verify"]([good_response])
        assert passed, f"Good HMAC handler should pass: score={score}, checks={checks}"


# ---------------------------------------------------------------------------
# Community probe loader tests
# ---------------------------------------------------------------------------

from gauntlet.core.community_probes import (
    COMMUNITY_DIR,
    _build_verify_from_yaml,
    load_community_probes,
)


class TestCommunityProbeLoader:
    """Test the YAML-based community probe loader."""

    def test_handles_missing_directory(self):
        """Should return empty list if community dir doesn't exist."""
        with mock.patch(
            "gauntlet.core.community_probes.COMMUNITY_DIR",
            Path("/nonexistent/path/that/doesnt/exist"),
        ):
            probes = load_community_probes()
            assert probes == []

    def test_loads_valid_yaml_probe(self):
        """Create a temp YAML probe and verify it loads correctly."""
        yaml_content = textwrap.dedent("""\
            name: "Test probe"
            category: "testing"
            domain: "test_domain"
            severity: "LOW"
            description: "A test probe for unit testing"
            steps:
              - prompt: "Write a hello world in Python"
            verify:
              required_patterns:
                - "print"
                - "hello"
              min_length: 10
        """)

        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "test_probe.yaml"
            yaml_path.write_text(yaml_content)

            with mock.patch(
                "gauntlet.core.community_probes.COMMUNITY_DIR",
                Path(tmpdir),
            ):
                probes = load_community_probes()

            assert len(probes) == 1
            probe = probes[0]
            assert probe["name"] == "Test probe"
            assert probe["category"] == "community_test_domain"
            assert probe["severity"] == "LOW"
            assert probe["step_count"] == 1
            assert probe["_community"] is True
            assert callable(probe["verify"])

    def test_verify_function_passes_good_response(self):
        """Verify function built from YAML passes a matching response."""
        spec = {
            "required_patterns": ["hello", "world"],
            "forbidden_patterns": ["error"],
            "min_length": 5,
        }
        verify = _build_verify_from_yaml(spec)
        score, passed, checks = verify(["hello world program"])
        assert passed
        assert score >= 0.6

    def test_verify_function_fails_bad_response(self):
        """Verify function built from YAML fails a non-matching response."""
        spec = {
            "required_patterns": ["CREATE TABLE", "INDEX"],
            "min_length": 50,
        }
        verify = _build_verify_from_yaml(spec)
        score, passed, checks = verify(["nope"])
        assert not passed
        assert score < 0.6

    def test_skips_malformed_yaml(self):
        """Malformed YAML files should be silently skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # File with invalid YAML
            bad_yaml = Path(tmpdir) / "bad.yaml"
            bad_yaml.write_text(": : : not valid yaml [[[")

            # File missing required fields
            incomplete = Path(tmpdir) / "incomplete.yaml"
            incomplete.write_text("name: incomplete\n")

            # Valid file for comparison
            valid = Path(tmpdir) / "valid.yaml"
            valid.write_text(textwrap.dedent("""\
                name: "Valid probe"
                category: "test"
                steps:
                  - "Do something"
            """))

            with mock.patch(
                "gauntlet.core.community_probes.COMMUNITY_DIR",
                Path(tmpdir),
            ):
                probes = load_community_probes()

            # Only the valid file should load
            assert len(probes) == 1
            assert probes[0]["name"] == "Valid probe"

    def test_steps_as_strings_converted_to_dicts(self):
        """Step strings should be converted to {prompt: ...} dicts."""
        yaml_content = textwrap.dedent("""\
            name: "String steps probe"
            category: "test"
            steps:
              - "First prompt"
              - "Second prompt"
        """)

        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "string_steps.yaml"
            yaml_path.write_text(yaml_content)

            with mock.patch(
                "gauntlet.core.community_probes.COMMUNITY_DIR",
                Path(tmpdir),
            ):
                probes = load_community_probes()

            assert len(probes) == 1
            assert probes[0]["steps"] == [
                {"prompt": "First prompt"},
                {"prompt": "Second prompt"},
            ]
            assert probes[0]["step_count"] == 2

    def test_empty_yaml_file_skipped(self):
        """Empty YAML files should be silently skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            empty = Path(tmpdir) / "empty.yaml"
            empty.write_text("")

            with mock.patch(
                "gauntlet.core.community_probes.COMMUNITY_DIR",
                Path(tmpdir),
            ):
                probes = load_community_probes()

            assert probes == []
