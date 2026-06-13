from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session as flask_session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from flask_wtf.csrf import CSRFProtect
from flask_dance.contrib.google import make_google_blueprint, google
from sqlalchemy import text
from datetime import datetime
import os
import logging
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import our modular logic
from models.models import db, User, Portfolio, Transaction, QuizScore, PredictionHistory, OptionTrade
from utils.ai_helper import AIAssistant
from utils.market_helper import MarketData
from ml_model import predict_trend, generate_fake_history

app = Flask(__name__)

# Production Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_only_for_local_testing')
app.config['DEBUG'] = os.environ.get('DEBUG', 'False').lower() == 'true'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
ALPHA_VANTAGE_API_KEY = (
    os.environ.get("ALPHA_VANTAGE_API_KEY")
    or os.environ.get("ALPHA_VANTAGE_KEY")
    or "AIQSS37BIUJF5QVF"
)


import random

def get_stock_price(symbol):
    try:
        import yfinance as yf
        stock = yf.Ticker(symbol)
        data = stock.history(period="1d")

        if data.empty:
            return random.uniform(100, 1000)

        return float(data['Close'].iloc[-1])
    except:
        return random.uniform(100, 1000)

def predict_price(price):
    change = random.uniform(-2, 2)
    return round(price + change, 2)

# Database — PostgreSQL only (prefer .env DATABASE_URL)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:1234@localhost:5432/ai_stock_db",
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
logger.info("DATABASE URI configured for PostgreSQL")

# Google OAuth Configuration
google_bp = make_google_blueprint(
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    scope=["profile", "email"],
    offline=True
)
app.register_blueprint(google_bp, url_prefix="/login")

# Security and Extensions
csrf = CSRFProtect(app)
# Exempt API routes from CSRF if they use token-based auth or are simple AJAX from same domain
# For this project, we'll keep it simple and handle it in frontend

# Initialize Extensions
db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Add OAuth login logic
@app.route("/google_login")
def google_login():
    if not google.authorized:
        return redirect(url_for("google.login"))
    
    resp = google.get("/oauth2/v1/userinfo")
    assert resp.ok, resp.text
    info = resp.json()
    email = info["email"]
    google_id = info["id"]
    
    user = User.query.filter_by(email=email).first()
    if not user:
        # Auto-register user
        user = User(
            username=info.get("name", email.split('@')[0]),
            email=email,
            google_id=google_id
        )
        db.session.add(user)
        db.session.commit()
        logger.info(f"New user registered via Google: {email}")
    
    login_user(user)
    return redirect(url_for("dashboard"))

@app.context_processor
def inject_now():
    return {'today_date': datetime.now().strftime('%d %b, %Y')}

# =========================
# ERROR HANDLING
# =========================
@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html', user=current_user), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html', user=current_user), 500

@app.errorhandler(403)
def forbidden_error(error):
    return render_template('errors/403.html', user=current_user), 403

from flask_wtf.csrf import CSRFError
@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    logger.warning(f"CSRF Error: {e.description}")
    return jsonify({'success': False, 'msg': 'CSRF token missing or invalid. Please refresh the page.'}), 400

# =========================
# DB INIT
# =========================
with app.app_context():
    try:
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection established successfully")
        
        # In production, use migrations (Flask-Migrate)
        # For now, we use create_all() to ensure the latest schema
        db.create_all()
        print("Database initialized successfully")
        logger.info("Database initialized successfully")
    except Exception:
        logger.exception("Database connection or initialization failed")
        raise

# =========================
# AUTH ROUTES
# =========================
@app.route('/')
def home():
    print("Route working: /")
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html', user=current_user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    print("Route working: /register")
    if request.method == 'POST':
        hashed = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
        user = User(
            username=request.form['username'],
            email=request.form['email'],
            password=hashed
        )
        db.session.add(user)
        db.session.commit()
        flash("Welcome to AI Stock Pro! Start with ₹10,000 virtual balance.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    print("Route working: /login")
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and bcrypt.check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash("Invalid credentials", "danger")
    return render_template('login.html', user=current_user)

@app.route('/logout')
def logout():
    print("Route working: /logout")
    logout_user()
    return redirect(url_for('home'))

# =========================
# DASHBOARD & MARKETS
# =========================
@app.route('/dashboard')
@login_required
def dashboard():
    print("Route working: /dashboard")
    indices = MarketData.get_indices()
    market_summary = MarketData.get_market_summary()
    portfolio = Portfolio.query.filter_by(user_id=current_user.id).all()
    transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.timestamp.desc()).limit(5).all()
    
    # Calculate portfolio values
    invested_value = sum([p.buy_price * p.quantity for p in portfolio])
    current_value = invested_value # Placeholder
    today_gain = 0.0 # Placeholder
    
    return render_template('dashboard.html', 
                         user=current_user, 
                         indices=indices,
                         market=market_summary,
                         portfolio=portfolio,
                         transactions=transactions,
                         invested_value=invested_value,
                         current_value=current_value,
                         today_gain=today_gain)

