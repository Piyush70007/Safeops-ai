def authorize(client, amount=1000, token="tok_visa_ok"):  # noqa: S107 - test token, not a secret
    body = {"order_id": "ORD-0123456789AB", "amount_cents": amount, "card_token": token}
    return client.post("/payments/authorize", json=body)


def test_valid_payment_is_approved(services):
    response = authorize(services["payments"])
    assert response.status_code == 201
    assert response.json()["status"] == "APPROVED"


def test_decline_token_is_declined(services):
    assert authorize(services["payments"], token="tok_decline_card").json()["status"] == "DECLINED"


def test_amount_above_limit_is_declined(services):
    assert authorize(services["payments"], amount=100_001).json()["status"] == "DECLINED"


def test_card_token_format_is_enforced(services):
    assert authorize(services["payments"], token="4111111111111111").status_code == 422


def test_payment_can_be_read_back(services):
    payment_id = authorize(services["payments"]).json()["payment_id"]
    assert services["payments"].get(f"/payments/{payment_id}").json()["payment_id"] == payment_id
    assert services["payments"].get("/payments/PAY-UNKNOWN").status_code == 404
