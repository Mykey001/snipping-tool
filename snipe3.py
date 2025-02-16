import asyncio
import time
import json
import logging
import datetime
from typing import Optional, Dict
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.system_program import ID as SystemProgramID
from solders.transaction import Transaction
from solders.instruction import Instruction as TransactionInstruction
from solders.keypair import Keypair
from solders.instruction import AccountMeta
from solana.rpc.types import TokenAccountOpts, TxOpts

from anchorpy import Program, Provider, Wallet, Idl
import os
import base58
from dotenv import load_dotenv
import aiohttp
from dataclasses import dataclass
from rich.console import Console
from rich.table import Table
from rich.live import Live
from collections import deque


        # Add memory-efficient event processing
from collections import deque
from asyncio import Queue, PriorityQueue


# Initialize Rich console
console = Console()

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('RaydiumBot')

# Load environment variables
load_dotenv()

# Raydium AMM IDL definition
RAYDIUM_IDL = {
    "version": "0.1.0",
    "name": "raydium_amm",
    "instructions": [
        {
            "name": "swap",
            "accounts": [
                {"name": "amm", "isMut": True, "isSigner": False},
                {"name": "authority", "isMut": False, "isSigner": False},
                {"name": "userTransferAuthority", "isMut": False, "isSigner": True},
                {"name": "sourceInfo", "isMut": True, "isSigner": False},
                {"name": "destinationInfo", "isMut": True, "isSigner": False},
                {"name": "sourceMint", "isMut": False, "isSigner": False},
                {"name": "destMint", "isMut": False, "isSigner": False},
                {"name": "tokenProgram", "isMut": False, "isSigner": False}
            ],
            "args": [
                {"name": "amountIn", "type": "u64"},
                {"name": "minimumAmountOut", "type": "u64"}
            ]
        }
    ]
}

@dataclass
class Config:
    RPC_URLS = [
        os.getenv("RPC_URL_1", "https://api.mainnet-beta.solana.com"),
        os.getenv("RPC_URL_2", "https://ssc-dao.genesysgo.net")
    ]
    WEBSOCKET_URL = os.getenv("WEBSOCKET_URL", "wss://api.mainnet-beta.solana.com")
    RAYDIUM_AMM_PROGRAM_ID = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
    MEME_COIN_MINT = Pubkey.from_string(os.getenv("MEME_COIN_MINT", "11111111111111111111111111111111"))
    COMMITMENT = Confirmed
    MAX_RETRIES = 5
    PRIORITY_FEE = 500_000
    SLIPPAGE = 0.05
    MAX_LATENCY = 0.5

    @staticmethod
    def get_wallet() -> Keypair:
        try:
            key_str = os.getenv("WALLET_PRIVATE_KEY")
            if not key_str:
                raise ValueError("WALLET_PRIVATE_KEY not found in environment variables")
            
            secret = base58.b58decode(key_str)
            if len(secret) == 64:
                return Keypair.from_bytes(secret)
            elif len(secret) == 32:
                return Keypair.from_seed(secret)
            else:
                raise ValueError(f"Invalid private key length: {len(secret)}")
        except Exception as e:
            logger.error(f"Error creating wallet: {str(e)}")
            raise

class RaydiumClient:
    def __init__(self):
        self.clients = []
        for url in Config.RPC_URLS:
            try:
                client = AsyncClient(url, commitment=Config.COMMITMENT)
                self.clients.append(client)
                logger.info(f"Initialized RPC client for {url}")
            except Exception as e:
                logger.error(f"Failed to initialize RPC client for {url}: {str(e)}")
        
        if not self.clients:
            raise RuntimeError("No RPC clients could be initialized")
            
        self.current_client = 0
        self.program: Optional[Program] = None
        self._last_blockhash = None
        self._last_blockhash_time = 0
        self.wallet = Wallet(Config.get_wallet())

    async def initialize(self):
        """Initialize Raydium AMM program"""
        try:
            logger.info("Initializing Raydium AMM program...")
            provider = Provider(self.clients[0], self.wallet)
            
            # Create Program instance with manual IDL
            idl = Idl.from_json(json.dumps(RAYDIUM_IDL))
            self.program = Program(idl, Config.RAYDIUM_AMM_PROGRAM_ID, provider)
            logger.info("Raydium AMM program initialized successfully")
            
            # Verify connection
            await self.client.get_latest_blockhash()
            
        except Exception as e:
            logger.error(f"Failed to initialize Raydium client: {str(e)}")
            raise

    @property
    def client(self) -> AsyncClient:
        return self.clients[self.current_client]

