# RESellAuth

[![PyPI version](https://img.shields.io/pypi/v/resellauth.svg)](https://pypi.org/project/resellauth/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Autonomous SellAuth Drop-Reseller Engine & Gateway**

`resellauth` synchronizes stock between a target supplier shop on SellAuth and your own storefront, handles user purchases through SellAuth Dynamic Delivery, automatically buys from the target store via request-based checkout (Altcha PoW solver + middleman LTC wallet settlement), and fulfills the buyer's order in real-time.

Zero dependency on SellAuth's official reseller API.

---

## Features

- **Pure Request-Based Target Flow**: Operates with `curl_cffi` TLS Chrome impersonation. Bypasses browser overhead entirely.
- **Built-in Native Altcha PoW Solver**: Solves SHA-256 number-hunt challenges in under 150ms in native Python.
- **Storefront 503 Anti-DDoS Bypass**: Native solver for SellAuth's JavaScript SHA-1 PoW challenge.
- **Live Stock Sync Engine**: Polls target variant stock and updates your SellAuth dynamic/service product stock automatically.
- **Middleman LTC Gateway**:
  - Automatically submits target order for exact quantity requested.
  - Generates LTC invoice on target.
  - Native On-Chain Signing: Signs SegWit BIP-143 transactions locally using your private key (WIF) and broadcasts to the network. Also supports Electrum-LTC / Core RPC.
- **SellAuth Dynamic Delivery Handler**:
  - Validates `X-Signature` HMAC-SHA256 headers using your webhook secret.
  - Delivers `EMAIL:PASSWORD:TOKEN` credentials line-by-line formatted exactly as required by SellAuth (HTTP 200 plain text lines).
- **Interactive CLI & Cross-Platform SQLite Storage**:
  - Run `resellauth setup` to configure store pairings, products, wallets, and sync intervals.
  - All configurations stored locally in `~/.resellauth/settings.db`.

---

## Installation

```bash
pip install resellauth
```

Or clone and install in editable mode:
```bash
git clone https://github.com/DraxonV1/RESellAuth.git
cd RESellAuth
pip install -e .
```

---

## Quick Start

### 1. Interactive Setup Wizard
Run the CLI wizard to configure your shop, target supplier, products, and LTC wallet:
```bash
resellauth setup
```
This prompts for:
- Your SellAuth API key & Shop ID
- Target Shop Domain & Product URL
- Product & Variant ID pairings
- Webhook HMAC secret for Dynamic Delivery
- LTC wallet payout method (private key / RPC / manual)

### 2. Start Stock Synchronizer & Dynamic Delivery Webhook
```bash
# Starts FastAPI server (port 8000) and background stock sync worker
resellauth start
```

### 3. CLI Commands
- `resellauth setup`: Interactive config generator (persists to SQLite).
- `resellauth sync`: Run an immediate stock and price sync pass.
- `resellauth target-inspect <url>`: Inspect all variants, live prices, and stocks of any target SellAuth product.
- `resellauth start`: Launch FastAPI webhook listener and background sync loop.

---

## SellAuth Storefront Configuration

1. In your SellAuth dashboard, create or edit your product.
2. Under **Deliverables**, select **Dynamic Delivery**.
3. Set your Webhook URL to:
   ```
   https://your-server.com/api/v1/deliver
   ```
4. Copy your Webhook Secret from **Storefront > Configure > Miscellaneous** and enter it during `resellauth setup`.

---

## Repository

- **GitHub**: [https://github.com/DraxonV1/RESellAuth](https://github.com/DraxonV1/RESellAuth)
