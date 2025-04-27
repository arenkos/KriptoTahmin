import os
from dotenv import load_dotenv
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'gizli-anahtar-buraya'
    
    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Flask-Login
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    
    # Uygulama ayarları
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY')
    BINANCE_API_SECRET = os.environ.get('BINANCE_API_SECRET')
    
    # Tahmin ayarları
    DEFAULT_SYMBOL = 'BTC/USDT'
    DEFAULT_TIMEFRAME = '1h'
    DEFAULT_LEVERAGE = 1
    DEFAULT_STOP_LOSS = 2.0  # %
    DEFAULT_TAKE_PROFIT = 4.0  # %
    
    # Analysis Settings
    DEFAULT_TIMEFRAMES = ['1m', '15m', '1h', '4h', '1d']
    DEFAULT_SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'ADA/USDT', 'SOL/USDT']
    ANALYSIS_PERIOD = 3  # years
    MIN_TRADING_VOLUME = 1000000  # minimum 24h volume in USDT
    
    # Trading Settings
    MAX_LEVERAGE = 20
    MIN_STOP_LOSS = 0.5  # 0.5%
    MAX_STOP_LOSS = 5.0  # 5%
    MIN_TAKE_PROFIT = 1.0  # 1%
    MAX_TAKE_PROFIT = 10.0  # 10% 