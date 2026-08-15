"""Tests for the per-caller rate-limit fairness layer — no network calls.

See pubmed_client.py's comment on _identity_limiter: None means "no server-level
identity" (CLI/tests/direct API use — behaves exactly as before this feature),
"anonymous" is the shared low-budget pool for HTTP callers with no API key, and
any other string is a keyed caller's own isolated, higher-budget pool.
"""

from biolab import pubmed_client
from biolab.auth import current_identity


def test_no_identity_set_skips_the_fairness_layer():
    token = current_identity.set(None)
    try:
        assert pubmed_client._identity_limiter() is None
    finally:
        current_identity.reset(token)


def test_anonymous_identity_gets_the_low_shared_rate():
    pubmed_client._identity_limiters.clear()
    token = current_identity.set("anonymous")
    try:
        limiter = pubmed_client._identity_limiter()
        assert limiter is not None
        assert limiter._min_interval == 1.0 / pubmed_client.ANONYMOUS_REQUESTS_PER_SECOND
    finally:
        current_identity.reset(token)


def test_keyed_identity_gets_the_full_global_rate():
    pubmed_client._identity_limiters.clear()
    token = current_identity.set("user:alice")
    try:
        limiter = pubmed_client._identity_limiter()
        assert limiter is not None
        assert limiter._min_interval == 1.0 / pubmed_client.REQUESTS_PER_SECOND
    finally:
        current_identity.reset(token)


def test_two_different_keyed_identities_get_independent_limiters():
    pubmed_client._identity_limiters.clear()

    token_a = current_identity.set("user:alice")
    limiter_a = pubmed_client._identity_limiter()
    current_identity.reset(token_a)

    token_b = current_identity.set("user:bob")
    limiter_b = pubmed_client._identity_limiter()
    current_identity.reset(token_b)

    assert limiter_a is not limiter_b


def test_same_identity_reuses_the_same_limiter():
    pubmed_client._identity_limiters.clear()

    token1 = current_identity.set("user:alice")
    limiter1 = pubmed_client._identity_limiter()
    current_identity.reset(token1)

    token2 = current_identity.set("user:alice")
    limiter2 = pubmed_client._identity_limiter()
    current_identity.reset(token2)

    assert limiter1 is limiter2
