import pytest

from app.models import MovementType, POStatus
from app.services import counts, inventory, purchasing
from app.services.inventory import InventoryError


def test_negative_stock_is_rejected(session):
    product = inventory.find_product(session, "ELC-1004")  # seeded as out of stock
    with pytest.raises(InventoryError, match="Insufficient stock"):
        inventory.adjust_stock(session, product.id, -1, type=MovementType.SALE)


def test_find_product_is_case_insensitive(session):
    assert inventory.find_product(session, "acc-2002").sku == "ACC-2002"
    assert inventory.find_product(session, "Braided USB-C Cable 2m").sku == "ACC-2002"


def test_transfer_moves_stock_between_warehouses(session):
    product = inventory.find_product(session, "ACC-2002")
    before = {w["code"]: w["quantity"] for w in inventory.stock_by_warehouse(session, product.id)}
    source = max(before, key=before.get)
    target = next(code for code in ("MAIN", "NORTH", "SOUTH") if code != source)
    total = inventory.on_hand(session, product.id)
    inventory.transfer_stock(session, product.id, 5, source, target)
    after = {w["code"]: w["quantity"] for w in inventory.stock_by_warehouse(session, product.id)}
    assert after[source] == before[source] - 5
    assert after[target] == before.get(target, 0) + 5
    assert inventory.on_hand(session, product.id) == total


def test_purchase_order_lifecycle(session):
    product = inventory.find_product(session, "SPT-6003")
    po = purchasing.create_po(session, [(product, 7)], created_by="test")
    assert po.status == POStatus.DRAFT
    assert po.lines[0].quantity == max(7, product.min_order_qty)  # MOQ enforced
    with pytest.raises(InventoryError):
        purchasing.set_status(session, po, POStatus.RECEIVED)  # must be ordered first
    purchasing.set_status(session, po, POStatus.APPROVED)
    purchasing.set_status(session, po, POStatus.ORDERED)
    before = inventory.on_hand(session, product.id)
    purchasing.set_status(session, po, POStatus.RECEIVED)
    assert inventory.on_hand(session, product.id) == before + po.lines[0].quantity
    with pytest.raises(InventoryError):
        purchasing.set_status(session, po, POStatus.CANCELLED)


def test_cycle_count_posts_variances(session):
    count = counts.create_count(session, "MAIN", "all")
    line = count.lines[0]
    counts.record_counts(session, count, {line.id: line.expected + 3})
    before = inventory.on_hand(session, line.product_id)
    counts.post_count(session, count)
    summary = counts.count_summary(session, count)
    assert summary["status"] == "posted" and summary["net_variance_units"] == 3
    assert inventory.on_hand(session, line.product_id) == before + 3
