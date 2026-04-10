"""Tests for submission signing and payload handling."""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch, MagicMock

import pytest

from gauntlet.core.submit import _sign_payload, submit_result, _SUBMIT_KEY
import gauntlet


# ---------------------------------------------------------------------------
# Tests: _sign_payload
# ---------------------------------------------------------------------------

class TestSignPayload:
    """HMAC-SHA256 signing of payload bytes."""

    def test_consistent_signature_for_same_input(self):
        body = b'{"model": "test", "score": 95}'
        sig1 = _sign_payload(body)
        sig2 = _sign_payload(body)
        assert sig1 == sig2

    def test_different_input_different_signature(self):
        sig1 = _sign_payload(b'{"model": "a"}')
        sig2 = _sign_payload(b'{"model": "b"}')
        assert sig1 != sig2

    def test_signature_is_hex_string(self):
        sig = _sign_payload(b"test")
        assert isinstance(sig, str)
        # SHA256 hex digest is 64 characters
        assert len(sig) == 64
        # Only hex chars
        int(sig, 16)

    def test_matches_manual_hmac(self):
        body = b'{"key": "value"}'
        expected = hmac.new(
            _SUBMIT_KEY.encode(), body, hashlib.sha256
        ).hexdigest()
        assert _sign_payload(body) == expected

    def test_empty_payload(self):
        sig = _sign_payload(b"")
        assert isinstance(sig, str)
        assert len(sig) == 64

    def test_large_payload(self):
        body = b"x" * 100_000
        sig = _sign_payload(body)
        assert isinstance(sig, str)
        assert len(sig) == 64


# ---------------------------------------------------------------------------
# Tests: submit_result — version injection
# ---------------------------------------------------------------------------

class TestSubmitResultVersionInjection:
    """submit_result injects cli_version into the payload."""

    @patch("gauntlet.core.submit.httpx.post")
    def test_injects_cli_version(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        payload = {"model": "test", "score": 90}
        submit_result(payload)

        # The payload dict should have been mutated
        assert payload["cli_version"] == gauntlet.__version__

    @patch("gauntlet.core.submit.httpx.post")
    def test_cli_version_included_in_posted_body(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        payload = {"model": "test-model", "score": 85}
        submit_result(payload)

        # Verify what was actually posted
        call_kwargs = mock_post.call_args
        posted_body = call_kwargs.kwargs.get("content") or call_kwargs[1].get("content")
        parsed = json.loads(posted_body)
        assert parsed["cli_version"] == gauntlet.__version__
        assert parsed["model"] == "test-model"
        assert parsed["score"] == 85


# ---------------------------------------------------------------------------
# Tests: submit_result — signature header
# ---------------------------------------------------------------------------

class TestSubmitResultSignature:
    """submit_result computes and sends HMAC signature header."""

    @patch("gauntlet.core.submit.httpx.post")
    def test_signature_header_present(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        submit_result({"model": "x"})

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert "X-Gauntlet-Signature" in headers

    @patch("gauntlet.core.submit.httpx.post")
    def test_signature_matches_body(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        submit_result({"model": "sig-check"})

        call_kwargs = mock_post.call_args
        posted_body = call_kwargs.kwargs.get("content") or call_kwargs[1].get("content")
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")

        expected_sig = _sign_payload(posted_body)
        assert headers["X-Gauntlet-Signature"] == expected_sig


# ---------------------------------------------------------------------------
# Tests: submit_result — HTTP behavior (mocked)
# ---------------------------------------------------------------------------

class TestSubmitResultHTTP:
    """HTTP call behavior without hitting the network."""

    @patch("gauntlet.core.submit.httpx.post")
    def test_returns_response_on_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = submit_result({"model": "x"})
        assert result is mock_resp

    @patch("gauntlet.core.submit.httpx.post")
    def test_returns_response_on_non_200(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        result = submit_result({"model": "x"})
        # Still returns the response (even on failure status)
        assert result is mock_resp

    @patch("gauntlet.core.submit.httpx.post", side_effect=Exception("connection refused"))
    def test_returns_none_on_exception(self, mock_post):
        result = submit_result({"model": "x"})
        assert result is None

    @patch("gauntlet.core.submit.httpx.post")
    def test_posts_to_community_api(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        submit_result({"model": "x"})

        call_args = mock_post.call_args
        url = call_args[0][0] if call_args[0] else call_args.kwargs.get("url", "")
        assert "gauntlet" in url.lower() or "basaltlabs" in url.lower()

    @patch("gauntlet.core.submit.httpx.post")
    def test_content_type_json(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        submit_result({"model": "x"})

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["Content-Type"] == "application/json"

    @patch("gauntlet.core.submit.httpx.post")
    def test_custom_timeout(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        submit_result({"model": "x"}, timeout=30)

        call_kwargs = mock_post.call_args
        timeout = call_kwargs.kwargs.get("timeout") or call_kwargs[1].get("timeout")
        assert timeout == 30
