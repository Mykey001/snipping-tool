from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
import asyncio
import threading
from datetime import datetime, timedelta
import logging
import os
from functools import wraps
from dataclasses import dataclass, asdict
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', os.urandom(24))
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class Trade:
    timestamp: str
    token_address: str
    amount_in: float
    amount_out: float
    price: float
    transaction_hash: str
    status: str

@dataclass
class BotMetrics:
    total_profit_loss: float
    success_rate: float
    average_response_time: float
    gas_spent: float
    total_trades: int

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

# Demo user - replace with database in production
USERS = {
    'admin': User(1, 'admin', generate_password_hash('adminpass'))
}

class FlaskBotWrapper:
    def __init__(self):
        self.stats = {
            'burn_events_detected': 0,
            'successful_swaps': 0,
            'failed_swaps': 0,
            'connection_status': 'Initializing',
            'start_time': datetime.now().isoformat(),
            'last_block_time': None,
            'recent_events': [],
            'trades': [],
            'wallet_balance': 0.0,
            'current_gas_price': 0,
            'pool_liquidity': {},
            'profit_loss': 0.0
        }
        self.metrics = BotMetrics(
            total_profit_loss=0.0,
            success_rate=0.0,
            average_response_time=0.0,
            gas_spent=0.0,
            total_trades=0
        )
        
    def update_stats(self, event_type, data):
        self.stats['last_block_time'] = datetime.now().isoformat()
        
        if event_type == 'burn_event':
            self.stats['burn_events_detected'] += 1
        elif event_type == 'successful_swap':
            self.stats['successful_swaps'] += 1
            self._add_trade(data, 'success')
        elif event_type == 'failed_swap':
            self.stats['failed_swaps'] += 1
            self._add_trade(data, 'failed')
        elif event_type == 'wallet_update':
            self.stats['wallet_balance'] = data
        elif event_type == 'gas_update':
            self.stats['current_gas_price'] = data
        elif event_type == 'pool_update':
            self.stats['pool_liquidity'].update(data)
            
        self._add_event(data)
        self._update_metrics()
        self._emit_updates()
    
    def _add_trade(self, trade_data, status):
        trade = Trade(
            timestamp=datetime.now().isoformat(),
            token_address=trade_data.get('token_address'),
            amount_in=trade_data.get('amount_in', 0),
            amount_out=trade_data.get('amount_out', 0),
            price=trade_data.get('price', 0),
            transaction_hash=trade_data.get('tx_hash'),
            status=status
        )
        self.stats['trades'].insert(0, asdict(trade))
        self.stats['trades'] = self.stats['trades'][:100]  # Keep last 100 trades
        
    def _add_event(self, data):
        event = {
            'timestamp': datetime.now().isoformat(),
            'event': data
        }
        self.stats['recent_events'].insert(0, event)
        self.stats['recent_events'] = self.stats['recent_events'][:20]
        
    def _update_metrics(self):
        total_trades = self.stats['successful_swaps'] + self.stats['failed_swaps']
        if total_trades > 0:
            self.metrics.success_rate = (self.stats['successful_swaps'] / total_trades) * 100
        self.metrics.total_trades = total_trades
        
    def _emit_updates(self):
        socketio.emit('stats_update', {
            'stats': self.stats,
            'metrics': asdict(self.metrics)
        })

# Initialize bot wrapper
bot_wrapper = FlaskBotWrapper()

@login_manager.user_loader
def load_user(user_id):
    for user in USERS.values():
        if user.id == int(user_id):
            return user
    return None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = USERS.get(username)
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('index'))
            
        return render_template('login.html', error="Invalid credentials")
        
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/api/stats')
@login_required
def get_stats():
    return jsonify({
        'stats': bot_wrapper.stats,
        'metrics': asdict(bot_wrapper.metrics)
    })

@app.route('/api/trades')
@login_required
def get_trades():
    return jsonify(bot_wrapper.stats['trades'])

@app.route('/api/config', methods=['GET', 'POST'])
@login_required
def bot_config():
    if request.method == 'POST':
        config = request.get_json()
        # Update bot configuration
        return jsonify({'status': 'success'})
    return jsonify({
        'rpc_urls': Config.RPC_URLS,
        'max_slippage': Config.SLIPPAGE,
        'priority_fee': Config.PRIORITY_FEE
    })

def run_bot():
    """Run the original bot logic in a separate thread"""
    async def bot_main():
        try:
            from snipe3 import SnipingBot
            bot = SnipingBot()
            await bot.initialize()
            
            def on_event(event_type, data):
                bot_wrapper.update_stats(event_type, data)
            
            bot.on_event = on_event
            
            await asyncio.gather(
                bot.monitor_lp_burns(),
                bot.display_status(),
                bot.monitor_wallet_balance(),
                bot.monitor_gas_prices()
            )
        except Exception as e:
            logger.error(f"Bot error: {str(e)}")
            bot_wrapper.update_stats('error', str(e))
    
    asyncio.run(bot_main())

if __name__ == '__main__':
    # Start bot in a separate thread
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Run Flask app
    socketio.run(app, debug=True, port=5000)

    if __name__ == '__main__':
        app.run(host='0.0.0.0', port=5000)
