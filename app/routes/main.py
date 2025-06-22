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
import mysql.connector
import subprocess
import signal
import traceback
import struct

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app

# MySQL bağlantı fonksiyonu
def get_mysql_connection():
    try:
        return mysql.connector.connect(
            host="193.203.168.175",
            user="u162605596_kripto2",
            password="Arenkos1.",
            database="u162605596_kripto2",
            connection_timeout=60,
            autocommit=True,
            buffered=True
        )
    except mysql.connector.Error as err:
        print(f"MySQL bağlantı hatası: {err}")
        return None

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
    # Sadece ilgili kullanıcıya göster
    user_email = current_user.email
    if user_email != 'aren_32@hotmail.com':
        flash('Bu sayfaya erişim izniniz yok.', 'danger')
        return redirect(url_for('main.index'))

    # Filtre parametreleri
    page = request.args.get('page', 1, type=int)
    per_page = 10
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    trade_type = request.args.get('trade_type')
    success = request.args.get('success')

    conn = get_mysql_connection()
    if not conn:
        return render_template('main/dashboard.html', 
                            error="Veritabanı bağlantısı kurulamadı.")
    cursor = conn.cursor()

    where_clauses = ["user_email = %s"]
    params = [user_email]
    if trade_type in ('LONG', 'SHORT'):
        where_clauses.append("trade_type = %s")
        params.append(trade_type)
    if success == '1':
        where_clauses.append("profit_loss > 0")
    elif success == '0':
        where_clauses.append("profit_loss <= 0")
    if start_date:
        where_clauses.append("entry_time >= %s")
        try:
            start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp()) * 1000
        except:
            start_ts = 0
        params.append(start_ts)
    if end_date:
        where_clauses.append("entry_time <= %s")
        try:
            end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp()) * 1000
        except:
            end_ts = 9999999999999
        params.append(end_ts)
    where_sql = " AND ".join(where_clauses)

    # DEBUG: SQL ve parametreler
    print("DEBUG SQL:", where_sql)
    print("DEBUG PARAMS:", params)
    print("DEBUG SQL COUNT:", where_sql.count('%s'))
    print("DEBUG PARAMS LEN:", len(params))
    if where_sql.count('%s') != len(params):
        raise Exception(f'SQL parametre sayısı ile params listesi eşleşmiyor! SQL: {where_sql}, params: {params}')

    # Toplam işlem sayısı
    cursor.execute(f"""
        SELECT COUNT(*) FROM realtime_transactions WHERE {where_sql}
    """, params)
    total = cursor.fetchone()[0]
    offset = (page - 1) * per_page

    # İşlemleri getir
    cursor.execute(f"""
        SELECT trade_type, entry_price, entry_time, entry_balance,
               exit_price, exit_time, exit_balance, profit_loss, trade_closed
        FROM realtime_transactions
        WHERE {where_sql}
        ORDER BY entry_time DESC
        LIMIT %s OFFSET %s
    """, params + [per_page, offset])
    transactions_data = cursor.fetchall()

    # Tüm filtreli işlemleri istatistik için çek
    cursor.execute(f"""
        SELECT trade_type, profit_loss, trade_closed FROM realtime_transactions WHERE {where_sql}
    """, params)
    all_data = cursor.fetchall()

    # Verileri işle
    transactions = []
    for t in transactions_data:
        try:
            # entry_time ve exit_time'ı işlerken bytes tipi kontrolü ekle
            entry_timestamp_raw = t[2]
            exit_timestamp_raw = t[5]

            entry_timestamp = None
            if entry_timestamp_raw is not None:
                if isinstance(entry_timestamp_raw, bytes):
                    if len(entry_timestamp_raw) == 8: # Genellikle 8 bayt unsigned long long
                        entry_timestamp = struct.unpack('<Q', entry_timestamp_raw)[0]
                    else:
                        print(f"Uyarı: Beklenmeyen bytes uzunluğu için entry_timestamp_raw: {entry_timestamp_raw}. Atlanıyor.")
                else:
                    entry_timestamp = int(entry_timestamp_raw)

            exit_timestamp = None
            if exit_timestamp_raw is not None:
                if isinstance(exit_timestamp_raw, bytes):
                    if len(exit_timestamp_raw) == 8:
                        exit_timestamp = struct.unpack('<Q', exit_timestamp_raw)[0]
                    else:
                        print(f"Uyarı: Beklenmeyen bytes uzunluğu için exit_timestamp_raw: {exit_timestamp_raw}. Atlanıyor.")
                else:
                    exit_timestamp = int(exit_timestamp_raw)

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
                'profit_loss': t[7] if t[7] is not None else 0,
                'trade_closed': bool(t[8])
            }
            transactions.append(transaction)
        except Exception as e:
            print(f"İşlem dönüştürme hatası: {str(e)}")
            continue

    # İstatistikleri hesapla
    total_long = sum(1 for x in all_data if x[0] == 'LONG')
    total_short = sum(1 for x in all_data if x[0] == 'SHORT')
    long_success = sum(1 for x in all_data if x[0] == 'LONG' and x[1] is not None and x[1] > 0)
    short_success = sum(1 for x in all_data if x[0] == 'SHORT' and x[1] is not None and x[1] > 0)
    total_trades = len(all_data)
    successful_trades = sum(1 for x in all_data if x[1] is not None and x[1] > 0)
    total_profit = sum(x[1] for x in all_data if x[1] is not None)
    total_loss = sum(x[1] for x in all_data if x[1] is not None and x[1] < 0)
    profits = [x[1] for x in all_data if x[1] is not None and x[1] > 0]
    losses = [x[1] for x in all_data if x[1] is not None and x[1] <= 0]
    stats = {
        'total_trades': total_trades,
        'successful_trades': successful_trades,
        'success_rate': (successful_trades / total_trades * 100) if total_trades > 0 else 0,
        'total_profit': total_profit,
        'total_loss': total_loss,
        'total_long': total_long,
        'total_short': total_short,
        'long_success': long_success,
        'short_success': short_success,
        'long_success_rate': (long_success / total_long * 100) if total_long > 0 else 0,
        'short_success_rate': (short_success / total_short * 100) if total_short > 0 else 0,
        'max_profit': max(profits) if profits else 0,
        'min_profit': min(losses) if losses else 0
    }

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
            self.prev_num = page - 1 if self.has_prev else None
            self.next_num = page + 1 if self.has_next else None

        def iter_pages(self, left_edge=2, left_current=2, right_current=3, right_edge=2):
            last = 0
            for num in range(1, self.pages + 1):
                if (num <= left_edge or 
                    (num > self.page - left_current - 1 and 
                     num < self.page + right_current) or 
                    num > self.pages - right_edge):
                    if last + 1 != num:
                        yield None
                    yield num
                    last = num

    pagination = Pagination(transactions, page, per_page, total)
    
    # Kullanıcının trading ayarlarını al
    settings = TradingSettings.query.filter_by(user_id=current_user.id).all()
    
    conn.close()

    return render_template('main/dashboard.html',
                        settings=settings,
                        transactions=pagination,
                        stats=stats,
                        filters={
                            'start_date': start_date,
                            'end_date': end_date,
                            'trade_type': trade_type,
                            'success': success
                        })

