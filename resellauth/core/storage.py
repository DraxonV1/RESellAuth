"""
Cross-Platform SQLite Storage Engine for ResellAuth.
Stores all settings, product pairings, LTC wallet keys, and logs in:
- Windows: C:\\Users\\<User>\\.resellauth\\settings.db
- Linux / macOS: ~/.resellauth/settings.db
"""

import os
import sqlite3
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from resellauth.core.config import ResellConfig, ProductPairing, VariantMapping, LTCWalletConfig


def get_resellauth_dir() -> Path:
    """Returns cross-platform directory ~/.resellauth/."""
    home = Path.home()
    app_dir = home / ".resellauth"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_db_path() -> Path:
    """Returns database path ~/.resellauth/settings.db."""
    return get_resellauth_dir() / "settings.db"


class StorageDB:
    def __init__(self, db_path: Optional[str] = None):
        self.path = Path(db_path) if db_path else get_db_path()
        self.init_db()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def init_db(self):
        """Initializes tables for configuration, pairings, and transactions."""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # Key-Value settings table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Product pairings table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS product_pairings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                my_product_id INTEGER NOT NULL,
                target_product_id INTEGER NOT NULL,
                target_product_slug TEXT NOT NULL,
                target_product_url TEXT NOT NULL,
                variant_mappings TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Middleman payment & order logs
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS order_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                our_invoice_id INTEGER,
                target_invoice_id TEXT,
                target_address TEXT,
                amount_ltc REAL,
                txid TEXT,
                status TEXT,
                deliverables_count INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)
            conn.commit()

    def set_setting(self, key: str, value: str):
        with self._get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row[0] if row else default

    def save_config(self, config: ResellConfig):
        """Saves entire configuration into SQLite."""
        with self._get_conn() as conn:
            # Store credentials & global settings
            settings_to_store = {
                "my_shop_id": str(config.my_shop_id),
                "my_shop_domain": config.my_shop_domain,
                "my_api_key": config.my_api_key,
                "my_webhook_secret": config.my_webhook_secret,
                "target_shop_domain": config.target_shop_domain,
                "target_shop_id": str(config.target_shop_id),
                "buyer_email_override": config.buyer_email_override or "",
                "sync_interval_seconds": str(config.sync_interval_seconds),
                "server_host": config.server_host,
                "server_port": str(config.server_port),
                "ltc_config": config.ltc.model_dump_json(),
            }
            for k, v in settings_to_store.items():
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v))

            # Store pairings
            conn.execute("DELETE FROM product_pairings")
            for p in config.pairings:
                v_json = json.dumps([m.model_dump() for m in p.variant_mappings])
                conn.execute(
                    """
                    INSERT INTO product_pairings
                    (my_product_id, target_product_id, target_product_slug, target_product_url, variant_mappings)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (p.my_product_id, p.target_product_id, p.target_product_slug, p.target_product_url, v_json),
                )
            conn.commit()

    def load_config(self) -> ResellConfig:
        """Loads ResellConfig from SQLite database."""
        with self._get_conn() as conn:
            rows = dict(conn.execute("SELECT key, value FROM settings").fetchall())
            if not rows:
                raise FileNotFoundError(f"No settings found in SQLite DB at '{self.path}'. Run 'resellauth setup' first.")

            ltc_raw = rows.get("ltc_config")
            ltc = LTCWalletConfig(**json.loads(ltc_raw)) if ltc_raw else LTCWalletConfig()

            # Load pairings
            pairing_rows = conn.execute(
                "SELECT my_product_id, target_product_id, target_product_slug, target_product_url, variant_mappings FROM product_pairings"
            ).fetchall()
            pairings = []
            for r in pairing_rows:
                vm_list = [VariantMapping(**item) for item in json.loads(r[4])]
                pairings.append(ProductPairing(
                    my_product_id=r[0],
                    target_product_id=r[1],
                    target_product_slug=r[2],
                    target_product_url=r[3],
                    variant_mappings=vm_list,
                ))

            return ResellConfig(
                my_shop_id=int(rows.get("my_shop_id", 0)),
                my_shop_domain=rows.get("my_shop_domain", ""),
                my_api_key=rows.get("my_api_key", ""),
                my_webhook_secret=rows.get("my_webhook_secret", ""),
                target_shop_domain=rows.get("target_shop_domain", ""),
                target_shop_id=int(rows.get("target_shop_id", 0)),
                buyer_email_override=rows.get("buyer_email_override") or None,
                sync_interval_seconds=int(rows.get("sync_interval_seconds", 120)),
                server_host=rows.get("server_host", "0.0.0.0"),
                server_port=int(rows.get("server_port", 8000)),
                pairings=pairings,
                ltc=ltc,
            )

    def log_order(
        self,
        our_invoice_id: Optional[int],
        target_invoice_id: str,
        target_address: str,
        amount_ltc: float,
        txid: Optional[str],
        status: str,
        deliverables_count: int,
    ):
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO order_logs
                (our_invoice_id, target_invoice_id, target_address, amount_ltc, txid, status, deliverables_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (our_invoice_id, target_invoice_id, target_address, amount_ltc, txid, status, deliverables_count),
            )
            conn.commit()


if __name__ == "__main__":
    db = StorageDB()
    print("[storage.py] Database located at:", db.path)
    print("Database tables initialized.")
