import asyncio
import time
import json
import logging
import datetime
from typing import Optional, Dict, Callable
import solders.rpc.responses
import asyncio
import backoff  # You'll need to pip install backoff
import aiohttp.client_exceptions
import ssl
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from anchorpy import Program, Provider, Wallet, Idl
import os
import base58
from dotenv import load_dotenv
import aiohttp
from dataclasses import dataclass
from collections import deque
from solana.rpc.async_api import AsyncClient

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

RAYDIUM_IDL = {
    "version": "0.0.0",
    "name": "raydium",
    "instructions": []
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
            if len(secret) != 64:
                raise ValueError(f"Expected 64 bytes for secret key, got {len(secret)}")

            return Keypair.from_bytes(secret)
        except Exception as e:
            logger.error(f"Error creating wallet: {str(e)}")
            raise


class RaydiumClient:
    def __init__(self):
        self.clients = []
        # Define timeout for AsyncClient separately
        self.rpc_timeout = 30  # seconds
        
        # Define aiohttp timeout for other connections
        self.http_timeout = aiohttp.ClientTimeout(
            total=30,
            connect=10,
            sock_read=10
        )
        
        for url in Config.RPC_URLS:
            try:
                # Use simple float timeout for AsyncClient
                client = AsyncClient(
                    url, 
                    commitment=Config.COMMITMENT,
                    timeout=self.rpc_timeout  # Using float timeout here
                )
                self.clients.append(client)
                logger.info(f"Initialized RPC client for {url}")
            except Exception as e:
                logger.error(f"Failed to initialize RPC client for {url}: {str(e)}")
        
        if not self.clients:
            raise RuntimeError("No RPC clients could be initialized")
            
        self.current_client = 0
        self.program: Optional[Program] = None
        self.on_event = None
        self.wallet: Optional[Wallet] = None

    def _rotate_client(self):
        """Rotate to the next available RPC client"""
        self.current_client = (self.current_client + 1) % len(self.clients)
        logger.info(f"Rotated to RPC client {self.current_client}")

    @backoff.on_exception(
        backoff.expo,
        (
            aiohttp.client_exceptions.ClientError,
            asyncio.TimeoutError,
            ssl.SSLError,
            ConnectionError
        ),
        max_tries=5,
        max_time=30
    )
    async def _retry_rpc_call(self, coro):
        """Wrapper to retry RPC calls with exponential backoff"""
        try:
            return await coro
        except Exception as e:
            logger.error(f"RPC call failed: {str(e)}")
            self._rotate_client()  # Try another client on failure
            raise

    async def initialize(self):
        """Initialize Raydium AMM program with retries."""
        try:
            logger.info("Initializing Raydium AMM program...")

            keypair = Config.get_wallet()
            self.wallet = Wallet(keypair)
            
            # Create provider with retry mechanism
            provider = Provider(self.clients[0], self.wallet)

            # Load IDL with retry
            idl = Idl.from_json(json.dumps(RAYDIUM_IDL))
            self.program = Program(idl, Config.RAYDIUM_AMM_PROGRAM_ID, provider)
            
            # Get latest blockhash with retry
            blockhash = await self._retry_rpc_call(
                self.client.get_latest_blockhash(Confirmed)
            )

            logger.info("Raydium AMM program initialized successfully.")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Raydium client: {str(e)}")
            # Re-raise the exception after logging
            raise

    @property
    def client(self) -> AsyncClient:
        """Returns the current active AsyncClient."""
        return self.clients[self.current_client]

    async def close(self):
        """Properly close all client connections"""
        for client in self.clients:
            try:
                await client.close()
            except Exception as e:
                logger.error(f"Error closing client: {str(e)}")
class BotStats:
    def __init__(self):
        self.start_time = datetime.datetime.now()
        self.burn_events_detected = 0
        self.successful_swaps = 0
        self.failed_swaps = 0
        self.last_events = deque(maxlen=100)
        self.connection_status = "Initializing"
        self.last_block_time = None
        self.wallet_balance = 0
        self.current_gas_price = 0
        
    def add_event(self, event: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.last_events.appendleft(f"{timestamp} - {event}")

class SnipingBot:
    def __init__(self):
        self.raydium = RaydiumClient()
        self.session: Optional[aiohttp.ClientSession] = None
        self.pool_cache = {}
        self.stats = BotStats()
        self.event_queue = asyncio.Queue()
        self.burn_cache = {}
        self.on_event: Optional[Callable] = None
        self.keypair: Optional[Keypair] = None

    async def initialize(self):
        try:
            await self.raydium.initialize()
            self.session = aiohttp.ClientSession()
            self.stats.add_event("Bot initialized successfully")
            logger.info("Bot initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize bot: {str(e)}")
            raise

    async def monitor_lp_burns(self):
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
                            if self.on_event:
                                await self.on_event('stats_update', self.stats.__dict__)
                            
            except Exception as e:
                retry_count += 1
                self.stats.connection_status = f"Reconnecting ({retry_count}/{Config.MAX_RETRIES})"
                self.stats.add_event(f"Connection error: {str(e)}")
                await asyncio.sleep(2 ** retry_count)

    async def monitor_wallet_balance(self):
        while True:
            try:
                response = await self.raydium.client.get_balance(self.raydium.wallet.public_key)
                self.stats.wallet_balance = response.value / 1e9
                if self.on_event:
                    await self.on_event('wallet_update', self.stats.wallet_balance)
            except Exception as e:
                logger.error(f"Error monitoring wallet balance: {str(e)}")
            await asyncio.sleep(5)

    async def monitor_gas_prices(self):
        while True:
            try:
                recent_blockhash = await self.raydium.client.get_latest_blockhash(Confirmed)
                if hasattr(self, 'stats'):
                # Convert Hash object to string using str()
                    self.stats.current_gas_price = str(recent_blockhash.value.blockhash)
                    if self.on_event:
                        await self.on_event('gas_update', self.stats.current_gas_price)
            except Exception as e:
                logger.error(f"Error monitoring gas prices: {str(e)}")
            await asyncio.sleep(5)

    async def process_log_message(self, msg):
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
            logger.error(f"Error processing message: {str(e)}")

    async def verify_burn_event(self, signature: str):
        try:
            tx = await self.raydium.client.get_transaction(
                signature,
                encoding="jsonParsed",
                max_supported_transaction_version=0
            )
            self.stats.add_event(f"Verified burn event: {signature[:8]}...")
        except Exception as e:
            logger.error(f"Error verifying burn: {str(e)}")

    async def cleanup(self):
        if self.session:
            await self.session.close()
        for client in self.raydium.clients:
            await client.close()


    async def verify_burn_event(self, signature: str):
        """Verify burn events with proper signature conversion"""
        try:
            # Convert string signature to Solana Signature type
            tx_signature = Signature.from_string(signature)
            
            tx = await self.raydium._retry_rpc_call(
                self.raydium.client.get_transaction(
                    tx_signature,  # Use the converted signature
                    encoding="jsonParsed",
                    max_supported_transaction_version=0
                )
            )
            self.stats.add_event(f"Verified burn event: {signature[:8]}...")
            
        except ValueError as e:
            logger.error(f"Invalid signature format: {str(e)}")
        except Exception as e:
            logger.error(f"Error verifying burn: {str(e)}")

    async def process_log_message(self, msg):
        """Process WebSocket messages with proper signature handling"""
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
                            # Validate signature format before processing
                            try:
                                # Test signature conversion
                                Signature.from_string(signature)
                                self.stats.add_event(f"Burn event detected: {signature[:8]}...")
                                await self.verify_burn_event(signature)
                            except ValueError:
                                logger.error(f"Invalid signature format received: {signature}")
                            
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")