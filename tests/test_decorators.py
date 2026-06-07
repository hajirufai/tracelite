"""Tests for @trace decorator."""

import pytest
from tracelite.decorators import trace, configure_decorator_tracing
from tracelite.processor import SimpleSpanProcessor
from tracelite.exporter import InMemoryExporter
from tracelite.span import StatusCode, Resource
from tracelite.context import get_current_span, set_current_span, restore_span


class TestTraceDecorator:
    def setup_method(self):
        self.exporter = InMemoryExporter()
        configure_decorator_tracing(
            processors=[SimpleSpanProcessor(self.exporter)],
            resource=Resource(attributes={"service.name": "test"}),
        )

    def teardown_method(self):
        # Clean up any lingering context
        configure_decorator_tracing(processors=[], resource=None)
        set_current_span(None)

    def test_basic_decorator(self):
        @trace
        def my_function():
            return 42

        result = my_function()
        assert result == 42
        assert self.exporter.span_count == 1
        span = self.exporter.get_spans()[0]
        assert "my_function" in span.name
        assert span.status.code == StatusCode.OK

    def test_custom_name(self):
        @trace(name="custom-operation")
        def my_function():
            pass

        my_function()
        span = self.exporter.get_spans()[0]
        assert span.name == "custom-operation"

    def test_with_attributes(self):
        @trace(attributes={"env": "test", "version": "1.0"})
        def my_function():
            pass

        my_function()
        span = self.exporter.get_spans()[0]
        assert span.attributes["env"] == "test"

    def test_record_args(self):
        @trace(record_args=True)
        def add(x, y):
            return x + y

        add(3, 4)
        span = self.exporter.get_spans()[0]
        assert "arg.x" in span.attributes
        assert "arg.y" in span.attributes

    def test_exception_recording(self):
        @trace
        def failing():
            raise ValueError("oops")

        with pytest.raises(ValueError):
            failing()

        span = self.exporter.get_spans()[0]
        assert span.status.code == StatusCode.ERROR
        assert len(span.events) >= 1

    def test_nested_decorators(self):
        @trace
        def outer():
            return inner()

        @trace
        def inner():
            return "done"

        result = outer()
        assert result == "done"
        assert self.exporter.span_count == 2

        spans = self.exporter.get_spans()
        outer_span = next(s for s in spans if "outer" in s.name)
        inner_span = next(s for s in spans if "inner" in s.name)
        assert inner_span.parent_span_id == outer_span.span_id
        assert inner_span.trace_id == outer_span.trace_id

    def test_preserves_function_name(self):
        @trace
        def my_special_function():
            """My docstring."""
            pass

        assert my_special_function.__name__ == "my_special_function"
        assert my_special_function.__doc__ == "My docstring."
