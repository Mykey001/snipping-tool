from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
import asyncio
import threading
from datetime import datetime
import logging
import os
from functools import wraps
from dataclasses import dataclass, asdict
import json
from snipe3 import SnipingBot, Config

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', os.urandom(24))
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
            'wallet_balance': 0.0,
            'current_gas_price': 0,
        }
        
    def update_stats(self, event_type, data):
        if event_type == 'stats_update':
            self.stats.update(data)
        elif event_type == 'wallet_update':
            self.stats['wallet_balance'] = data
        elif event_type == 'gas_update':
            self.stats['current_gas_price'] = data
            
        socketio.emit('stats_update', {'stats': self.stats})

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
    return jsonify({'stats': bot_wrapper.stats})

@app.route('/api/config', methods=['GET', 'POST'])
@login_required
def bot_config():
    if request.method == 'POST':
        data = request.get_json()
        if 'memeCoinMint' in data:
            try:
                # Update meme coin mint in Config
                Config.MEME_COIN_MINT = data['memeCoinMint']
                return jsonify({'status': 'success'})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 400
    
    return jsonify({
        'rpc_urls': Config.RPC_URLS,
        'meme_coin_mint': str(Config.MEME_COIN_MINT),
        'max_slippage': Config.SLIPPAGE,
        'priority_fee': Config.PRIORITY_FEE
    })

def run_bot():
    """Run the original bot logic in a separate thread"""
    async def bot_main():
        try:
            bot = SnipingBot()
            await bot.initialize()
            
            def on_event(event_type, data):
                bot_wrapper.update_stats(event_type, data)
            
            bot.on_event = on_event
            
            await asyncio.gather(
                bot.monitor_lp_burns(),
                bot.monitor_wallet_balance(),
                bot.monitor_gas_prices()
            )
        except Exception as e:
            logger.error(f"Bot error: {str(e)}")
            bot_wrapper.update_stats('error', str(e))
            # Add retry logic
            await asyncio.sleep(5)
            return await bot_main()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(bot_main())
    except Exception as e:
        logger.error(f"Fatal bot error: {str(e)}")
    finally:
        loop.close()

if __name__ == '__main__':
    # Start bot in a separate thread
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Run Flask app
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)