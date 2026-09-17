"""
FastAPI Dynamic Delivery Webhook Gateway (Async).
Verifies HMAC-SHA256 signatures, initiates supplier checkout,
dispatches LTC middleman payment, and delivers lines to SellAuth.
"""

import hmac
import hashlib
import json
import logging
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Header, Response

from resellauth.core.config import ResellConfig
from resellauth.supplier.client import SupplierClient
from resellauth.gateway.ltc import LTCGateway

logger = logging.getLogger("resellauth.server")

app = FastAPI(title="ResellAuth Dynamic Delivery Gateway", version="0.1.0")
_config: Optional[ResellConfig] = None
_supplier: Optional[SupplierClient] = None
_ltc_gateway: Optional[LTCGateway] = None


def init_app(config: ResellConfig):
    global _config, _supplier, _ltc_gateway
    _config = config
    _supplier = SupplierClient(
        target_domain=config.target_shop_domain,
        target_shop_id=config.target_shop_id
    )
    _ltc_gateway = LTCGateway(config.ltc)


@app.on_event("shutdown")
async def shutdown_event():
    if _supplier:
        await _supplier.close()
    if _ltc_gateway:
        await _ltc_gateway.close()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "resellauth-dynamic-delivery"}


@app.post("/api/v1/deliver")
async def handle_dynamic_delivery(
    request: Request,
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    """
    SellAuth Dynamic Delivery Handler:
    - Verifies raw body signature using HMAC-SHA256 with my_webhook_secret.
    - Resolves mapped target product & variant.
    - Executes pure-request supplier order.
    - Dispatches LTC payment via middleman gateway.
    - Streams deliverables back with HTTP 200 plain text.
    """
    if not _config or not _supplier or not _ltc_gateway:
        raise HTTPException(status_code=500, detail="Server not initialized with ResellConfig.")

    body_bytes = await request.body()
    if not x_signature:
        raise HTTPException(status_code=401, detail="Missing X-Signature header.")

    expected_signature = hmac.new(
        _config.my_webhook_secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, x_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Malformed JSON: {e}")

    invoice_id = payload.get("id")
    item = payload.get("item", {})
    my_product_id = item.get("product_id")
    my_variant_id = item.get("variant_id")
    quantity = item.get("quantity", 1)
    customer_email = payload.get("email") or _config.buyer_email_override

    print(f"\n[WEBHOOK] Received Dynamic Delivery for Invoice #{invoice_id}")
    print(f"          Product ID: {my_product_id} | Variant ID: {my_variant_id} | Quantity: {quantity}")
    print(f"          Buyer Email: {customer_email}")

    # Map product & variant to target
    target_prod_id = None
    target_var_id = None
    for p in _config.pairings:
        if p.my_product_id == my_product_id:
            target_prod_id = p.target_product_id
            for m in p.variant_mappings:
                if m.my_variant_id == my_variant_id:
                    target_var_id = m.target_variant_id
                    break
            break

    if not target_prod_id or not target_var_id:
        print(f"[-] No target mapping found for Product {my_product_id}, Variant {my_variant_id}")
        raise HTTPException(status_code=400, detail="Unmapped variant in resellauth catalog.")

    try:
        # 1. Initiate checkout on supplier
        checkout_hash = await _supplier.create_checkout(
            product_id=target_prod_id,
            variant_id=target_var_id,
            quantity=quantity
        )
        print(f"[✓] Supplier Checkout: {checkout_hash}")

        # 2. Lock LTC Gateway on supplier
        invoice_info = await _supplier.lock_ltc_gateway(
            unique_id=checkout_hash,
            email=customer_email
        )
        ltc_address = invoice_info["crypto_address"]
        ltc_amount = float(invoice_info["crypto_amount"])
        usd_price = float(invoice_info["price_usd"])

        # 3. Pay via middleman LTC gateway
        await _ltc_gateway.pay_invoice(
            target_address=ltc_address,
            amount_ltc=ltc_amount,
            price_usd=usd_price,
            invoice_id=invoice_info["invoice_id"]
        )

        # 4. Await supplier deliverables
        print("[*] Waiting for supplier confirmation & deliverable unlocking...")
        raw_deliverables = await _supplier.wait_for_deliverables(
            unique_id=checkout_hash,
            timeout_seconds=300,
            poll_interval=4
        )

        if not raw_deliverables:
            raise RuntimeError("Supplier payment verified but deliverables array is empty.")

        print(f"[✓] Received {len(raw_deliverables)} accounts from supplier!")

        # Format line-by-line as required by SellAuth
        response_text = "\n".join(raw_deliverables)
        return Response(content=response_text, media_type="text/plain", status_code=200)

    except Exception as e:
        print(f"[-] Fulfillment failure: {e}")
        raise HTTPException(status_code=500, detail=f"Fulfillment failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    print("[server/app.py] Standalone server launch test on port 8000...")
    cfg = ResellConfig(
        my_shop_id=1,
        my_shop_domain="test.mysellauth.com",
        my_api_key="sec_test",
        my_webhook_secret="wh_test",
        target_shop_domain="supplier.mysellauth.com",
        target_shop_id=1,
    )
    init_app(cfg)
    uvicorn.run(app, host="127.0.0.1", port=8000)
