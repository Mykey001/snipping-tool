import asyncio
from aiohttp import web
import json
from typing import Set, Dict
import logging

# Import your SnipingBot class
from snipe3 import SnipingBot  # Assuming your existing code is in bot.py

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BotServer:
    def __init__(self):
        self.bot = SnipingBot()
        self.app = web.Application()
        self.websockets: Set[web.WebSocketResponse] = set()
        self.setup_routes()
        
    def setup_routes(self):
        self.app.router.add_get('/ws', self.websocket_handler)
        self.app.router.add_post('/api/config', self.update_config)
        
    async def broadcast(self, message: Dict):
        if self.websockets:
            data = json.dumps(message)
            for ws in self.websockets:
                try:
                    await ws.send_str(data)
                except Exception as e:
                    logger.error(f"Error broadcasting to websocket: {e}")
                    
    async def on_bot_event(self, event_type: str, data: Dict):
        await self.broadcast({
            "type": event_type,
            "stats": data
        })
        
    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        self.websockets.add(ws)
        logger.info(f"New client connected. Total clients: {len(self.websockets)}")
        
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    # Handle any incoming messages if needed
                    pass
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
        finally:
            self.websockets.remove(ws)
            logger.info(f"Client disconnected. Remaining clients: {len(self.websockets)}")
        
        return ws
        
    async def update_config(self, request):
        try:
            data = await request.json()
            # Update bot configuration
            # You would implement the actual config update logic here
            return web.json_response({"status": "success"})
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=400)
            
    async def start(self):
        # Initialize the bot
        await self.bot.initialize()
        
        # Set up the event handler
        self.bot.on_event = self.on_bot_event
        
        # Start all monitoring tasks
        monitoring_tasks = [
            self.bot.monitor_lp_burns(),
            self.bot.monitor_wallet_balance(),
            self.bot.monitor_gas_prices()
        ]
        
        # Start the web server
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 5000)
        await site.start()
        
        logger.info("Server started on http://localhost:5000")
        
        # Run all tasks concurrently
        await asyncio.gather(*monitoring_tasks)

if __name__ == "__main__":
    bot_server = BotServer()
    asyncio.run(bot_server.start())