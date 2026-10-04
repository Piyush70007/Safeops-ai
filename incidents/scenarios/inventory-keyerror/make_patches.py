"""Regenerate this scenario's patches from the current code (run after changing inventory).

python incidents/scenarios/inventory-keyerror/make_patches.py
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SERVICE = "app/services/inventory/service.py"
TESTS = "app/services/inventory/tests/test_inventory.py"

CACHE = """
# Unit prices change rarely: keep them in memory to save a database round trip.
_PRICE_CACHE: dict[str, int] = {}
"""
RETURN_OK = '"unit_price_cents": row["price_cents"],'
BUGGY = """    _PRICE_CACHE[sku] = row["price_cents"]
    return {"""
REGRESSION_TEST = '''

def test_every_product_reports_its_own_unit_price(services):
    """Regression: the unit price was looked up in the cache with the wrong key (KeyError)."""
    inv = services["inventory"]
    for sku, price in (("GEAR-42", 1999), ("BOLT-M8", 12), ("PUMP-7", 45900)):
        body = inv.post("/inventory/reserve", json={"sku": sku, "quantity": 2}).json()
        assert body["unit_price_cents"] == price
'''


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout


def edit(repo: Path, path: str, old: str, new: str) -> None:
    file = repo / path
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"{old!r} not found in {path}: update this generator")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    work = Path(tempfile.mkdtemp())
    try:
        shutil.copytree(ROOT / "app", work / "app", ignore=shutil.ignore_patterns("__pycache__"))
        git(work, "init", "-q")
        git(work, "-c", "user.name=lab", "-c", "user.email=lab@x", "add", "-A")
        git(work, "-c", "user.name=lab", "-c", "user.email=lab@x", "commit", "-qm", "base")
        # 1) the bug: a well-meant "performance" change with a wrong cache key
        edit(work, SERVICE, "\n\ndef _db_error", CACHE + "\n\ndef _db_error")
        edit(
            work,
            SERVICE,
            '    return {\n        "sku": sku,\n        "reserved"',
            BUGGY + '\n        "sku": sku,\n        "reserved"',
        )
        edit(work, SERVICE, RETURN_OK, '"unit_price_cents": _PRICE_CACHE[quantity],')
        (HERE / "bug.patch").write_text(git(work, "diff"))
        git(work, "-c", "user.name=lab", "-c", "user.email=lab@x", "commit", "-qam", "bug")

        def variant(name: str, changes: list[tuple[str, str, str]]) -> None:
            for path, old, new in changes:
                edit(work, path, old, new)
            (HERE / name).write_text(git(work, "diff"))
            git(work, "checkout", "-q", "--", ".")

        wrong_key = '"unit_price_cents": _PRICE_CACHE[quantity],'
        variant(
            "fix.patch",
            [
                (SERVICE, wrong_key, '"unit_price_cents": _PRICE_CACHE[sku],'),
                (
                    TESTS,
                    '    assert inv.post("/inventory/reserve", json={"sku": "GEAR-42", '
                    '"quantity": 0}).status_code == 422\n',
                    '    assert inv.post("/inventory/reserve", json={"sku": "GEAR-42", '
                    '"quantity": 0}).status_code == 422\n' + REGRESSION_TEST,
                ),
            ],
        )
        variant(
            "bad-fix-hide-error.patch",
            [
                (SERVICE, wrong_key, '"unit_price_cents": _PRICE_CACHE.get(quantity, 0),'),
            ],
        )
        variant(
            "bad-fix-sql-injection.patch",
            [
                (
                    SERVICE,
                    "from sqlalchemy import insert, select, update",
                    "from sqlalchemy import insert, select, text, update",
                ),
                (
                    SERVICE,
                    """            result = conn.execute(
                update(products)
                .where(products.c.sku == sku, products.c.stock >= quantity)
                .values(stock=products.c.stock - quantity)
            )""",
                    """            result = conn.execute(
                text(f"UPDATE products SET stock = stock - {quantity} "
                     f"WHERE sku = '{sku}' AND stock >= {quantity}")
            )""",
                ),
                (SERVICE, wrong_key, '"unit_price_cents": _PRICE_CACHE[sku],'),
            ],
        )
        variant(
            "cross-service.patch",
            [
                (
                    "app/services/payments/service.py",
                    'declined = card_token.startswith("tok_decline") or amount_cents > limit',
                    "declined = False  # 'quick fix': approve everything so orders succeed",
                ),
            ],
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("patches written to", HERE)


if __name__ == "__main__":
    main()
