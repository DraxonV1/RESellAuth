"""
Interactive CLI for resellauth.
Supports SQLite database storage (~/.resellauth/settings.db) across Windows, Linux, and macOS.
"""

import sys
import asyncio
import uvicorn
from rich.console import Console
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.panel import Panel
from rich.table import Table

from resellauth.core.config import ResellConfig, ProductPairing, VariantMapping, LTCWalletConfig
from resellauth.core.storage import StorageDB, get_db_path
from resellauth.sync.engine import StockSynchronizer
from resellauth.supplier.client import SupplierClient
from resellauth.gateway.ltc_tx import LTCWallet
from resellauth.server.app import app, init_app

console = Console()
db = StorageDB()


async def cli_inspect(url: str):
    """Inspects any target product live asynchronously."""
    console.print(f"[cyan]Inspecting {url}...[/cyan]")
    domain = url.split("/")[2]
    slug = url.rstrip("/").split("/")[-1]

    client = SupplierClient(domain, target_shop_id=0)
    try:
        data = await client.fetch_product_variants(slug)
        console.print(f"\n[bold green]Product: {data.get('name')} (ID: {data.get('id')})[/bold green]")

        table = Table(title=f"Supplier Variants ({domain})")
        table.add_column("Variant ID", style="cyan")
        table.add_column("Variant Name", style="magenta")
        table.add_column("Price (USD)", style="green")
        table.add_column("Stock", style="yellow")
        table.add_column("Min Qty", style="blue")

        for v in data.get("variants", []):
            table.add_row(
                str(v.get("id")),
                v.get("name"),
                f"${v.get('price')}",
                str(v.get("stock")),
                str(v.get("quantity_min") or 1),
            )
        console.print(table)
    finally:
        await client.close()


async def cli_sync():
    """Performs an immediate stock sync pass."""
    cfg = db.load_config()
    syncer = StockSynchronizer(cfg)
    try:
        await syncer.sync_once()
    finally:
        await syncer.close()


