from sqlmodel import select

from app.hooks import webhooks
from app.hooks.builtin import evaluate_alerts
from app.hooks.bus import EventBus, EventHook, toggles
from app.models import Alert, MovementType
from app.services import inventory


def test_bus_patterns_isolation_and_toggles(client):
    bus = EventBus()
    seen: list[str] = []
    bus.register(EventHook("stock_only", "stock.*", lambda e: seen.append(f"stock:{e.type}")))
    bus.register(EventHook("alts", "po.created|po.received", lambda e: seen.append(f"po:{e.type}")))
    bus.register(EventHook("boom", "*", lambda e: 1 / 0))  # a broken hook must not break emit()

    bus.emit("stock.low", {})
    bus.emit("po.received", {})
    bus.emit("po.cancelled", {})
    assert seen == ["stock:stock.low", "po:po.received"]

    toggles.set_enabled("stock_only", False)
    try:
        bus.emit("stock.out", {})
        assert seen[-1] == "po:po.received"
    finally:
        toggles.set_enabled("stock_only", True)


def test_webhook_signatures_roundtrip():
    body = b'{"type":"stock.low"}'
    signature = webhooks.sign("s3cret", body)
    assert signature.startswith("sha256=")
    assert webhooks.verify("s3cret", body, signature)
    assert not webhooks.verify("wrong", body, signature)


def test_alert_engine_raises_and_resolves_stock_alerts(session):
    product = inventory.find_product(session, "HOM-4005")
    qty = inventory.on_hand(session, product.id)
    inventory.adjust_stock(session, product.id, -qty, reason="test drain")
    evaluate_alerts(session, [product.id], emit=False)
    open_kinds = {a.kind for a in session.exec(select(Alert).where(Alert.product_id == product.id, Alert.resolved == False))}  # noqa: E712
    assert "stockout" in open_kinds

    inventory.adjust_stock(session, product.id, qty, reason="test restore", type=MovementType.RECEIPT)
    evaluate_alerts(session, [product.id], emit=False)
    still_open = session.exec(
        select(Alert).where(Alert.product_id == product.id, Alert.resolved.is_(False), Alert.kind == "stockout")
    ).all()
    assert not still_open
