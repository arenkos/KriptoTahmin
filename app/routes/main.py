from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, session
from flask_login import login_required, current_user
from app.models.database import db, User, TradingSettings, Transaction, AnalysisResult
from app.forms.main import SettingsForm
from app.utils.api.binance_api import BinanceAPI
from app.utils.indicators.analysis import CryptoAnalyzer
from config import Config
from datetime import datetime, timedelta
import sys
import os
import pandas as pd
import ccxt
import concurrent.futures
import sqlite3
import subprocess
import signal
import traceback
import struct

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app

# Ana dizini Python path'ine ekle
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from main_strategy import backtest_strategy

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
    # Sayfalama için parametreleri al
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Her sayfada kaç işlem gösterileceği
    
    # Kullanıcının işlem geçmişini al
    transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(
        Transaction.created_at.desc()
    ).paginate(page=page, per_page=per_page)
    
    # Kullanıcının trading ayarlarını al (is_active filtresi kaldırıldı)
    settings = TradingSettings.query.filter_by(user_id=current_user.id).all()
    
    return render_template('main/dashboard.html',
                         settings=settings,
                         transactions=transactions)

@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = SettingsForm()
    # Form seçeneklerini doldur
    form.symbol.choices = [(s, s) for s in SUPPORTED_SYMBOLS]
    form.timeframe.choices = [(t, t) for t in TIMEFRAMES]

    # Düzenlenecek ayarın ID'sini al
    settings_id = request.args.get('settings_id', type=int)
    editing_settings = None
    if settings_id:
        editing_settings = TradingSettings.query.get_or_404(settings_id)
        if editing_settings.user_id != current_user.id:
            flash('Bu ayarlara erişim izniniz yok', 'danger')
            return redirect(url_for('main.dashboard'))

    if request.method == 'POST' and form.validate_on_submit():
        if editing_settings:
            # Mevcut ayarı güncelle
            editing_settings.symbol = form.symbol.data
            editing_settings.timeframe = form.timeframe.data
            editing_settings.leverage = form.leverage.data
            editing_settings.stop_loss = form.stop_loss.data
            editing_settings.take_profit = form.take_profit.data
            editing_settings.atr_period = form.atr_period.data
            editing_settings.atr_multiplier = form.atr_multiplier.data
            editing_settings.api_key = form.api_key.data
            editing_settings.api_secret = form.api_secret.data
            editing_settings.balance = form.balance.data
            editing_settings.updated_at = datetime.utcnow()
            flash('Ayar başarıyla güncellendi', 'success')
        else:
            # Yeni ayar oluştur
            new_settings = TradingSettings(
                user_id=current_user.id,
                symbol=form.symbol.data,
                timeframe=form.timeframe.data,
                leverage=form.leverage.data,
                stop_loss=form.stop_loss.data,
                take_profit=form.take_profit.data,
                atr_period=form.atr_period.data,
                atr_multiplier=form.atr_multiplier.data,
                api_key=form.api_key.data,
                api_secret=form.api_secret.data,
                balance=form.balance.data
            )
            db.session.add(new_settings)
            flash('Yeni ayar başarıyla oluşturuldu', 'success')
        
        db.session.commit()
        return redirect(url_for('main.dashboard'))

    # GET ise mevcut ayarları forma doldur
    if request.method == 'GET':
        if editing_settings:
            # Düzenlenen ayarın bilgilerini forma doldur
            form.symbol.data = editing_settings.symbol
            form.timeframe.data = editing_settings.timeframe
            form.leverage.data = editing_settings.leverage
            form.stop_loss.data = editing_settings.stop_loss
            form.take_profit.data = editing_settings.take_profit
            form.atr_period.data = editing_settings.atr_period
            form.atr_multiplier.data = editing_settings.atr_multiplier
            form.api_key.data = editing_settings.api_key
            form.api_secret.data = editing_settings.api_secret
            form.balance.data = editing_settings.balance
        else:
            # Yeni ayar için son kullanılan ayarları doldur
            last_settings = TradingSettings.query.filter_by(
                user_id=current_user.id
            ).order_by(TradingSettings.updated_at.desc()).first()
            if last_settings:
                form.symbol.data = last_settings.symbol
                form.timeframe.data = last_settings.timeframe
                form.leverage.data = last_settings.leverage
                form.stop_loss.data = last_settings.stop_loss
                form.take_profit.data = last_settings.take_profit
                form.atr_period.data = last_settings.atr_period
                form.atr_multiplier.data = last_settings.atr_multiplier
                form.api_key.data = last_settings.api_key
                form.api_secret.data = last_settings.api_secret
                form.balance.data = last_settings.balance

    return render_template('main/settings.html', form=form, editing_settings=editing_settings)

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
    settings.binance_active = True
    settings.telegram_active = True
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
    settings.binance_active = False
    settings.telegram_active = False
    db.session.commit()
    
    flash('Trading durduruldu', 'success')
    return redirect(url_for('main.dashboard'))

