from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app.models.database import db, User, TradingSettings, Transaction, AnalysisResult
from app.forms.main import TradingSettingsForm, APISettingsForm
from app.utils.api.binance_api import BinanceAPI
from app.utils.indicators.analysis import CryptoAnalyzer
from config import Config
from datetime import datetime, timedelta
import sys
import os
import pandas as pd
import ccxt
import concurrent.futures

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app

# Ana dizini Python path'ine ekle
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import backtest_strategy

bp = Blueprint('main', __name__)

# Desteklenen kripto para çiftleri
SUPPORTED_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", 
    "DOGE/USDT", "SOL/USDT", "DOT/USDT", "AVAX/USDT", "1000SHIB/USDT",
    "LINK/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "ETC/USDT"
]

# Desteklenen zaman dilimleri
TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]

@bp.route('/')
def index():
    predictions = []
    if current_user.is_authenticated:
        # Son tahminleri getir
        predictions = AnalysisResult.query.order_by(
            AnalysisResult.created_at.desc()
        ).limit(5).all()
    
    return render_template('main/index.html', predictions=predictions)

@bp.route('/dashboard')
@login_required
def dashboard():
    # Get user's trading settings
    settings = TradingSettings.query.filter_by(user_id=current_user.id, is_active=True).all()
    
    # Get user's active trades
    active_trades = Transaction.query.filter_by(user_id=current_user.id, status='open').all()
    
    # Get analysis results
    analysis_results = AnalysisResult.query.filter_by(symbol=current_user.trading_settings[0].symbol if current_user.trading_settings else None).all()
    
    return render_template('main/dashboard.html',
                         settings=settings,
                         active_trades=active_trades,
                         analysis_results=analysis_results)

@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    trading_form = TradingSettingsForm()
    api_form = APISettingsForm()
    
    if trading_form.validate_on_submit():
        # Update or create trading settings
        settings = TradingSettings.query.filter_by(
            user_id=current_user.id,
            symbol=trading_form.symbol.data,
            timeframe=trading_form.timeframe.data
        ).first()
        
        if settings:
            settings.leverage = trading_form.leverage.data
            settings.stop_loss = trading_form.stop_loss.data
            settings.take_profit = trading_form.take_profit.data
        else:
            settings = TradingSettings(
                user_id=current_user.id,
                symbol=trading_form.symbol.data,
                timeframe=trading_form.timeframe.data,
                leverage=trading_form.leverage.data,
                stop_loss=trading_form.stop_loss.data,
                take_profit=trading_form.take_profit.data
            )
            db.session.add(settings)
            
        db.session.commit()
        flash('Trading ayarları güncellendi', 'success')
        return redirect(url_for('main.settings'))
        
    if api_form.validate_on_submit():
        # Update API settings
        current_user.api_key = api_form.api_key.data
        current_user.api_secret = api_form.api_secret.data
        db.session.commit()
        flash('API ayarları güncellendi', 'success')
        return redirect(url_for('main.settings'))
        
    return render_template('main/settings.html',
                         trading_form=trading_form,
                         api_form=api_form)

@bp.route('/analyze/<symbol>/<timeframe>')
@login_required
def analyze(symbol, timeframe):
    # Initialize Binance API
    api = BinanceAPI(current_user.api_key, current_user.api_secret)
    
    # Initialize analyzer
    analyzer = CryptoAnalyzer(api.exchange, symbol, timeframe)
    
    # Perform analysis
    result = analyzer.analyze()
    
    # Save analysis result
    analysis = AnalysisResult(
        symbol=symbol,
        timeframe=timeframe,
        start_date=datetime.now() - timedelta(days=365*3),
        end_date=datetime.now(),
        success_rate=result['accuracy'],
        optimal_leverage=result['optimal_params']['leverage'],
        optimal_stop_loss=result['optimal_params']['stop_loss'],
        optimal_take_profit=result['optimal_params']['take_profit']
    )
    db.session.add(analysis)
    db.session.commit()
    
    return jsonify(result)

@bp.route('/start_trading/<settings_id>')
@login_required
def start_trading(settings_id):
    settings = TradingSettings.query.get_or_404(settings_id)
    
    if settings.user_id != current_user.id:
        flash('Bu ayarlara erişim izniniz yok', 'danger')
        return redirect(url_for('main.dashboard'))
        
    # Initialize Binance API
    api = BinanceAPI(current_user.api_key, current_user.api_secret)
    
    # Start trading
    # This would be handled by a background task in production
    # For now, we'll just update the settings
    settings.is_active = True
    db.session.commit()
    
    flash('Trading başlatıldı', 'success')
    return redirect(url_for('main.dashboard'))

@bp.route('/stop_trading/<settings_id>')
@login_required
def stop_trading(settings_id):
    settings = TradingSettings.query.get_or_404(settings_id)
    
    if settings.user_id != current_user.id:
        flash('Bu ayarlara erişim izniniz yok', 'danger')
        return redirect(url_for('main.dashboard'))
        
    # Stop trading
    settings.is_active = False
    db.session.commit()
    
    flash('Trading durduruldu', 'success')
    return redirect(url_for('main.dashboard'))