def cli_setup():
    """Interactive configuration generator with SQLite persistence."""
    console.print(Panel.fit(
        "[bold cyan]ResellAuth Interactive Setup Wizard[/bold cyan]\n"
        f"Settings will be saved to SQLite at: [yellow]{get_db_path()}[/yellow]",
        border_style="cyan"
    ))

    # 1. Your Storefront
    console.print("\n[bold yellow]--- 1. Your SellAuth Storefront ---[/bold yellow]")
    my_shop_domain = Prompt.ask("Your shop domain (e.g. myshop.mysellauth.com)")
    my_shop_id = IntPrompt.ask("Your shop ID (e.g. 102450)")
    my_api_key = Prompt.ask("Your SellAuth API Key (dash.sellauth.com/api)", password=True)
    my_webhook_secret = Prompt.ask("Your Dynamic Delivery Webhook Secret (Storefront > Configure > Misc)", password=True)

    # 2. Target Supplier
    console.print("\n[bold yellow]--- 2. Target Supplier ---[/bold yellow]")
    target_shop_domain = Prompt.ask("Target shop domain (e.g. supplier.mysellauth.com)")
    target_shop_id = IntPrompt.ask("Target shop ID")
    target_prod_url = Prompt.ask("Target product URL (e.g. https://supplier.mysellauth.com/product/item)")

    target_slug = target_prod_url.rstrip("/").split("/")[-1]

    # Quick inspection
    console.print(f"\n[cyan]Inspecting target supplier product '{target_slug}'...[/cyan]")
    target_client = SupplierClient(target_shop_domain, target_shop_id)
    try:
        t_data = asyncio.run(target_client.fetch_product_variants(target_slug))
        t_prod_id = t_data.get("id")
        console.print(f"[green]Found Product: {t_data.get('name')} (ID: {t_prod_id})[/green]")

        t_table = Table(title="Supplier Variants")
        t_table.add_column("Variant ID", style="cyan")
        t_table.add_column("Name", style="magenta")
        t_table.add_column("Price", style="green")
        t_table.add_column("Stock", style="yellow")
        for v in t_data.get("variants", []):
            t_table.add_row(str(v["id"]), v["name"], f"${v.get('price')}", str(v.get("stock")))
        console.print(t_table)
    except Exception as e:
        console.print(f"[red]Auto-fetch failed: {e}[/red]")
        t_prod_id = IntPrompt.ask("Enter Target Product ID manually")
    finally:
        asyncio.run(target_client.close())

    # 3. Product & Variant Pairings
    console.print("\n[bold yellow]--- 3. Product & Variant Mapping ---[/bold yellow]")
    my_product_id = IntPrompt.ask("Your corresponding Product ID in SellAuth dashboard")

    variant_mappings = []
    add_more = True
    while add_more:
        my_v_id = IntPrompt.ask("Your Variant ID")
        t_v_id = IntPrompt.ask("Target Variant ID")
        auto_price = Confirm.ask("Auto-sync price with markup?", default=False)
        markup = 0.0
        if auto_price:
            markup = float(Prompt.ask("Markup percentage (e.g. 20 for +20%)", default="20"))

        variant_mappings.append(VariantMapping(
            my_variant_id=my_v_id,
            target_variant_id=t_v_id,
            auto_sync_price=auto_price,
            markup_percent=markup,
        ))
        add_more = Confirm.ask("Map another variant?", default=False)

    pairing = ProductPairing(
        my_product_id=my_product_id,
        target_product_id=t_prod_id,
        target_product_slug=target_slug,
        target_product_url=target_prod_url,
        variant_mappings=variant_mappings,
    )

    # 4. Middleman LTC Wallet
    console.print("\n[bold yellow]--- 4. LTC Middleman Payment Gateway ---[/bold yellow]")
    auto_pay = Confirm.ask("Enable automatic on-chain LTC settlement from your private key?", default=True)
    ltc_priv_key = None
    rpc_url = None
    rpc_user = None
    rpc_password = None
    ltc_mode = "manual_rpc"

    if auto_pay:
        pay_method = Prompt.ask("Select Payout Method", choices=["private_key", "electrum_rpc", "manual"], default="private_key")
        ltc_mode = pay_method
        if pay_method == "private_key":
            ltc_priv_key = Prompt.ask("Enter your Litecoin Private Key (WIF format)", password=True)
            try:
                w = LTCWallet(ltc_priv_key)
                console.print(f"[green]✓ Wallet verified![/green]")
                console.print(f"  Native SegWit: [cyan]{w.native_segwit_address}[/cyan]")
                console.print(f"  Legacy:        [cyan]{w.legacy_address}[/cyan]")
            except Exception as e:
                console.print(f"[red]Warning: Could not parse private key WIF: {e}[/red]")
        elif pay_method == "electrum_rpc":
            rpc_url = Prompt.ask("Electrum-LTC Daemon RPC URL", default="http://127.0.0.1:7777")
            if Confirm.ask("Does RPC require authentication?", default=False):
                rpc_user = Prompt.ask("RPC User")
                rpc_password = Prompt.ask("RPC Password", password=True)

    max_usd = float(Prompt.ask("Max USD safety limit per invoice", default="25.0"))

    ltc_config = LTCWalletConfig(
        mode=ltc_mode,
        auto_pay=auto_pay,
        private_key_wif=ltc_priv_key,
        rpc_url=rpc_url,
        rpc_user=rpc_user,
        rpc_password=rpc_password,
        max_auto_pay_usd=max_usd,
    )

    # 5. Save to SQLite
    config = ResellConfig(
        my_shop_id=my_shop_id,
        my_shop_domain=my_shop_domain,
        my_api_key=my_api_key,
        my_webhook_secret=my_webhook_secret,
        target_shop_domain=target_shop_domain,
        target_shop_id=target_shop_id,
        pairings=[pairing],
        ltc=ltc_config,
    )

    db.save_config(config)
    console.print(Panel(f"[bold green]Configuration successfully saved to SQLite at {get_db_path()}![/bold green]", border_style="green"))
    console.print("\nNext steps:")
    console.print("1. Set your SellAuth Dynamic Delivery Webhook URL to: [cyan]http://your-server:8000/api/v1/deliver[/cyan]")
    console.print("2. Run [bold green]resellauth sync[/bold green] to test manual stock sync.")
    console.print("3. Run [bold green]resellauth start[/bold green] to launch daemon and webhook listener.")


def cli_start():
    """Starts the FastAPI webhook server with background async sync loop."""
    cfg = db.load_config()
    init_app(cfg)

    async def _run_app():
        syncer = StockSynchronizer(cfg)
        sync_task = asyncio.create_task(syncer.run_forever())
        console.print(f"[green]✓ Background stock synchronizer loop active ({cfg.sync_interval_seconds}s)[/green]")

        server_cfg = uvicorn.Config(app, host=cfg.server_host, port=cfg.server_port, log_level="info")
        server = uvicorn.Server(server_cfg)
        try:
            await server.serve()
        finally:
            sync_task.cancel()
            await syncer.close()

    console.print(f"[cyan]✓ Starting Dynamic Delivery gateway on {cfg.server_host}:{cfg.server_port}...[/cyan]")
    asyncio.run(_run_app())


def main():
    if len(sys.argv) < 2:
        console.print("[bold cyan]ResellAuth CLI[/bold cyan]")
        console.print("Commands:")
        console.print("  [green]resellauth setup[/green]                 Interactive configuration wizard (SQLite)")
        console.print("  [green]resellauth start[/green]                 Start webhook server & background sync worker")
        console.print("  [green]resellauth sync[/green]                  Run immediate stock sync pass")
        console.print("  [green]resellauth target-inspect <url>[/green]  Inspect live supplier variants/stock")
        sys.exit(0)

    cmd = sys.argv[1].lower()
    if cmd == "setup":
        cli_setup()
    elif cmd == "sync":
        asyncio.run(cli_sync())
    elif cmd == "start":
        cli_start()
    elif cmd == "target-inspect":
        if len(sys.argv) < 3:
            console.print("[red]Usage: resellauth target-inspect <product_url>[/red]")
            sys.exit(1)
        asyncio.run(cli_inspect(sys.argv[2]))
    else:
        console.print(f"[red]Unknown command '{cmd}'[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