class BotStats:
    def __init__(self):
        self.start_time = datetime.datetime.now()
        self.burn_events_detected = 0
        self.successful_swaps = 0
        self.failed_swaps = 0
        self.last_events = deque(maxlen=5)
        self.connection_status = "Initializing"
        self.last_block_time = None
        
    def add_event(self, event: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.last_events.appendleft(f"{timestamp} - {event}")

class SnipingBot:
    def __init__(self):
        self.raydium = RaydiumClient()
        self.session = None
        self.pool_cache = {}
        self.stats = BotStats()



    def __init__(self):
        self.event_queue = PriorityQueue()
        self.recent_events = deque(maxlen=100)
        self.burn_cache = {}
        
    async def process_events(self):
        while True:
            priority, event = await self.event_queue.get()
            if event['type'] == 'burn':
                await self.handle_burn_event(event)
            self.event_queue.task_done()
            
    async def handle_burn_event(self, event):
        # Add event batching
        if len(self.burn_cache) >= 10:
            await self.process_burn_batch(self.burn_cache)
            self.burn_cache.clear()
        self.burn_cache[event['signature']] = event



    async def initialize(self):
        """Initialize the bot"""
        await self.raydium.initialize()
        self.session = aiohttp.ClientSession()
        self.stats.add_event("Bot initialized successfully")

    async def display_status(self):
        """Display real-time bot status"""
        while True:
            table = Table(title="Raydium Sniping Bot Status")
            
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="green")
            
            uptime = datetime.datetime.now() - self.stats.start_time
            table.add_row("Uptime", str(uptime).split('.')[0])
            table.add_row("Connection Status", self.stats.connection_status)
            table.add_row("Burn Events Detected", str(self.stats.burn_events_detected))
            table.add_row("Successful Swaps", str(self.stats.successful_swaps))
            table.add_row("Failed Swaps", str(self.stats.failed_swaps))
            
            if self.stats.last_block_time:
                last_block_age = datetime.datetime.now() - self.stats.last_block_time
                table.add_row("Last Block Age", f"{last_block_age.total_seconds():.1f}s")
            
            table.add_row("Recent Events", "")
            for event in self.stats.last_events:
                table.add_row("", event)
            
            console.clear()
            console.print(table)
            
            await asyncio.sleep(1)
    

    async def monitor_wallet_balance(self):
        while True:
            # e.g. fetch balance from self.raydium.client
            await asyncio.sleep(5)

    async def monitor_gas_prices(self):
        while True:
            # e.g. fetch gas price from some API
            await asyncio.sleep(5)


    async def monitor_lp_burns(self):
        """Monitor LP burn events"""
        retry_count = 0
        self.stats.connection_status = "Connected"
        
        while retry_count < Config.MAX_RETRIES:
            try:
                async with self.session.ws_connect(Config.WEBSOCKET_URL) as ws:
                    self.stats.add_event("WebSocket connection established")
                    
                    await ws.send_json({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [str(Config.RAYDIUM_AMM_PROGRAM_ID)]},
                            {"commitment": str(Config.COMMITMENT)}
                        ]
                    })
                    
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            self.stats.last_block_time = datetime.datetime.now()
                            await self.process_log_message(data)
                            
            except Exception as e:
                retry_count += 1
                self.stats.connection_status = f"Reconnecting ({retry_count}/{Config.MAX_RETRIES})"
                self.stats.add_event(f"Connection error: {str(e)}")
                await asyncio.sleep(2 ** retry_count)

    async def process_log_message(self, msg):
        """Process incoming log messages"""
        try:
            if "params" in msg and "result" in msg["params"]:
                result = msg["params"].get("result", {})
                if isinstance(result, dict):
                    value = result.get("value", {})
                    logs = value.get("logs", [])
                    
                    if any("Instruction: Burn" in log for log in logs):
                        self.stats.burn_events_detected += 1
                        signature = value.get("signature")
                        if signature:
                            self.stats.add_event(f"Burn event detected: {signature[:8]}...")
                            await self.verify_burn_event(signature)
                            
        except Exception as e:
            self.stats.add_event(f"Error processing message: {str(e)}")

    async def verify_burn_event(self, signature: str):
        """Verify a burn event"""
        try:
            tx = await self.raydium.client.get_transaction(
                signature,
                encoding="jsonParsed",
                max_supported_transaction_version=0
            )
            # Add your verification logic here
            self.stats.add_event(f"Verified burn event: {signature[:8]}...")
        except Exception as e:
            self.stats.add_event(f"Error verifying burn: {str(e)}")

    async def cleanup(self):
        """Cleanup resources"""
        if self.session is not None:
            await self.session.close()
        for client in self.raydium.clients:
            await client.close()

async def main():
    bot = SnipingBot()
    try:
        await bot.initialize()
        await asyncio.gather(
            bot.display_status(),
            bot.monitor_lp_burns()
        )
    except Exception as e:
        console.print(f"[red]Bot error: {str(e)}")
    finally:
        await bot.cleanup()

if __name__ == "__main__":
    try:
        console.print("[yellow]Starting Raydium Sniping Bot...[/yellow]")
        console.print("[yellow]Press Ctrl+C to stop the bot[/yellow]")
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("[red]Bot stopped by user[/red]")
    except Exception as e:
        console.print(f"[red]Unhandled exception: {str(e)}[/red]")


        # Add memory-efficient event processing
from collections import deque
from asyncio import Queue, PriorityQueue