@bp.route('/start_binance/<settings_id>')
@login_required
def start_binance(settings_id):
    settings = TradingSettings.query.get_or_404(settings_id)
    if settings.user_id != current_user.id:
        flash('Bu ayarlara erişim izniniz yok', 'danger')
        return redirect(url_for('main.dashboard'))
    if not current_user.api_key or not current_user.api_secret or not current_user.balance:
        flash('Binance işlemlerini başlatmak için API bilgilerinizi ve bakiyenizi girin.', 'warning')
        return redirect(url_for('main.settings'))
    settings.binance_active = True
    db.session.commit()
    # trade.py'yi Binance için başlat
    subprocess.Popen([sys.executable, "trade.py", "--mode", "binance", "--settings_id", str(settings.id)])
    flash('Binance işlemleri başlatıldı', 'success')
    return redirect(url_for('main.dashboard'))

@bp.route('/stop_binance/<settings_id>')
@login_required
def stop_binance(settings_id):
    settings = TradingSettings.query.get_or_404(settings_id)
    if settings.user_id != current_user.id:
        flash('Bu ayarlara erişim izniniz yok', 'danger')
        return redirect(url_for('main.dashboard'))
    settings.binance_active = False
    db.session.commit()
    # trade.py process'ini durdur (ör: PID dosyasından oku ve öldür)
    try:
        with open(f"binance_pid_{settings.id}.txt", "r") as f:
            pid = int(f.read())
        os.kill(pid, signal.SIGTERM)
    except Exception as e:
        print(f"Binance işlemi durdurulamadı: {e}")
    flash('Binance işlemleri durduruldu', 'success')
    return redirect(url_for('main.dashboard'))

@bp.route('/start_telegram/<settings_id>')
@login_required
def start_telegram(settings_id):
    settings = TradingSettings.query.get_or_404(settings_id)
    if settings.user_id != current_user.id:
        flash('Bu ayarlara erişim izniniz yok', 'danger')
        return redirect(url_for('main.dashboard'))
    settings.telegram_active = True
    db.session.commit()
    # trade.py'yi Telegram için başlat
    subprocess.Popen([sys.executable, "trade.py", "--mode", "telegram", "--settings_id", str(settings.id)])
    flash('Telegram sinyali başlatıldı', 'success')
    return redirect(url_for('main.dashboard'))

@bp.route('/stop_telegram/<settings_id>')
@login_required
def stop_telegram(settings_id):
    settings = TradingSettings.query.get_or_404(settings_id)
    if settings.user_id != current_user.id:
        flash('Bu ayarlara erişim izniniz yok', 'danger')
        return redirect(url_for('main.dashboard'))
    settings.telegram_active = False
    db.session.commit()
    # Burada arka planda telegram sinyalini durdurabilirsin
    # ör: telegram_bot.stop(settings)
    flash('Telegram sinyali durduruldu', 'success')
    return redirect(url_for('main.dashboard'))

