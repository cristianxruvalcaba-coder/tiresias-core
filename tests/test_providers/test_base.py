"""Tests for the BaseProvider abstract interface."""
import pytest
from tiresias.providers.base import BaseProvider


def test_base_provider_is_abstract():
    with pytest.raises(TypeError):
        BaseProvider()  # type: ignore


def test_is_error_true_for_5xx():
    class ConcreteProvider(BaseProvider):
        @property
        def name(self):
            return "test"
        @property
        def api_base(self):
            return "http://test"
        def format_request(self, body):
            return "http://test", {}, body
        def parse_response(self, r):
            return r

    p = ConcreteProvider()
    assert p.is_error(500) is True
    assert p.is_error(502) is True
    assert p.is_error(503) is True


def test_is_error_false_for_non_5xx():
    class ConcreteProvider(BaseProvider):
        @property
        def name(self):
            return "test"
        @property
        def api_base(self):
            return "http://test"
        def format_request(self, body):
            return "http://test", {}, body
        def parse_response(self, r):
            return r

    p = ConcreteProvider()
    assert p.is_error(200) is False
    assert p.is_error(400) is False
    assert p.is_error(404) is False