@bp.route('/analyze_parameters')
@login_required
def analyze_parameters():
    selected_symbol = request.args.get('symbol')
    symbols = SUPPORTED_SYMBOLS if not selected_symbol else [selected_symbol]
    all_results = {}

    # Get the app instance before creating threads
    app = current_app._get_current_object()  # This gets the actual app instance

    # Binance bağlantısını oluştur
    exchange = ccxt.binance({
        'options': {
            'defaultType': 'future'
        },
        'enableRateLimit': True
    })

    def analyze_symbol(symbol, flask_app):
        symbol_results = []
        print(f"Analyzing {symbol}...")

        for timeframe in TIMEFRAMES:
            try:
                # Her zaman dilimi için veri al
                bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=1000)
                df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])

                # Backtest yap
                result = backtest_strategy(timeframe, df)

                # Check if result is a dictionary and handle appropriately
                if isinstance(result, dict):
                    leverage = result.get('leverage', 0)
                    stop_percent = result.get('stop_percentage', 0)
                    successful_trades = result.get('successful_trades', 0)
                    unsuccessful_trades = result.get('unsuccessful_trades', 0)
                    final_balance = result.get('final_balance', 0)
                    success_rate = result.get('success_rate', 0)
                    profit_rate = result.get('profit_rate', 0) * 100  # Convert to percentage
                else:
                    # Try to handle it as a tuple as before
                    try:
                        if isinstance(result, tuple) and len(result) >= 5:
                            leverage, stop_percent, successful_trades, unsuccessful_trades, final_balance = result[:5]
                        else:
                            print(f"Warning: Unexpected result format from backtest_strategy for {symbol} {timeframe}")
                            leverage, stop_percent, successful_trades, unsuccessful_trades, final_balance = 0, 0, 0, 0, 0

                        # Calculate success and profit rates
                        total_trades = int(successful_trades) + int(unsuccessful_trades)
                        success_rate = (int(successful_trades) / total_trades * 100) if total_trades > 0 else 0
                        profit_rate = (float(final_balance) - 100.0) if final_balance != "0" else 0
                    except Exception as e:
                        print(f"Error parsing result for {symbol} {timeframe}: {str(e)}")
                        leverage, stop_percent, successful_trades, unsuccessful_trades, final_balance = 0, 0, 0, 0, 0
                        success_rate, profit_rate = 0, 0

                # Append the results
                symbol_results.append({
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'leverage': leverage,
                    'stop_percent': stop_percent,
                    'success_rate': round(success_rate, 2),
                    'profit_rate': round(profit_rate, 2),
                    'successful_trades': successful_trades,
                    'unsuccessful_trades': unsuccessful_trades,
                    'final_balance': final_balance
                })

                # Sonucu veritabanına kaydet - create a new app context in each thread
                with flask_app.app_context():
                    analysis = AnalysisResult(
                        symbol=symbol,
                        timeframe=timeframe,
                        start_date=datetime.fromtimestamp(bars[0][0] / 1000),
                        end_date=datetime.fromtimestamp(bars[-1][0] / 1000),
                        success_rate=success_rate,
                        optimal_leverage=float(leverage),
                        optimal_stop_loss=float(stop_percent),
                        optimal_take_profit=float(stop_percent)
                    )
                    db.session.add(analysis)
                    db.session.commit()  # Commit after each successful analysis

            except Exception as e:
                print(f"Error analyzing {symbol} {timeframe}: {str(e)}")
                continue

        return symbol_results

    try:
        # Çoklu işlem için ThreadPoolExecutor kullan - pass the app to each thread
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_symbol = {executor.submit(analyze_symbol, symbol, app): symbol for symbol in symbols}

            for future in concurrent.futures.as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    symbol_results = future.result()
                    if symbol_results:
                        all_results[symbol] = sorted(symbol_results, key=lambda x: float(x['profit_rate']),
                                                     reverse=True)
                except Exception as e:
                    print(f"Error processing {symbol}: {str(e)}")

        # En iyi sonuçları seç
        best_results = []
        for symbol, results in all_results.items():
            if results:  # Eğer sonuç varsa
                best_results.extend(results[:3])  # Her sembol için en iyi 3 sonucu al

        # Tüm en iyi sonuçları kâr oranına göre sırala
        best_results.sort(key=lambda x: float(x['profit_rate']), reverse=True)

        return render_template('main/analysis.html',
                               results=best_results,
                               all_results=all_results,
                               symbols=SUPPORTED_SYMBOLS,
                               selected_symbol=selected_symbol)
    except Exception as e:
        print(f"Error in analysis: {str(e)}")
        return render_template('main/analysis.html', error="Bir hata oluştu")

@bp.route('/analysis')
def analysis():
    # Tüm desteklenen sembolleri al
    symbols = SUPPORTED_SYMBOLS
    
    # URL'den seçili sembolü al
    selected_symbol = request.args.get('symbol')
    
    # Veritabanından sonuçları çek
    if selected_symbol:
        # Belirli bir sembol için sonuçları al
        results = AnalysisResult.query.filter_by(symbol=selected_symbol).order_by(AnalysisResult.profit_rate.desc()).all()
        all_results = {selected_symbol: results}
    else:
        # Tüm sembollerin sonuçlarını al
        results = AnalysisResult.query.order_by(AnalysisResult.profit_rate.desc()).limit(10).all()
        # Sembollere göre grupla
        all_results = {}
        for result in AnalysisResult.query.all():
            if result.symbol not in all_results:
                all_results[result.symbol] = []
            all_results[result.symbol].append(result)
    
    return render_template('main/analysis.html',
                         symbols=symbols,
                         selected_symbol=selected_symbol,
                         results=results,
                         all_results=all_results) 