@bp.route('/delete_setting/<settings_id>')
@login_required
def delete_setting(settings_id):
    settings = TradingSettings.query.get_or_404(settings_id)
    if settings.user_id != current_user.id:
        flash('Bu ayarlara erişim izniniz yok', 'danger')
        return redirect(url_for('main.dashboard'))
    db.session.delete(settings)
    db.session.commit()
    flash('Ayar silindi', 'success')
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
@login_required
def analysis():
    """Parametre analizi sayfası"""
    symbol = request.args.get('symbol', 'BTC/USDT')
    
    # Desteklenen semboller
    symbols = [
        "BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT",
        "DOGE/USDT", "SOL/USDT", "DOT/USDT", "AVAX/USDT", "1000SHIB/USDT",
        "LINK/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "ETC/USDT"
    ]
    
    # Analiz parametreleri
    timeframes = ["1h", "4h", "1d"]
    leverages = [1, 2, 3, 5, 10]
    stop_losses = [1, 2, 3, 5]
    take_profits = [2, 3, 5, 10]
    atr_periods = [10, 14, 20]
    atr_multipliers = [2, 3, 4]
    
    results = []
    
    # Her parametre kombinasyonu için test yap
    for timeframe in timeframes:
        for leverage in leverages:
            for stop_loss in stop_losses:
                for take_profit in take_profits:
                    for atr_period in atr_periods:
                        for atr_multiplier in atr_multipliers:
                            # Veriyi al
                            df = fetch_data_from_db(symbol, timeframe)
                            if df is None or df.empty:
                                continue
                            
                            # Stratejiyi test et
                            result = backtest_strategy(
                                df,
                                initial_balance=1000,  # Başlangıç bakiyesi
                                leverage=leverage,
                                stop_loss_percentage=stop_loss,
                                take_profit_percentage=take_profit,
                                atr_period=atr_period,
                                atr_multiplier=atr_multiplier
                            )
                            
                            # Sonuçları kaydet
                            analysis_result = AnalysisResult(
                                user_id=current_user.id,
                                symbol=symbol,
                                timeframe=timeframe,
                                leverage=leverage,
                                stop_loss=stop_loss,
                                take_profit=take_profit,
                                atr_period=atr_period,
                                atr_multiplier=atr_multiplier,
                                successful_trades=result['successful_trades'],
                                unsuccessful_trades=result['unsuccessful_trades'],
                                success_rate=result['success_rate'],
                                final_balance=result['final_balance'],
                                profit_rate=result['profit_rate'],
                                trade_closed=result['trade_closed']
                            )
                            db.session.add(analysis_result)
                            
                            # İşlemleri kaydet
                            for transaction in result['transactions']:
                                db_transaction = Transaction(
                                    user_id=current_user.id,
                                    symbol=symbol,
                                    timeframe=timeframe,
                                    trade_type=transaction['trade_type'],
                                    entry_price=transaction['entry_price'],
                                    entry_time=transaction['entry_time'],
                                    entry_balance=transaction['entry_balance'],
                                    exit_price=transaction.get('exit_price'),
                                    exit_time=transaction.get('exit_time'),
                                    exit_balance=transaction.get('exit_balance'),
                                    profit_loss=transaction.get('profit_loss'),
                                    trade_closed=transaction['trade_closed']
                                )
                                db.session.add(db_transaction)
                            
                            results.append({
                                'symbol': symbol,
                                'timeframe': timeframe,
                                'leverage': leverage,
                                'stop_loss': stop_loss,
                                'take_profit': take_profit,
                                'atr_period': atr_period,
                                'atr_multiplier': atr_multiplier,
                                'successful_trades': result['successful_trades'],
                                'unsuccessful_trades': result['unsuccessful_trades'],
                                'success_rate': result['success_rate'],
                                'final_balance': result['final_balance'],
                                'profit_rate': result['profit_rate'],
                                'trade_closed': result['trade_closed']
                            })
    
    # Değişiklikleri kaydet
    db.session.commit()
    
    # Sonuçları kar oranına göre sırala
    results.sort(key=lambda x: x['profit_rate'], reverse=True)
    
    return render_template('main/param_analysis.html',
                         results=results,
                         symbols=symbols,
                         selected_symbol=symbol)

