"""
Supplier Storefront Async Client.
Handles 503 challenge bypass, stock extraction, checkout initiation,
LTC gateway locking, and live deliverable retrieval on the target supplier shop.
"""

import json
import asyncio
from typing import Dict, Any, List, Optional
from curl_cffi.requests import AsyncSession
from resellauth.core.altcha import solve_altcha, solve_sellauth_503


class SupplierClient:
    def __init__(self, target_domain: str, target_shop_id: int = 0, impersonate: str = "chrome124"):
        self.domain = target_domain
        self.shop_id = target_shop_id
        self.api_base = "https://api-internal-3.sellauth.com"
        self.impersonate = impersonate
        self.session: Optional[AsyncSession] = None
        self.headers = {
            "Accept": "application/json",
            "Origin": f"https://{target_domain}",
            "Referer": f"https://{target_domain}/",
        }

    async def _get_session(self) -> AsyncSession:
        if self.session is None:
            self.session = AsyncSession(impersonate=self.impersonate)
        return self.session

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def _ensure_storefront_access(self, url: str) -> str:
        s = await self._get_session()
        resp = await s.get(url, headers={**self.headers, "Accept": "text/html,*/*"})
        if resp.status_code == 503 and "Please wait..." in resp.text:
            solution = await solve_sellauth_503(resp.text)
            if solution:
                c_name, c_val = solution
                s.cookies.set(c_name, c_val, domain=".mysellauth.com")
                resp = await s.get(url, headers={**self.headers, "Accept": "text/html,*/*"})

        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch supplier page {url}: HTTP {resp.status_code}")
        return resp.text

    async def fetch_product_variants(self, product_slug: str) -> Dict[str, Any]:
        """Fetches product page HTML and parses Alpine.js product data."""
        url = f"https://{self.domain}/product/{product_slug}"
        html = await self._ensure_storefront_access(url)

        start_needle = "product: {"
        pos = html.find(start_needle)
        if pos == -1:
            raise RuntimeError(f"Could not find product data in target storefront HTML for '{product_slug}'")

        start = pos + len("product: ")
        brace_count = 0
        end = 0
        for idx, char in enumerate(html[start : start + 50000]):
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    end = idx + 1
                    break

        product_data = json.loads(html[start : start + end])
        return product_data

    async def get_altcha_token(self) -> str:
        s = await self._get_session()
        resp = await s.get(f"{self.api_base}/v1/altcha", headers=self.headers)
        resp.raise_for_status()
        return await solve_altcha(resp.json())

    async def create_checkout(self, product_id: int, variant_id: int, quantity: int) -> str:
        s = await self._get_session()
        token = await self.get_altcha_token()
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
            "altcha": token,
        }
        resp = await s.post(
            f"{self.api_base}/v1/checkout",
            headers={**self.headers, "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        url = resp.json()["url"]
        return url.rstrip("/").split("/")[-1]

    async def get_minimal_status(self, unique_id: str) -> Dict[str, Any]:
        s = await self._get_session()
        resp = await s.get(f"{self.api_base}/v1/checkout/{unique_id}/minimal", headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    async def get_full_checkout(self, unique_id: str) -> Dict[str, Any]:
        s = await self._get_session()
        resp = await s.get(f"{self.api_base}/v1/checkout/{unique_id}/full", headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    async def lock_ltc_gateway(self, unique_id: str, email: str) -> Dict[str, Any]:
        s = await self._get_session()
        full_info = await self.get_full_checkout(unique_id)
        shop_info = full_info.get("shop", {})
        methods = {
            m["type"].upper(): m["id"]
            for m in shop_info.get("payment_methods", [])
        }
        if "LTC" not in methods:
            raise RuntimeError("Supplier shop does not accept LTC payments.")

        ltc_method_id = methods["LTC"]
        altcha_token = await self.get_altcha_token()

        payload = {
            "email": email,
            "payment_method_id": ltc_method_id,
            "altcha": altcha_token,
            "terms": True,
            "newsletter": False,
        }
        resp = await s.put(
            f"{self.api_base}/v1/checkout/{unique_id}",
            headers={**self.headers, "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()

        updated = (await self.get_full_checkout(unique_id))["invoice"]
        return {
            "invoice_id": updated.get("id"),
            "unique_id": updated.get("unique_id"),
            "status": updated.get("status"),
            "price_usd": updated.get("price_usd"),
            "crypto_address": updated.get("crypto_address"),
            "crypto_amount": updated.get("crypto_amount"),
            "uri": f"litecoin:{updated.get('crypto_address')}?amount={updated.get('crypto_amount')}",
        }

    async def wait_for_deliverables(
        self, unique_id: str, timeout_seconds: int = 400, poll_interval: int = 4
    ) -> List[str]:
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout_seconds:
            status = await self.get_minimal_status(unique_id)
            if status.get("status") in ["completed", "paid"] or status.get("completed_at"):
                full = await self.get_full_checkout(unique_id)
                items = full.get("invoice", {}).get("items", [])
                deliverables = []
                for item in items:
                    deliverables.extend(item.get("delivered", []))
                return deliverables
            await asyncio.sleep(poll_interval)

        raise TimeoutError(f"Supplier invoice {unique_id} was not marked paid within {timeout_seconds}s")


if __name__ == "__main__":
    async def _test():
        print("[supplier/client.py] Testing live inspect...")
        cli = SupplierClient("supplier.mysellauth.com")
        data = await cli.fetch_product_variants("sample-item")
        print(f"Target Product: {data.get('name')} (ID: {data.get('id')})")
        for v in data.get("variants", []):
            print(f"  {v.get('id')}: {v.get('name')} | Stock: {v.get('stock')}")
        await cli.close()

    asyncio.run(_test())
