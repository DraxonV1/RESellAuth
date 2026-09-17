"""
SellAuth Pure Request-Based Checkout & Invoice Generator Reference.
Demonstrates the reverse-engineered flow without browser overhead.
Uses sanitized mock/example parameters.
"""

import hashlib
import json
import base64
import time
from curl_cffi import requests


def solve_altcha(challenge_data: dict) -> str:
    """Solve Altcha SHA-256 Proof-of-Work challenge."""
    algorithm = challenge_data["algorithm"]
    challenge = challenge_data["challenge"]
    salt = challenge_data["salt"]
    signature = challenge_data["signature"]
    maxnumber = challenge_data.get("maxnumber", 1000000)

    start_time = time.time()
    for num in range(maxnumber + 1):
        test_str = salt + str(num)
        h = hashlib.sha256(test_str.encode("utf-8")).hexdigest()
        if h == challenge:
            took = int((time.time() - start_time) * 1000)
            payload = {
                "algorithm": algorithm,
                "challenge": challenge,
                "number": num,
                "salt": salt,
                "signature": signature,
                "took": took,
            }
            raw_json = json.dumps(payload, separators=(",", ":"))
            return base64.b64encode(raw_json.encode("utf-8")).decode("utf-8")
    raise ValueError("Altcha PoW solution not found within maxnumber range")


class SellAuthReferenceClient:
    def __init__(self, shop_domain="supplier.mysellauth.com", shop_id=10001, impersonate="chrome124"):
        self.shop_domain = shop_domain
        self.shop_id = shop_id
        self.base_url = "https://api-internal-3.sellauth.com"
        self.session = requests.Session(impersonate=impersonate)
        self.headers = {
            "Accept": "application/json",
            "Origin": f"https://{shop_domain}",
            "Referer": f"https://{shop_domain}/",
        }

    def get_altcha_token(self) -> str:
        """Fetch and solve Altcha challenge."""
        resp = self.session.get(f"{self.base_url}/v1/altcha", headers=self.headers)
        resp.raise_for_status()
        return solve_altcha(resp.json())

    def create_checkout(self, product_id: int, variant_id: int, quantity: int) -> str:
        """Create checkout and return unique invoice hash."""
        altcha_token = self.get_altcha_token()
        payload = {
            "cart": [
                {
                    "productId": product_id,
                    "variantId": variant_id,
                    "quantity": quantity,
                }
            ],
            "currency": "USD",
            "shopId": str(self.shop_id),
            "source": "storefront",
            "altcha": altcha_token,
        }
        resp = self.session.post(
            f"{self.base_url}/v1/checkout",
            headers={**self.headers, "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        checkout_url = data["url"]
        unique_id = checkout_url.rstrip("/").split("/")[-1]
        return unique_id

    def get_checkout_full(self, unique_id: str) -> dict:
        """Fetch complete checkout and shop payment gateway info."""
        resp = self.session.get(
            f"{self.base_url}/v1/checkout/{unique_id}/full",
            headers=self.headers,
        )
        resp.raise_for_status()
        return resp.json()

    def set_payment_method(self, unique_id: str, email: str, payment_method_id: int) -> dict:
        """Set payment gateway (e.g. LTC) and delivery email via PUT."""
        altcha_token = self.get_altcha_token()
        payload = {
            "email": email,
            "payment_method_id": payment_method_id,
            "altcha": altcha_token,
            "terms": True,
            "newsletter": False,
        }
        resp = self.session.put(
            f"{self.base_url}/v1/checkout/{unique_id}",
            headers={**self.headers, "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    print("[reverse/sellauth_pure_req.py] Reference implementation module loaded.")
