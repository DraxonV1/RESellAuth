# SellAuth Reverse-Engineered Flow & Invoice Specification

Target Domain: `supplier.mysellauth.com`  
Target Product: `/product/example-item`  
API Host: `https://api-internal-3.sellauth.com`  
Shop ID: `10001`  
Customer Email: `buyer@example.com`  

---

## 1. Product & Variant Inventory Architecture

### Product Details
- **Product ID**: `10001`
- **Product Name**: `Sample Digital Goods`
- **Slug / Path**: `example-item`
- **Storefront Technology**: Alpine.js SPA embedded into server-rendered HTML template.

### Variants Matrix (Example)
| Variant ID | Variant Name | Price (USD) | Stock | Min / Max Qty | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `20001` | `Tier 1 Digital Account` | $0.07 | 0 | 1 / - | Out of stock |
| `20002` | `Tier 2 Digital Account` | $0.12 | 250 | 7 / 250 | In Stock (Selected) |

---

## 2. Checkout Creation & PoW Captcha (Altcha)

SellAuth uses **Altcha Proof-of-Work (PoW)** challenges to prevent bot checkouts.

### Step 2.1: Altcha Challenge
- **Endpoint**: `GET https://api-internal-3.sellauth.com/v1/altcha`
- **Response**:
  ```json
  {
    "algorithm": "SHA-256",
    "challenge": "731c79a588dd919078e99dacec38dd5a9646dcf0e9d5c2d7dd0ca6087a157686",
    "maxnumber": 10000,
    "salt": "15ba683f01819fbe4caa13bb?expires=1789644115",
    "signature": "a05e3b3253a97dbd71418dcfaa8fc5335971393055e2b9ac07e6d8ea1e3b5ae9"
  }
  ```
- **PoW Solver**: Client iterates numbers `0` to `maxnumber` until `SHA256(salt + number) == challenge`.

### Step 2.2: Cart Checkout POST
- **Endpoint**: `POST https://api-internal-3.sellauth.com/v1/checkout`
- **Headers**:
  ```http
  Accept: application/json
  Content-Type: application/json
  Origin: https://supplier.mysellauth.com
  Referer: https://supplier.mysellauth.com/product/example-item
  ```
- **Request Body**:
  ```json
  {
    "cart": [
      {
        "productId": 10001,
        "variantId": 20002,
        "quantity": 7
      }
    ],
    "currency": "USD",
    "shopId": "10001",
    "source": "storefront",
    "altcha": "<base64_encoded_solution_payload>"
  }
  ```
- **Response**:
  ```json
  {
    "url": "https://supplier.mysellauth.com/checkout/01ce2bfe62f9e-00000100001"
  }
  ```

---

## 3. Checkout SPA & Payment Gateway Selection

The checkout page is a React SPA running at `/checkout/{unique_id}`.

### Step 3.1: Fetch Full Invoice Snapshot
- **Endpoint**: `GET https://api-internal-3.sellauth.com/v1/checkout/{unique_id}/full`
- Returns cart contents, shop gateway configuration (LTC, BTC, Stripe, Customer Balance), pricing calculations, and tax.

### Step 3.2: Select Payment Method & Finalize Invoice
- User enters delivery email: `buyer@example.com`
- User selects payment method: `LTC` (Litecoin)
- Altcha verification completed for checkout form.
- **Endpoint**: `PUT https://api-internal-3.sellauth.com/v1/checkout/{unique_id}`
- **Form Data**:
  ```json
  {
    "email": "buyer@example.com",
    "payment_method_id": 30001,
    "terms": true,
    "newsletter": false,
    "altcha": "<altcha_payload>"
  }
  ```

---

## 4. Active Invoice & Real-time Crypto State

### Invoice Metadata (Example)
- **Invoice ID**: `100001`
- **Unique Invoice Hash**: `01ce2bfe62f9e-00000100001`
- **Initial Status**: `pending`
- **Currency**: `USD`
- **Total USD Price**: `$0.84` ($0.12 x 7 units)
- **Payment Gateway**: `LTC`
- **Assigned Litecoin Address**: `ltc1qexampleaddress000000000000000000000000000`
- **Exact Crypto Amount**: `0.01592417 LTC`
- **Litecoin URI**: `litecoin:ltc1qexampleaddress000000000000000000000000000?amount=0.01592417`

---

## 5. Live Polling & Deliverables Architecture

### Polling Mechanism
The checkout frontend polls the lightweight status endpoint every ~4-5 seconds:
- **Endpoint**: `GET https://api-internal-3.sellauth.com/v1/checkout/01ce2bfe62f9e-00000100001/minimal`

```json
{
  "id": 100001,
  "unique_id": "01ce2bfe62f9e-00000100001",
  "status": "completed",
  "paid": "0.84",
  "completed_at": "2026-02-01T12:00:00.000000Z"
}
```

### Fulfillment & Deliverables Unlocking
Upon status transitioning to `completed`:
1. The frontend immediately triggers a re-fetch of `/v1/checkout/{unique_id}/full`.
2. `items[0].status` transitions from `"pending"` to `"completed"`.
3. `items[0].delivered_count` updates to the purchased quantity.
4. `items[0].delivered` array unlocks the accounts in `EMAIL:PASSWORD:TOKEN` or serial key format.
5. Example delivered format:
   ```text
   user1@example.com:Password123!:SAMPLE_DISCORD_TOKEN_HERE_AAAA
   user2@example.com:Password123!:SAMPLE_DISCORD_TOKEN_HERE_BBBB
   user3@example.com:Password123!:SAMPLE_DISCORD_TOKEN_HERE_CCCC
   ```
