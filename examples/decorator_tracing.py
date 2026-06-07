"""
Decorator-based tracing example.

Shows how to use @trace for zero-boilerplate instrumentation.
"""

import time
from tracelite.decorators import trace, configure_decorator_tracing
from tracelite.processor import SimpleSpanProcessor
from tracelite.exporter import ConsoleExporter, InMemoryExporter
from tracelite.span import Resource
from tracelite.visualizer import render_span_tree


def main():
    exporter = InMemoryExporter()
    configure_decorator_tracing(
        processors=[
            SimpleSpanProcessor(ConsoleExporter(colored=True)),
            SimpleSpanProcessor(exporter),
        ],
        resource=Resource(attributes={"service.name": "order-service"}),
    )

    # Call the traced function
    result = process_order("ord_789", items=["widget-a", "widget-b"], quantity=3)
    print(f"\nOrder result: {result}")

    # Visualize
    spans = [s.to_dict() for s in exporter.get_spans()]
    print("\n" + render_span_tree(spans))


@trace(name="process_order", record_args=True)
def process_order(order_id: str, items: list, quantity: int) -> dict:
    validate_inventory(items)
    total = calculate_total(items, quantity)
    charge_payment(order_id, total)
    return {"order_id": order_id, "total": total, "status": "confirmed"}


@trace(record_args=True)
def validate_inventory(items: list):
    time.sleep(0.005)
    for item in items:
        check_stock(item)


@trace(record_args=True)
def check_stock(item: str):
    time.sleep(0.002)


@trace
def calculate_total(items: list, quantity: int) -> float:
    time.sleep(0.003)
    return len(items) * quantity * 9.99


@trace(attributes={"payment.provider": "stripe"})
def charge_payment(order_id: str, amount: float):
    time.sleep(0.010)


if __name__ == "__main__":
    main()