@bp.route('/param_analysis')
def param_analysis():
    # SQLite veritabanından doğrudan analysis_results tablosundaki verileri çek
    try:
        # crypto_data.db veritabanına bağlan
        conn = sqlite3.connect('crypto_data.db')
        conn.row_factory = sqlite3.Row  # Sonuçları sözlük olarak al
        cursor = conn.cursor()
        
        # analysis_results tablosunun varlığını kontrol et
        cursor.execute('''
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='analysis_results'
        ''')
        
        if not cursor.fetchone():
            conn.close()
            return render_template('main/param_analysis.html', 
                                error="Analiz sonuçları bulunamadı. Lütfen önce analiz işlemini çalıştırın.")
        
        # Verileri sorgula
        cursor.execute('''
        SELECT * FROM analysis_results ORDER BY final_balance DESC
        ''')
        
        results = cursor.fetchall()
        
        # Sonuçları sembollere göre grupla
        all_results = {}
        for row in results:
            symbol = row['symbol']
            if symbol not in all_results:
                all_results[symbol] = []
            all_results[symbol].append(dict(row))
        
        # Bütün sembolleri al
        cursor.execute('SELECT DISTINCT symbol FROM analysis_results')
        symbols = [row['symbol'] for row in cursor.fetchall()]
        
        # URL'den seçili sembolü al
        selected_symbol = request.args.get('symbol')
        if selected_symbol and selected_symbol in all_results:
            filtered_results = all_results[selected_symbol]
        else:
            # Eğer seçili sembol yoksa veya geçersizse tüm sonuçlar
            filtered_results = results
            
        # Desteklenen zaman dilimleri
        timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]
        
        # Her zaman dilimi için sonuç bul
        timeframe_results = {}
        for timeframe in timeframes:
            timeframe_results[timeframe] = []
            for symbol, res_list in all_results.items():
                for res in res_list:
                    if res['timeframe'] == timeframe:
                        timeframe_results[timeframe].append(res)
        
        conn.close()
        
        return render_template('main/param_analysis.html',
                             symbols=symbols,
                             selected_symbol=selected_symbol,
                             results=filtered_results,
                             all_results=all_results,
                             timeframes=timeframes,
                             timeframe_results=timeframe_results)
    except Exception as e:
        print(f"Veritabanı hatası: {str(e)}")
        return render_template('main/param_analysis.html', error=f"Veritabanı hatası: {str(e)}")

@bp.route('/apply_settings')
@login_required
def apply_settings():
    # URL parametrelerinden ayarları al
    symbol = request.args.get('symbol')
    timeframe = request.args.get('timeframe')
    leverage = float(request.args.get('leverage', 1))
    stop_percentage = float(request.args.get('stop_percentage', 1))
    kar_al_percentage = float(request.args.get('kar_al_percentage', 2))
    atr_period = int(request.args.get('atr_period', 10))
    atr_multiplier = float(request.args.get('atr_multiplier', 3.0))

    # Yeni trading ayarı oluştur
    new_settings = TradingSettings(
        user_id=current_user.id,
        symbol=symbol,
        timeframe=timeframe,
        leverage=leverage,
        stop_loss=stop_percentage,
        take_profit=kar_al_percentage,
        atr_period=atr_period,
        atr_multiplier=atr_multiplier
    )
    
    db.session.add(new_settings)
    db.session.commit()
    
    flash('Ayarlar başarıyla uygulandı', 'success')
    return redirect(url_for('main.settings', settings_id=new_settings.id))

