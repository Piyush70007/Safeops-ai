def test_get_product_returns_seeded_catalogue(services):
    body = services["inventory"].get("/inventory/GEAR-42").json()
    assert body["name"] == "Gear wheel 42T"
    assert body["price_cents"] == 1999


def test_reserve_reduces_stock_and_returns_price(services):
    inv = services["inventory"]
    before = inv.get("/inventory/PUMP-7").json()["stock"]
    body = inv.post("/inventory/reserve", json={"sku": "PUMP-7", "quantity": 3}).json()
    assert body == {
        "sku": "PUMP-7",
        "reserved": 3,
        "remaining": before - 3,
        "unit_price_cents": 45900,
    }


def test_cannot_reserve_more_than_stock(services):
    response = services["inventory"].post(
        "/inventory/reserve", json={"sku": "PUMP-7", "quantity": 26}
    )
    assert response.status_code == 409
    assert services["inventory"].get("/inventory/PUMP-7").json()["stock"] == 25


def test_last_item_can_be_reserved(services):
    inv = services["inventory"]
    assert inv.post("/inventory/reserve", json={"sku": "PUMP-7", "quantity": 25}).status_code == 200
    assert inv.get("/inventory/PUMP-7").json()["stock"] == 0


def test_unknown_product_is_404(services):
    assert services["inventory"].get("/inventory/NOPE-1").status_code == 404
    response = services["inventory"].post(
        "/inventory/reserve", json={"sku": "NOPE-1", "quantity": 1}
    )
    assert response.status_code == 404


def test_release_returns_stock(services):
    inv = services["inventory"]
    inv.post("/inventory/reserve", json={"sku": "BOLT-M8", "quantity": 100})
    inv.post("/inventory/release", json={"sku": "BOLT-M8", "quantity": 100})
    assert inv.get("/inventory/BOLT-M8").json()["stock"] == 10000


def test_invalid_input_is_rejected(services):
    inv = services["inventory"]
    assert inv.post("/inventory/reserve", json={"sku": "bad sku", "quantity": 1}).status_code == 422
    assert inv.post("/inventory/reserve", json={"sku": "GEAR-42", "quantity": 0}).status_code == 422
