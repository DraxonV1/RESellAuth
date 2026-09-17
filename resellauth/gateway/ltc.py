"""
Middleman LTC Payment Gateway (Async).
Supports:
1. Native On-Chain Signing with User's Private Key (WIF).
   - Fetches UTXOs from block explorers.
   - Signs SegWit BIP143 transaction locally.
   - Broadcasts directly to Litecoin network.
2. Automated RPC (Electrum / Litecoin Core Daemon).
3. Operator Manual Mode.
"""

from typing import Dict, Any, Optional, List
from curl_cffi.requests import AsyncSession
from resellauth.core.config import LTCWalletConfig
from resellauth.gateway.ltc_tx import LTCWallet


class LTCGateway:
    def __init__(self, config: LTCWalletConfig):
        self.config = config
        self.session: Optional[AsyncSession] = None
        self.wallet: Optional[LTCWallet] = None

        if self.config.private_key_wif:
            try:
                self.wallet = LTCWallet(self.config.private_key_wif)
                print(f"[LTC GATEWAY] Initialized Native Wallet:")
                print(f"             SegWit Address: {self.wallet.native_segwit_address}")
                print(f"             Legacy Address: {self.wallet.legacy_address}")
            except Exception as e:
                print(f"[LTC GATEWAY] [!] Warning: Could not parse private key WIF: {e}")

    async def _get_session(self) -> AsyncSession:
        if self.session is None:
            self.session = AsyncSession()
        return self.session

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def fetch_utxos(self, address: str) -> List[Dict[str, Any]]:
        """
        Fetches unspent outputs (UTXOs) for address using reliable public Litecoin explorers.
        Tries Blockchair -> SoChain -> LitecoinSpace (mempool.space fork).
        """
        s = await self._get_session()
        utxos = []

        # Provider 1: litecoinspace.org (mempool.space fork)
        try:
            url = f"https://litecoinspace.org/api/address/{address}/utxo"
            resp = await s.get(url, timeout=10)
            if resp.status_code == 200:
                for item in resp.json():
                    utxos.append({
                        "txid": item["txid"],
                        "vout": item["vout"],
                        "value": item["value"],  # in satoshis
                    })
                return utxos
        except Exception as e:
            print(f"[LTC GATEWAY] Provider 1 error: {e}")

        # Provider 2: blockchair.com
        try:
            url = f"https://api.blockchair.com/litecoin/dashboards/address/{address}"
            resp = await s.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                utxo_data = data.get("data", {}).get(address, {}).get("utxo", [])
                for u in utxo_data:
                    utxos.append({
                        "txid": u["transaction_hash"],
                        "vout": u["index"],
                        "value": u["value"],
                    })
                return utxos
        except Exception as e:
            print(f"[LTC GATEWAY] Provider 2 error: {e}")

        return utxos

    async def broadcast_tx(self, raw_tx_hex: str) -> str:
        """Broadcasts raw hex transaction to the Litecoin network."""
        s = await self._get_session()

        # Provider 1: litecoinspace.org
        try:
            url = "https://litecoinspace.org/api/tx"
            resp = await s.post(url, data=raw_tx_hex, headers={"Content-Type": "text/plain"}, timeout=15)
            if resp.status_code in [200, 201]:
                return resp.text.strip()
        except Exception:
            pass

        # Provider 2: blockchair.com
        try:
            url = "https://api.blockchair.com/litecoin/push/transaction"
            resp = await s.post(url, json={"data": raw_tx_hex}, timeout=15)
            if resp.status_code == 200:
                return resp.json().get("data", {}).get("transaction_hash")
        except Exception:
            pass

        raise RuntimeError("Failed to broadcast raw LTC transaction through public explorers.")

    async def pay_invoice(
        self,
        target_address: str,
        amount_ltc: float,
        price_usd: float,
        invoice_id: str,
    ) -> Dict[str, Any]:
        """
        Dispatches LTC to target address:
        - If private_key_wif is provided and auto_pay is true: signs on-chain & broadcasts directly.
        - If electrum_rpc is configured: calls electrum daemon.
        - Otherwise: prompts/logs manual payout instructions.
        """
        print(f"\n[LTC GATEWAY] Processing invoice #{invoice_id}")
        print(f"             Target: {target_address}")
        print(f"             Amount: {amount_ltc:.8f} LTC (~${price_usd:.2f} USD)")

        if price_usd > self.config.max_auto_pay_usd:
            raise ValueError(
                f"Invoice cost ${price_usd:.2f} exceeds safety ceiling ${self.config.max_auto_pay_usd:.2f}"
            )

        # 1. Native Private Key On-Chain Mode
        if self.wallet and self.config.auto_pay:
            return await self._pay_with_private_key(target_address, amount_ltc)

        # 2. Electrum RPC Mode
        elif self.config.mode == "electrum_rpc" and self.config.rpc_url and self.config.auto_pay:
            return await self._pay_electrum_rpc(target_address, amount_ltc)

        # 3. Manual Operator Mode
        else:
            return self._pay_manual(target_address, amount_ltc, invoice_id)

    async def _pay_with_private_key(self, to_address: str, amount_ltc: float) -> Dict[str, Any]:
        """Builds, signs, and broadcasts transaction using user's private key."""
        amount_sats = int(round(amount_ltc * 100_000_000))
        fee_sats = 2000  # standard ~0.00002 LTC fee

        # Search UTXOs across SegWit and Legacy addresses
        utxos = await self.fetch_utxos(self.wallet.native_segwit_address)
        if not utxos:
            utxos = await self.fetch_utxos(self.wallet.legacy_address)

        total_avail = sum(u["value"] for u in utxos)
        if total_avail < amount_sats + fee_sats:
            raise RuntimeError(
                f"Insufficient funds in wallet {self.wallet.native_segwit_address}: "
                f"Available {total_avail / 1e8:.8f} LTC, Required {(amount_sats + fee_sats) / 1e8:.8f} LTC."
            )

        # Build & Sign raw transaction
        raw_tx = self.wallet.build_p2wpkh_tx(
            utxos=utxos,
            to_address=to_address,
            send_amount_sats=amount_sats,
            fee_sats=fee_sats
        )

        # Broadcast
        txid = await self.broadcast_tx(raw_tx)
        print(f"[LTC GATEWAY] [✓] Transaction broadcasted! TXID: {txid}")
        return {
            "success": True,
            "txid": txid,
            "mode": "private_key_onchain",
            "raw_tx": raw_tx
        }

    async def _pay_electrum_rpc(self, to_address: str, amount: float) -> Dict[str, Any]:
        s = await self._get_session()
        payload = {
            "id": "resellauth-pay",
            "method": "payto",
            "params": [to_address, amount],
        }
        auth = None
        if self.config.rpc_user and self.config.rpc_password:
            auth = (self.config.rpc_user, self.config.rpc_password)

        resp = await s.post(self.config.rpc_url, json=payload, auth=auth, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data and data["error"]:
            raise RuntimeError(f"Electrum RPC Error: {data['error']}")

        tx_hex = data.get("result")
        b_payload = {
            "id": "resellauth-broadcast",
            "method": "broadcast",
            "params": [tx_hex],
        }
        b_resp = await s.post(self.config.rpc_url, json=b_payload, auth=auth, timeout=30)
        b_data = b_resp.json()
        txid = b_data.get("result")
        print(f"[LTC GATEWAY] Transaction broadcasted via Electrum! TXID: {txid}")
        return {"success": True, "txid": txid, "mode": "electrum_rpc"}

    def _pay_manual(self, to_address: str, amount: float, invoice_id: str) -> Dict[str, Any]:
        print("=" * 60)
        print(" [!] MANUAL LTC PAYOUT DISPATCH")
        print(f"     Amount:           {amount:.8f} LTC")
        print(f"     Destination:      {to_address}")
        print(f"     URI:              litecoin:{to_address}?amount={amount:.8f}")
        print(f"     Supplier Invoice: {invoice_id}")
        print("=" * 60)
        return {"success": True, "mode": "manual_pending", "address": to_address, "amount": amount}
