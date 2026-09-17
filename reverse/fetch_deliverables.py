"""
SellAuth Deliverables Polling Reference Implementation.
Polls status and extracts line items using generic mock parameters.
"""

import time
from typing import Dict, Any, List
from curl_cffi import requests


class DeliverablesPollingReference:
    def __init__(self, shop_domain: str = "supplier.mysellauth.com", impersonate: str = "chrome124"):
        self.shop_domain = shop_domain
        self.base_url = "https://api-internal-3.sellauth.com"
        self.session = requests.Session(impersonate=impersonate)
        self.headers = {
            "Accept": "application/json",
            "Origin": f"https://{shop_domain}",
            "Referer": f"https://{shop_domain}/",
        }

    def get_minimal_status(self, unique_id: str) -> Dict[str, Any]:
        """Polls lightweight status endpoint."""
        url = f"{self.base_url}/v1/checkout/{unique_id}/minimal"
        resp = self.session.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def get_full_invoice(self, unique_id: str) -> Dict[str, Any]:
        """Fetches complete invoice with delivered arrays."""
        url = f"{self.base_url}/v1/checkout/{unique_id}/full"
        resp = self.session.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def extract_deliverables(self, invoice_data: Dict[str, Any]) -> List[str]:
        items = invoice_data.get("invoice", {}).get("items", [])
        deliverables = []
        for item in items:
            deliverables.extend(item.get("delivered", []))
        return deliverables


if __name__ == "__main__":
    print("[reverse/fetch_deliverables.py] Deliverables polling reference loaded.")
