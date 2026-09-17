"""
Configuration models and disk loader for resellauth.
"""

import os
import json
from typing import List, Optional
from pydantic import BaseModel, Field


class VariantMapping(BaseModel):
    my_variant_id: int
    target_variant_id: int
    markup_percent: float = 0.0
    auto_sync_price: bool = False
    min_quantity: int = 1


class ProductPairing(BaseModel):
    my_product_id: int
    target_product_id: int
    target_product_slug: str
    target_product_url: str
    variant_mappings: List[VariantMapping] = Field(default_factory=list)


class LTCWalletConfig(BaseModel):
    mode: str = "manual_rpc"  # "manual_rpc", "electrum_rpc", "core_rpc"
    rpc_url: Optional[str] = None
    rpc_user: Optional[str] = None
    rpc_password: Optional[str] = None
    auto_pay: bool = False
    max_auto_pay_usd: float = 25.0


class ResellConfig(BaseModel):
    # Your store credentials
    my_shop_id: int
    my_shop_domain: str
    my_api_key: str
    my_webhook_secret: str

    # Target supplier
    target_shop_domain: str
    target_shop_id: int

    # Product mappings
    pairings: List[ProductPairing] = Field(default_factory=list)

    # Fulfillment & LTC middleman
    buyer_email_override: Optional[str] = "dropreseller@deliveries.internal"
    ltc: LTCWalletConfig = Field(default_factory=LTCWalletConfig)

    # Background sync & Server settings
    sync_interval_seconds: int = 120
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    @classmethod
    def load(cls, path: str = "config.json") -> "ResellConfig":
        if not os.path.exists(path):
            raise FileNotFoundError(f"Configuration '{path}' not found. Run 'resellauth setup' first.")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)

    def save(self, path: str = "config.json") -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))


if __name__ == "__main__":
    print("[config.py] Module test:")
    cfg = ResellConfig(
        my_shop_id=1,
        my_shop_domain="test.mysellauth.com",
        my_api_key="sec_test",
        my_webhook_secret="wh_test",
        target_shop_domain="supplier.mysellauth.com",
        target_shop_id=1,
    )
    print("Default schema initialized successfully.")
