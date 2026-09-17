"""
Stock & Price Synchronizer Engine (Async).
Continuously aligns manual variant stock counts with live supplier availability.
"""

import time
import asyncio
from typing import Optional
from resellauth.core.config import ResellConfig
from resellauth.supplier.client import SupplierClient
from resellauth.shop.client import ShopClient


class StockSynchronizer:
    def __init__(self, config: ResellConfig):
        self.config = config
        self.supplier = SupplierClient(
            target_domain=config.target_shop_domain,
            target_shop_id=config.target_shop_id
        )
        self.shop = ShopClient(
            shop_id=config.my_shop_id,
            api_key=config.my_api_key
        )

    async def close(self):
        await self.supplier.close()
        await self.shop.close()

    async def sync_once(self) -> None:
        """Executes a single async synchronization pass across all paired products."""
        print(f"\n[*] Starting async stock sync pass at {time.strftime('%Y-%m-%d %H:%M:%S')}...")

        for pairing in self.config.pairings:
            try:
                print(f"[*] Fetching target product '{pairing.target_product_slug}'...")
                target_data = await self.supplier.fetch_product_variants(pairing.target_product_slug)
                target_variants = {v["id"]: v for v in target_data.get("variants", [])}

                for mapping in pairing.variant_mappings:
                    target_var = target_variants.get(mapping.target_variant_id)
                    if not target_var:
                        print(f"[-] Target variant {mapping.target_variant_id} not found in supplier inventory.")
                        continue

                    target_stock = int(target_var.get("stock", 0))
                    target_price = float(target_var.get("price", 0.0))

                    print(f"    - Variant {mapping.my_variant_id} <- Supplier {mapping.target_variant_id} ({target_var.get('name')})")
                    print(f"      Live Stock: {target_stock} | Base Price: ${target_price:.2f}")

                    # Update stock on your SellAuth storefront
                    success = await self.shop.update_variant_stock(
                        product_id=pairing.my_product_id,
                        variant_id=mapping.my_variant_id,
                        stock=target_stock
                    )
                    if success:
                        print(f"      [✓] Updated stock to {target_stock} on variant {mapping.my_variant_id}")

                    # Optionally sync price with markup
                    if mapping.auto_sync_price:
                        markup = mapping.markup_percent
                        new_price = round(target_price * (1.0 + (markup / 100.0)), 2)
                        await self.shop.update_product_variant_price(
                            product_id=pairing.my_product_id,
                            variant_id=mapping.my_variant_id,
                            new_price=new_price
                        )
                        print(f"      [✓] Updated price to ${new_price:.2f} (+{markup}%)")

            except Exception as e:
                print(f"[-] Sync failure on '{pairing.target_product_slug}': {e}")

        print("[*] Stock sync pass completed.")

    async def run_forever(self, interval_seconds: Optional[int] = None) -> None:
        """Asynchronous background loop."""
        interval = interval_seconds or self.config.sync_interval_seconds
        while True:
            await self.sync_once()
            await asyncio.sleep(interval)


if __name__ == "__main__":
    async def _test():
        print("[sync/engine.py] Testing StockSynchronizer load:")
        cfg = ResellConfig(
            my_shop_id=1,
            my_shop_domain="demo.mysellauth.com",
            my_api_key="sec_dummy",
            my_webhook_secret="wh_dummy",
            target_shop_domain="supplier.mysellauth.com",
            target_shop_id=1,
        )
        syncer = StockSynchronizer(cfg)
        print("Synchronizer initialized.")
        await syncer.close()
    asyncio.run(_test())
