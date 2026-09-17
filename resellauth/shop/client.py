"""
Your Storefront Async API Client.
Interfaces with your SellAuth dashboard API (Bearer Token)
to update product stock counts, deliverables types, and variant pricing.
"""

from typing import Dict, Any, Optional
from curl_cffi.requests import AsyncSession


class ShopClient:
    def __init__(self, shop_id: int, api_key: str, base_url: str = "https://api.sellauth.com/v1", impersonate: str = "chrome124"):
        self.shop_id = shop_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.impersonate = impersonate
        self.session: Optional[AsyncSession] = None
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _get_session(self) -> AsyncSession:
        if self.session is None:
            self.session = AsyncSession(impersonate=self.impersonate)
        return self.session

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def get_product(self, product_id: int) -> Dict[str, Any]:
        """Fetches product details from your shop."""
        s = await self._get_session()
        url = f"{self.base_url}/shops/{self.shop_id}/products/{product_id}"
        resp = await s.get(url, headers=self.headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    async def ensure_deliverables_type_dynamic(self, product_id: int) -> bool:
        """Ensures product is set to 'dynamic' so manual stock count endpoint works."""
        s = await self._get_session()
        url = f"{self.base_url}/shops/{self.shop_id}/products/bulk-update/deliverables-type"
        resp = await s.put(url, headers=self.headers, json={"product_ids": [product_id], "deliverables_type": "dynamic"})
        return resp.status_code == 200

    async def update_variant_stock(self, product_id: int, variant_id: int, stock: int) -> bool:
        """
        Updates the manual stock count of a dynamic or service variant.
        Endpoint: PUT /v1/shops/{shopId}/products/{productId}/stock/{variantId}
        """
        s = await self._get_session()
        url = f"{self.base_url}/shops/{self.shop_id}/products/{product_id}/stock/{variant_id}"
        payload = {"stock": int(stock)}
        resp = await s.put(url, headers=self.headers, json=payload, timeout=15)
        if resp.status_code in [200, 204]:
            return True
        elif resp.status_code == 400 and "must be \"service\" or \"dynamic\"" in resp.text:
            # Auto switch to dynamic delivery and retry
            await self.ensure_deliverables_type_dynamic(product_id)
            resp2 = await s.put(url, headers=self.headers, json=payload, timeout=15)
            if resp2.status_code in [200, 204]:
                return True
        resp.raise_for_status()
        return False

    async def update_product_variant_price(
        self, product_id: int, variant_id: int, new_price: float
    ) -> bool:
        """
        Updates the price of a specific variant on your product.
        """
        s = await self._get_session()
        current = await self.get_product(product_id)
        prod = current.get("product") or current

        variants = prod.get("variants", [])
        modified = False
        for v in variants:
            if v.get("id") == variant_id:
                v["price"] = f"{new_price:.2f}"
                modified = True
                break

        if not modified:
            raise ValueError(f"Variant ID {variant_id} not found on your product {product_id}")

        url = f"{self.base_url}/shops/{self.shop_id}/products/{product_id}/update"
        payload = {
            "type": prod.get("type", "variant"),
            "name": prod.get("name"),
            "path": prod.get("path"),
            "description": prod.get("description"),
            "currency": prod.get("currency", "USD"),
            "visibility": prod.get("visibility", "public"),
            "deliverables_type": prod.get("deliverables_type", "dynamic"),
            "variants": variants,
        }
        resp = await s.put(url, headers=self.headers, json=payload, timeout=15)
        resp.raise_for_status()
        return True