@bp.route('/transaction_history/<symbol>/<timeframe>')
@login_required
def transaction_history(symbol, timeframe):
    try:
        # Sayfalama için parametreleri al
        page = request.args.get('page', 1, type=int)
        per_page = 10  # Sayfa başına gösterilecek işlem sayısı

        # SQLite veritabanına bağlan
        conn = sqlite3.connect('crypto_data.db')
        cursor = conn.cursor()

        # En güncel analysis_id'yi bul
        cursor.execute("""
            SELECT id FROM analysis_results
            WHERE symbol = ? AND timeframe = ?
            ORDER BY created_at DESC LIMIT 1
        """, (symbol, timeframe))
        row = cursor.fetchone()
        if not row:
            total = 0
            transactions = []
        else:
            latest_analysis_id = row[0]
            # Toplam işlem sayısı
            cursor.execute("""
                SELECT COUNT(*) FROM backtest_transactions
                WHERE analysis_id = ?
            """, (latest_analysis_id,))
            total = cursor.fetchone()[0]
            # Sayfalama için offset hesapla
            offset = (page - 1) * per_page
            # İşlemleri getir
            cursor.execute("""
                SELECT trade_type, entry_price, entry_time, entry_balance,
                       exit_price, exit_time, exit_balance, profit_loss, trade_closed
                FROM backtest_transactions
                WHERE analysis_id = ?
                ORDER BY entry_time DESC
                LIMIT ? OFFSET ?
            """, (latest_analysis_id, per_page, offset))
            transactions_data = cursor.fetchall()

            # Verileri işle
            transactions = []
            for t in transactions_data:
                try:
                    # Timestamp'i kontrol et (milisaniye mi, saniye mi?)
                    entry_timestamp = int(t[2]) if t[2] else None
                    exit_timestamp = int(t[5]) if t[5] else None
                    # Milisaniye/saniye ayrımı: 10 haneli ise saniye, 13 haneli ise milisaniye
                    def ts_to_dt(ts):
                        if not ts:
                            return None
                        ts = int(ts)
                        if len(str(ts)) > 10:
                            return datetime.fromtimestamp(ts / 1000)
                        else:
                            return datetime.fromtimestamp(ts)
                    transaction = {
                        'trade_type': t[0],
                        'entry_price': t[1],
                        'entry_time': ts_to_dt(entry_timestamp),
                        'entry_balance': t[3],
                        'exit_price': t[4],
                        'exit_time': ts_to_dt(exit_timestamp),
                        'exit_balance': t[6],
                        'profit_loss': t[7],
                        'trade_closed': bool(t[8])
                    }
                    transactions.append(transaction)
                except Exception as e:
                    print(f"İşlem dönüştürme hatası: {str(e)}")
                    continue

        # Sayfalama sınıfı
        class Pagination:
            def __init__(self, items, page, per_page, total):
                self.items = items
                self.page = page
                self.per_page = per_page
                self.total = total
                self.pages = (total + per_page - 1) // per_page
                self.has_prev = page > 1
                self.has_next = page < self.pages
                self.prev_num = page - 1
                self.next_num = page + 1

            def iter_pages(self, left_edge=2, left_current=2, right_current=3, right_edge=2):
                last = 0
                for num in range(1, self.pages + 1):
                    if (num <= left_edge or
                        (num > self.page - left_current - 1 and
                         num < self.page + right_current) or
                        num > self.pages - right_edge + 1):
                        if last + 1 != num:
                            yield None
                        yield num
                        last = num

        # Sayfalama nesnesi oluştur
        pagination = Pagination(transactions, page, per_page, total)

        conn.close()

        return render_template('main/transaction_history.html',
                             symbol=symbol,
                             timeframe=timeframe,
                             transactions=pagination)

    except Exception as e:
        print(f"İşlem geçmişi yüklenirken hata: {str(e)}")
        traceback.print_exc()
        flash('İşlem geçmişi yüklenirken bir hata oluştu. Lütfen daha sonra tekrar deneyin.', 'error')
        return redirect(url_for('main.dashboard')) 