@app.route('/markets')
@login_required
def markets():
    print("Route working: /markets")
    indices = MarketData.get_indices()
    market_summary = MarketData.get_market_summary()
    return render_template('markets.html', 
                         user=current_user, 
                         indices=indices, 
                         market=market_summary)

@app.route('/trade', methods=['GET'])
@login_required
def trade_page():
    print("Route working: /trade")
    symbol = request.args.get('symbol', 'TCS.NS')
    return render_template('trade.html', user=current_user, symbol=symbol)

@app.route('/market_summary')
@login_required
def market_summary_api():
    return jsonify(MarketData.get_market_summary())

@app.route('/get_stock_data', methods=['POST'])
@login_required
def get_stock_data():
    symbol = request.json.get('symbol', '').upper().strip()
    if not symbol:
        return jsonify({'success': False, 'error': 'Symbol is required'})
    
    # Ensure symbol always ends with .NS
    if not symbol.endswith('.NS') and not symbol.endswith('.BO'):
        symbol += '.NS'
    elif symbol.endswith('.BO'):
        symbol = symbol.replace('.BO', '.NS')
    
    try:
        price = get_stock_price(symbol)
            
        history = generate_fake_history(price)
        trend, predicted = predict_trend(history)
        
        return jsonify({
            'success': True, 
            'price': round(price, 2),
            'predicted': round(predicted, 2),
            'trend': trend,
            'symbol': symbol,
            'volatility': round(random.uniform(0.5, 3.0), 2),
            'momentum': round(random.uniform(-1, 1), 2),
            'risk': 'Low' if random.random() > 0.5 else 'Medium',
            'mood': trend
        })
    except Exception as e:
        logger.error(f"Error in /get_stock_data for {symbol}: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/ml_prediction', methods=['POST'])
@login_required
def ml_prediction():
    data = request.json
    symbol = data.get("symbol")

    price = get_stock_price(symbol)

    history = generate_fake_history(price)

    trend, predicted = predict_trend(history)

    return jsonify({
        "success": True,
        "trend": trend,
        "predicted_price": predicted,
        "history": history
    })

@app.route('/live_price', methods=['POST'])
@login_required
def live_price():
    data = request.json
    symbol = data.get('symbol', '').upper().strip()
    if not symbol:
        return jsonify({'success': False})

    try:
        price = get_stock_price(symbol)
            
        # For live price we need to return a dictionary with trend, change etc.
        # Simple local calculation for change
        change = round(random.uniform(-5, 5), 2)
        percent = round((change / price) * 100, 2)
        
        return jsonify({
            'success': True, 
            'symbol': symbol,
            'price': round(price, 2),
            'change': change,
            'percent': percent,
            'trend': 'Bullish' if change >= 0 else 'Bearish'
        })
    except Exception as e:
        logger.error("Live price fetch failed for %s: %s", symbol, e)
        return jsonify({'success': False, 'error': str(e)})

@app.route('/analyze', methods=['POST'])
@login_required
def analyze():
    symbol = request.json.get('symbol', '').upper().strip()
    if not symbol:
        return jsonify({'success': False})

    res = MarketData.get_analysis(symbol)
    if res:
        return jsonify(res)
    return jsonify({'success': False})

@app.route('/search_stocks')
@login_required
def search_stocks():
    query = request.args.get('q', '').upper()
    if not query:
        return jsonify([])

    stocks = [
        {"symbol": "RELIANCE.NS", "name": "Reliance Industries Ltd."},
        {"symbol": "TCS.NS", "name": "Tata Consultancy Services Ltd."},
        {"symbol": "INFY.NS", "name": "Infosys Ltd."},
        {"symbol": "HDFCBANK.NS", "name": "HDFC Bank Ltd."},
        {"symbol": "SBIN.NS", "name": "State Bank of India"},
        {"symbol": "ICICIBANK.NS", "name": "ICICI Bank Ltd."},
        {"symbol": "ITC.NS", "name": "ITC Ltd."},
        {"symbol": "HUL.NS", "name": "Hindustan Unilever Ltd."},
        {"symbol": "LT.NS", "name": "Larsen & Toubro Ltd."},
        {"symbol": "AXISBANK.NS", "name": "Axis Bank Ltd."},
        {"symbol": "KOTAKBANK.NS", "name": "Kotak Mahindra Bank Ltd."},
        {"symbol": "BHARTIARTL.NS", "name": "Bharti Airtel Ltd."},
        {"symbol": "WIPRO.NS", "name": "Wipro Ltd."},
        {"symbol": "ADANIENT.NS", "name": "Adani Enterprises Ltd."},
        {"symbol": "ADANIPORTS.NS", "name": "Adani Ports & SEZ Ltd."},
        {"symbol": "BAJFINANCE.NS", "name": "Bajaj Finance Ltd."},
        {"symbol": "BAJAJFINSV.NS", "name": "Bajaj Finserv Ltd."},
        {"symbol": "SUNPHARMA.NS", "name": "Sun Pharmaceutical Industries Ltd."},
        {"symbol": "M&M.NS", "name": "Mahindra & Mahindra Ltd."},
        {"symbol": "MARUTI.NS", "name": "Maruti Suzuki India Ltd."},
        {"symbol": "TATAMOTORS.NS", "name": "Tata Motors Ltd."},
        {"symbol": "JSWSTEEL.NS", "name": "JSW Steel Ltd."},
        {"symbol": "TATASTEEL.NS", "name": "Tata Steel Ltd."},
        {"symbol": "ONGC.NS", "name": "Oil & Natural Gas Corporation Ltd."},
        {"symbol": "POWERGRID.NS", "name": "Power Grid Corporation of India Ltd."},
        {"symbol": "NTPC.NS", "name": "NTPC Ltd."},
        {"symbol": "HINDALCO.NS", "name": "Hindalco Industries Ltd."},
        {"symbol": "COALINDIA.NS", "name": "Coal India Ltd."},
        {"symbol": "UPL.NS", "name": "UPL Ltd."},
        {"symbol": "GRASIM.NS", "name": "Grasim Industries Ltd."},
        {"symbol": "ULTRACEMCO.NS", "name": "UltraTech Cement Ltd."},
        {"symbol": "HEROMOTOCO.NS", "name": "Hero MotoCorp Ltd."},
        {"symbol": "EICHERMOT.NS", "name": "Eicher Motors Ltd."},
        {"symbol": "BPCL.NS", "name": "Bharat Petroleum Corporation Ltd."},
        {"symbol": "HCLTECH.NS", "name": "HCL Technologies Ltd."},
        {"symbol": "TECHM.NS", "name": "Tech Mahindra Ltd."},
        {"symbol": "ASIANPAINT.NS", "name": "Asian Paints Ltd."},
        {"symbol": "TITAN.NS", "name": "Titan Company Ltd."},
        {"symbol": "DIVISLAB.NS", "name": "Divi's Laboratories Ltd."},
        {"symbol": "DRREDDY.NS", "name": "Dr. Reddy's Laboratories Ltd."},
        {"symbol": "CIPLA.NS", "name": "Cipla Ltd."},
        {"symbol": "APOLLOHOSP.NS", "name": "Apollo Hospitals Enterprise Ltd."},
        {"symbol": "HDFCLIFE.NS", "name": "HDFC Life Insurance Company Ltd."},
        {"symbol": "SBILIFE.NS", "name": "SBI Life Insurance Company Ltd."},
        {"symbol": "BRITANNIA.NS", "name": "Britannia Industries Ltd."},
        {"symbol": "NESTLEIND.NS", "name": "Nestlé India Ltd."},
        {"symbol": "INDUSINDBK.NS", "name": "IndusInd Bank Ltd."}
    ]

    filtered_stocks = [
        s for s in stocks 
        if query in s['symbol'].upper() or query in s['name'].upper()
    ]
    return jsonify(filtered_stocks[:10])

# =========================
# AI & PREDICTION
# =========================
@app.route('/prediction')
@login_required
def prediction():
    print("Route working: /prediction")
    return render_template('prediction.html', user=current_user)

@app.route('/portfolio')
@login_required
def portfolio():
    print("Route working: /portfolio")
    portfolio_items = Portfolio.query.filter_by(user_id=current_user.id).all()
    
    # Calculate portfolio values
    invested_value = sum([p.buy_price * p.quantity for p in portfolio_items])
    current_value = invested_value # Dummy for now
    today_gain = 0.0 # Dummy for now
    
    return render_template('portfolio.html', 
                         user=current_user, 
                         portfolio=portfolio_items,
                         invested_value=invested_value,
                         current_value=current_value,
                         today_gain=today_gain)

@app.route('/predict', methods=['POST'])
@login_required
def predict():
    symbol = request.json.get('symbol', 'RELIANCE.NS').upper().strip()
    if not symbol.endswith('.NS') and not symbol.endswith('.BO'):
        symbol += '.NS'
    elif symbol.endswith('.BO'):
        symbol = symbol.replace('.BO', '.NS')
        
    res = AIAssistant.get_stock_prediction(symbol)
    if res['success']:
        # Store prediction history
        pred_entry = PredictionHistory(
            stock_symbol=symbol,
            predicted_price=res['predicted_price'],
            current_price=res['current_price'],
            confidence=res['confidence'],
            trend=res['trend'],
            ai_explanation=res['insights'][0],
            user_id=current_user.id
        )
        db.session.add(pred_entry)
        db.session.commit()
    return jsonify(res)

@app.route('/ai_chat', methods=['POST'])
@login_required
def ai_chat():
    query = request.json.get('message', '')
    context = request.json.get('context', {})
    
    # Simple logic-based agent
    query_lower = query.lower()
    response = ""
    
    if "buy" in query_lower or "sell" in query_lower:
        # Extract potential symbol
        symbol = context.get('symbol', 'TCS.NS')
        res = AIAssistant.get_stock_prediction(symbol)
        if res['success']:
            rec = "BUY" if res['trend'] == "Bullish" else "SELL"
            response = f"Analysis for {symbol}: The current trend is {res['trend']}. My technical model predicts a target of ₹{res['predicted_price']}. Recommendation: **{rec}**. *Disclaimer: Markets are risky.*"
        else:
            response = "I can't find data for that stock. Try 'Should I buy RELIANCE?'"
            
    elif "nifty" in query_lower:
        indices = MarketData.get_indices()
        nifty = next((i for i in indices if i['name'] == 'NIFTY 50'), None)
        if nifty:
            response = f"NIFTY 50 is currently at ₹{nifty['price']} ({nifty['percent']}%). It's the benchmark index for India's top 50 companies. The trend is {nifty['trend']}."
        else:
            response = "NIFTY 50 is India's premier stock index. It represents the weighted average of 50 large Indian companies."
            
    elif "best" in query_lower or "gainer" in query_lower:
        summary = MarketData.get_market_summary()
        top = summary['gainers'][0] if summary['gainers'] else None
        if top:
            response = f"Today's top gainer is {top['symbol']} at ₹{top['price']} (+{top['percent']}%). Always research before entering."
        else:
            response = "Markets are dynamic. Check the 'Markets' tab for real-time movers."
            
    else:
        response = AIAssistant.answer_query(query, context)
        
    return jsonify({'success': True, 'response': response})

# =========================
# TRADING MODULE
# =========================
@app.route('/trade', methods=['POST'])
@app.route('/execute_trade', methods=['POST'])
@login_required
def execute_trade():
    data = request.json
    symbol = data.get('symbol', '').upper().strip()
    qty = int(data.get('quantity', 0))
    trade_type = data.get('trade_type', 'Delivery') # 'Intraday' or 'Delivery'
    action = data.get('action') # 'Buy' or 'Sell'

    print(f"Received trade request - Symbol: {symbol}, Action: {action}, Qty: {qty}")

    if not symbol:
        return jsonify({'success': False, 'msg': 'Symbol required'})
    
    if qty <= 0:
        return jsonify({'success': False, 'msg': 'Quantity must be greater than 0'})

    try:
        price = get_stock_price(symbol)
            
        total_cost = price * qty
        
        if action == 'Buy':
            if current_user.balance >= total_cost:
                current_user.balance -= total_cost
                
                # Update Portfolio
                pos = Portfolio.query.filter_by(user_id=current_user.id, stock_symbol=symbol, trade_type=trade_type).first()
                if pos:
                    # Update average buy price
                    total_qty = pos.quantity + qty
                    pos.buy_price = ((pos.buy_price * pos.quantity) + (price * qty)) / total_qty
                    pos.quantity = total_qty
                    pos.current_price = price # Update current price too
                else:
                    new_pos = Portfolio(
                        stock_symbol=symbol, 
                        quantity=qty, 
                        buy_price=price, 
                        current_price=price, # Initial current price is buy price
                        trade_type=trade_type, 
                        user_id=current_user.id
                    )
                    db.session.add(new_pos)
                
                # Log Transaction
                txn = Transaction(stock_symbol=symbol, type='Buy', quantity=qty, price=price, trade_type=trade_type, user_id=current_user.id)
                db.session.add(txn)
                db.session.commit()
                return jsonify({'success': True, 'msg': f'Successfully bought {qty} shares of {symbol} at ₹{price}'})
            return jsonify({'success': False, 'msg': f'Insufficient balance. Need ₹{total_cost:.2f}, have ₹{current_user.balance:.2f}'})
        
        elif action == 'Sell':
            pos = Portfolio.query.filter_by(user_id=current_user.id, stock_symbol=symbol, trade_type=trade_type).first()
            if pos and pos.quantity >= qty:
                current_user.balance += total_cost
                pos.quantity -= qty
                if pos.quantity == 0:
                    db.session.delete(pos)
                
                # Log Transaction
                txn = Transaction(stock_symbol=symbol, type='Sell', quantity=qty, price=price, trade_type=trade_type, user_id=current_user.id)
                db.session.add(txn)
                db.session.commit()
                return jsonify({'success': True, 'msg': f'Successfully sold {qty} shares of {symbol} at ₹{price}'})
            return jsonify({'success': False, 'msg': f'Insufficient shares of {symbol} in your {trade_type} portfolio'})
            
    except Exception as e:
        print(f"Trade error: {str(e)}")
        return jsonify({'success': False, 'msg': f'Error executing trade: {str(e)}'})

# =========================
# F&O SIMULATION
# =========================
@app.route('/fno_trade', methods=['POST'])
@login_required
def fno_trade():
    data = request.json
    trade = OptionTrade(
        index_symbol=data['index'],
        option_type=data['type'],
        strike_price=data['strike'],
        expiry_date=data['expiry'],
        quantity=data['quantity'],
        buy_price=data['buy_price'],
        user_id=current_user.id
    )
    db.session.add(trade)
    db.session.commit()
    return jsonify({'success': True, 'msg': 'Option trade simulated successfully'})

# =========================
# OTHER ROUTES
# =========================
@app.route('/learning')
@login_required
def learning():
    print("Route working: /learning")
    return render_template('learning.html', user=current_user)

@app.route('/quiz')
@login_required
def quiz():
    logger.info(f"User {current_user.id} accessing /quiz")
    return render_template('quiz.html', user=current_user)

@app.route('/profile')
@login_required
def profile():
    print("Route working: /profile")
    trade_count = Transaction.query.filter_by(user_id=current_user.id).count()
    quiz_history = QuizScore.query.filter_by(user_id=current_user.id).order_by(QuizScore.timestamp.desc()).all()
    
    # Calculate simple badges
    badges = []
    if trade_count >= 1:
        badges.append({'name': 'First Trade', 'icon': 'fa-shopping-cart', 'color': 'text-success'})
    if len(quiz_history) >= 1:
        badges.append({'name': 'Quick Learner', 'icon': 'fa-bolt', 'color': 'text-warning'})
    if current_user.balance > 10000:
        badges.append({'name': 'Profit Maker', 'icon': 'fa-trending-up', 'color': 'text-primary'})

    return render_template('profile.html', 
                         user=current_user, 
                         trade_count=trade_count, 
                         quiz_history=quiz_history,
                         badges=badges)

@app.route('/save_quiz', methods=['POST'])
@login_required
def save_quiz():
    try:
        data = request.json
        if not data:
            logger.error("No JSON data received in /save_quiz")
            return jsonify({'success': False, 'msg': 'No data received'}), 400
            
        logger.info(f"Saving quiz score for user {current_user.id}: {data}")
        
        score = QuizScore(
            score=data.get('score', 0),
            total=data.get('total', 5),
            level=data.get('level', 'Beginner'),
            user_id=current_user.id
        )
        current_user.learning_level = data.get('level', 'Beginner')
        db.session.add(score)
        db.session.commit()
        logger.info("Quiz score saved successfully")
        return jsonify({'success': True})
    except Exception as e:
        logger.exception(f"Error saving quiz score: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'msg': str(e)}), 500

@app.route('/ml', methods=['POST']) 
def ml(): 
    import random 

    data = request.json 
    price = float(data.get("price", 100)) 

    # Simple ML logic (trend-based simulation) 
    history = [price + random.uniform(-5, 5) for _ in range(10)] 
    
    avg_price = sum(history) / len(history) 

    if price > avg_price: 
        trend = "Bearish" 
        predicted = round(price - random.uniform(1, 5), 2) 
    else: 
        trend = "Bullish" 
        predicted = round(price + random.uniform(1, 5), 2) 

    confidence = round(random.uniform(70, 95), 2) 

    return jsonify({ 
        "success": True, 
        "trend": trend, 
        "predicted": predicted, 
        "confidence": confidence 
    })

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000, debug=False)