@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = SettingsForm()
    settings_id = request.args.get('settings_id')
    editing_settings = None

    # Eğer bir ayar düzenleniyorsa, onu bul
    if settings_id:
        editing_settings = TradingSettings.query.get_or_404(settings_id)
        if current_user.id != editing_settings.user_id:
            flash('Bu işlem için yetkiniz yok', 'danger')
            return redirect(url_for('main.dashboard'))

    # Form gönderildiğinde ve geçerli olduğunda
    if form.validate_on_submit():
        # Kullanılacak ayar nesnesini belirle (yeni veya mevcut)
        target_settings = editing_settings if editing_settings else TradingSettings(user_id=current_user.id)
        
        # Form verilerini nesneye ata
        form.populate_obj(target_settings)

        # Veritabanına ekle/güncelle ve kaydet
        if not editing_settings:
            db.session.add(target_settings)
        db.session.commit()
        
        flash('Ayarlar kaydedildi', 'success')
        return redirect(url_for('main.dashboard'))

    # Sayfa ilk kez yükleniyorsa (GET request)
    if request.method == 'GET':
        if editing_settings:
            # Düzenleme modundaysa, form'u mevcut ayarlarla doldur
            form.process(obj=editing_settings)
        else:
            # Yeni ayar modundaysa, kullanıcının son ayarlarını bul ve form'u doldur
            last_settings = TradingSettings.query.filter_by(user_id=current_user.id).order_by(TradingSettings.updated_at.desc()).first()
            if last_settings:
                form.process(obj=last_settings)

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
    # MySQL veritabanından doğrudan analysis_results tablosundaki verileri çek
    try:
        # MySQL veritabanına bağlan
        conn = get_mysql_connection()
        if not conn:
            return render_template('main/param_analysis.html', 
                                error="Veritabanı bağlantısı kurulamadı.")
        cursor = conn.cursor(dictionary=True)  # Sonuçları sözlük olarak al
        
        # analysis_results tablosunun varlığını kontrol et
        cursor.execute('''
        SELECT TABLE_NAME FROM information_schema.TABLES 
        WHERE TABLE_SCHEMA = 'u162605596_kripto2' AND TABLE_NAME = 'analysis_results'
        ''')
        
        if not cursor.fetchone():
            conn.close()
            return render_template('main/param_analysis.html', 
                                error="Analiz sonuçları bulunamadı. Lütfen önce analiz işlemini çalıştırın.")
        
        # Verileri sorgula
        cursor.execute('''
        SELECT * FROM analysis_results WHERE final_balance >= 100 ORDER BY final_balance DESC
        ''')
        
        results = cursor.fetchall()
        
        # Sonuçları sembollere göre grupla
        all_results = {}
        for row in results:
            symbol = row['symbol']
            if symbol not in all_results:
                all_results[symbol] = []
            all_results[symbol].append(row)
        
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
        for tf in timeframes:
            cursor.execute('''
            SELECT * FROM analysis_results 
            WHERE timeframe = %s AND final_balance >= 100 
            ORDER BY final_balance DESC
            ''', (tf,))
            timeframe_results[tf] = cursor.fetchall()
        
        conn.close()
        
        return render_template('main/param_analysis.html',
                            all_results=all_results,
                            filtered_results=filtered_results,
                            symbols=symbols,
                            selected_symbol=selected_symbol,
                            timeframes=timeframes,
                            timeframe_results=timeframe_results)
                            
    except Exception as e:
        print(f"Param analysis hatası: {str(e)}")
        return render_template('main/param_analysis.html', 
                            error=f"Veri çekme hatası: {str(e)}")

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
        page = request.args.get('page', 1, type=int)
        per_page = 10
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        trade_type = request.args.get('trade_type')
        success = request.args.get('success')

        conn = get_mysql_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id FROM analysis_results
            WHERE symbol = %s AND timeframe = %s
            ORDER BY created_at DESC LIMIT 1
        """, (symbol, timeframe))
        row = cursor.fetchone()
        if not row:
            total = 0
            transactions = []
            stats = {}
        else:
            latest_analysis_id = row['id']
            where_clauses = ["analysis_id = %s"]
            params = [latest_analysis_id]
            if trade_type in ('LONG', 'SHORT'):
                where_clauses.append("trade_type = %s")
                params.append(trade_type)
            if success == '1':
                where_clauses.append("profit_loss > 0")
            elif success == '0':
                where_clauses.append("profit_loss <= 0")
            if start_date:
                where_clauses.append("entry_time >= %s")
                try:
                    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp()) * 1000
                except:
                    start_ts = 0
                params.append(start_ts)
            if end_date:
                where_clauses.append("entry_time <= %s")
                try:
                    end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp()) * 1000
                except:
                    end_ts = 9999999999999
                params.append(end_ts)
            where_sql = " AND ".join(where_clauses)

            print("DEBUG SQL:", where_sql)
            print("DEBUG PARAMS:", params)
            print("DEBUG SQL COUNT:", where_sql.count('%s'))
            print("DEBUG PARAMS LEN:", len(params))
            if where_sql.count('%s') != len(params):
                raise Exception(f'SQL parametre sayısı ile params listesi eşleşmiyor! SQL: {where_sql}, params: {params}')

            cursor.execute(f"""
                SELECT COUNT(*) FROM backtest_transactions
                WHERE {where_sql}
            """, params)
            count_row = cursor.fetchone()
            try:
                total = count_row['COUNT(*)']
            except:
                total = count_row[0]
            offset = (page - 1) * per_page

            cursor.execute(f"""
                SELECT trade_type, entry_price, entry_time, entry_balance,
                       exit_price, exit_time, exit_balance, profit_loss, trade_closed
                FROM backtest_transactions
                WHERE {where_sql}
                ORDER BY entry_time DESC
                LIMIT %s OFFSET %s
            """, params + [per_page, offset])
            transactions_data = cursor.fetchall()

            cursor.execute(f"""
                SELECT trade_type, profit_loss, trade_closed
                FROM backtest_transactions
                WHERE {where_sql}
            """, params)
            all_data = cursor.fetchall()

            transactions = []
            for t in transactions_data:
                try:
                    entry_timestamp = int(t['entry_time']) if t['entry_time'] else None
                    exit_timestamp = int(t['exit_time']) if t['exit_time'] else None
                    def ts_to_dt(ts):
                        if not ts:
                            return None
                        ts = int(ts)
                        if len(str(ts)) > 10:
                            return datetime.fromtimestamp(ts / 1000)
                        else:
                            return datetime.fromtimestamp(ts)
                    transaction = {
                        'trade_type': t['trade_type'],
                        'entry_price': t['entry_price'],
                        'entry_time': ts_to_dt(entry_timestamp),
                        'entry_balance': t['entry_balance'],
                        'exit_price': t['exit_price'],
                        'exit_time': ts_to_dt(exit_timestamp),
                        'exit_balance': t['exit_balance'],
                        'profit_loss': t['profit_loss'],
                        'trade_closed': bool(t['trade_closed'])
                    }
                    transactions.append(transaction)
                except Exception as e:
                    print(f"İşlem dönüştürme hatası: {str(e)}")
                    continue

            total_long = sum(1 for x in all_data if x['trade_type'] == 'LONG')
            total_short = sum(1 for x in all_data if x['trade_type'] == 'SHORT')
            long_success = sum(1 for x in all_data if x['trade_type'] == 'LONG' and x['profit_loss'] > 0)
            short_success = sum(1 for x in all_data if x['trade_type'] == 'SHORT' and x['profit_loss'] > 0)
            long_fail = total_long - long_success
            short_fail = total_short - short_success
            total_success = long_success + short_success
            total_fail = long_fail + short_fail
            total_count = total_long + total_short
            total_profit = sum(x['profit_loss'] for x in all_data if x['profit_loss'] is not None)
            total_loss = sum(x['profit_loss'] for x in all_data if x['profit_loss'] is not None and x['profit_loss'] < 0)
            max_profit = max([x['profit_loss'] for x in all_data if x['profit_loss'] is not None], default=0)
            min_profit = min([x['profit_loss'] for x in all_data if x['profit_loss'] is not None], default=0)
            stats = {
                'total': total_count,
                'long': total_long,
                'short': total_short,
                'long_success': long_success,
                'short_success': short_success,
                'long_fail': long_fail,
                'short_fail': short_fail,
                'long_success_pct': (long_success / total_long * 100) if total_long else 0,
                'short_success_pct': (short_success / total_short * 100) if total_short else 0,
                'total_success': total_success,
                'total_fail': total_fail,
                'total_success_pct': (total_success / total_count * 100) if total_count else 0,
                'total_profit': total_profit,
                'total_loss': total_loss,
                'max_profit': max_profit,
                'min_profit': min_profit,
                'total_trades': total_count,
                'total_long': total_long,
                'total_short': total_short,
                'long_success_rate': (long_success / total_long * 100) if total_long else 0,
                'short_success_rate': (short_success / total_short * 100) if total_short else 0,
                'success_rate': (total_success / total_count * 100) if total_count else 0,
                'successful_trades': total_success
            }

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

        pagination = Pagination(transactions, page, per_page, total)
        conn.close()

        return render_template('main/transaction_history.html',
                             symbol=symbol,
                             timeframe=timeframe,
                             transactions=pagination,
                             stats=stats,
                             filters={
                                 'start_date': start_date,
                                 'end_date': end_date,
                                 'trade_type': trade_type,
                                 'success': success
                             })

    except Exception as e:
        print(f"İşlem geçmişi yüklenirken hata: {str(e)}")
        traceback.print_exc()
        flash('İşlem geçmişi yüklenirken bir hata oluştu. Lütfen daha sonra tekrar deneyin.', 'error')
        return redirect(url_for('main.dashboard'))

@bp.route('/realtime_transaction_history')
@login_required
def realtime_transaction_history():
    # Sadece ilgili kullanıcıya göster
    user_email = current_user.email
    if user_email != 'aren_32@hotmail.com':
        flash('Bu sayfaya erişim izniniz yok.', 'danger')
        return redirect(url_for('main.dashboard'))

    # Filtre parametreleri
    page = request.args.get('page', 1, type=int)
    per_page = 10
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    trade_type = request.args.get('trade_type')
    success = request.args.get('success')

    conn = get_mysql_connection()
    if not conn:
        return render_template('main/realtime_transaction_history.html', 
                            error="Veritabanı bağlantısı kurulamadı.")
    cursor = conn.cursor()

    where_clauses = ["user_email = %s"]
    params = [user_email]
    if trade_type in ('LONG', 'SHORT'):
        where_clauses.append("trade_type = %s")
        params.append(trade_type)
    if success == '1':
        where_clauses.append("profit_loss > 0")
    elif success == '0':
        where_clauses.append("profit_loss <= 0")
    if start_date:
        where_clauses.append("entry_time >= %s")
        try:
            start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp()) * 1000
        except:
            start_ts = 0
        params.append(start_ts)
    if end_date:
        where_clauses.append("entry_time <= %s")
        try:
            end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp()) * 1000
        except:
            end_ts = 9999999999999
        params.append(end_ts)
    where_sql = " AND ".join(where_clauses)

    # Toplam işlem sayısı
    cursor.execute(f"SELECT COUNT(*) FROM realtime_transactions WHERE {where_sql}", params)
    total = cursor.fetchone()[0]
    offset = (page - 1) * per_page

    # İşlemleri getir
    cursor.execute(f"""
        SELECT trade_type, entry_price, entry_time, entry_balance,
               exit_price, exit_time, exit_balance, profit_loss, trade_closed
        FROM realtime_transactions
        WHERE {where_sql}
        ORDER BY entry_time DESC
        LIMIT %s OFFSET %s
    """, params + [per_page, offset])
    transactions_data = cursor.fetchall()

    # Tüm filtreli işlemleri istatistik için çek
    cursor.execute(f"SELECT trade_type, profit_loss, trade_closed FROM realtime_transactions WHERE {where_sql}", params)
    all_data = cursor.fetchall()

    # Verileri işle
    transactions = []
    for t in transactions_data:
        try:
            print(f"DEBUG: İşlem verisi (raw): {t}")
            # entry_time ve exit_time'ı işlerken bytes tipi kontrolü ekle
            entry_timestamp_raw = t[2]
            exit_timestamp_raw = t[5]

            entry_timestamp = None
            if entry_timestamp_raw is not None:
                if isinstance(entry_timestamp_raw, bytes):
                    if len(entry_timestamp_raw) == 8: # Genellikle 8 bayt unsigned long long
                        entry_timestamp = struct.unpack('<Q', entry_timestamp_raw)[0]
                        print(f"DEBUG: entry_timestamp (bytes to int): {entry_timestamp}")
                    else:
                        print(f"Uyarı: Beklenmeyen bytes uzunluğu için entry_timestamp_raw: {entry_timestamp_raw}. Atlanıyor.")
                else:
                    entry_timestamp = int(entry_timestamp_raw)
                    print(f"DEBUG: entry_timestamp (int directly): {entry_timestamp}")

            exit_timestamp = None
            if exit_timestamp_raw is not None:
                if isinstance(exit_timestamp_raw, bytes):
                    if len(exit_timestamp_raw) == 8:
                        exit_timestamp = struct.unpack('<Q', exit_timestamp_raw)[0]
                        print(f"DEBUG: exit_timestamp (bytes to int): {exit_timestamp}")
                    else:
                        print(f"Uyarı: Beklenmeyen bytes uzunluğu için exit_timestamp_raw: {exit_timestamp_raw}. Atlanıyor.")
                else:
                    exit_timestamp = int(exit_timestamp_raw)
                    print(f"DEBUG: exit_timestamp (int directly): {exit_timestamp}")

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
                'profit_loss': t[7] if t[7] is not None else 0,
                'trade_closed': bool(t[8])
            }
            transactions.append(transaction)
        except Exception as e:
            print(f"İşlem dönüştürme hatası: {str(e)}")
            continue

    # İstatistikleri hesapla
    total_long = sum(1 for x in all_data if x[0] == 'LONG')
    total_short = sum(1 for x in all_data if x[0] == 'SHORT')
    long_success = sum(1 for x in all_data if x[0] == 'LONG' and x[1] is not None and x[1] > 0)
    short_success = sum(1 for x in all_data if x[0] == 'SHORT' and x[1] is not None and x[1] > 0)
    
    total_trades = len(all_data)
    successful_trades = sum(1 for x in all_data if x[1] is not None and x[1] > 0)
    total_profit = sum(x[1] for x in all_data if x[1] is not None)
    
    stats = {
        'total_trades': total_trades,
        'successful_trades': successful_trades,
        'success_rate': (successful_trades / total_trades * 100) if total_trades > 0 else 0,
        'total_profit': total_profit,
        'total_long': total_long,
        'total_short': total_short,
        'long_success': long_success,
        'short_success': short_success,
        'long_success_rate': (long_success / total_long * 100) if total_long > 0 else 0,
        'short_success_rate': (short_success / total_short * 100) if total_short > 0 else 0
    }

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
            self.prev_num = page - 1 if self.has_prev else None
            self.next_num = page + 1 if self.has_next else None

        def iter_pages(self, left_edge=2, left_current=2, right_current=3, right_edge=2):
            last = 0
            for num in range(1, self.pages + 1):
                if (num <= left_edge or 
                    (num > self.page - left_current - 1 and 
                     num < self.page + right_current) or 
                    num > self.pages - right_edge):
                    if last + 1 != num:
                        yield None
                    yield num
                    last = num

    pagination = Pagination(transactions, page, per_page, total)
    conn.close()

    return render_template('main/realtime_transaction_history.html',
                        transactions=transactions,
                        pagination=pagination,
                        stats=stats,
                        filters={
                            'start_date': start_date,
                            'end_date': end_date,
                            'trade_type': trade_type,
                            'success': success
                        }) 