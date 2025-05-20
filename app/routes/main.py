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

    if request.method == 'POST' and form.validate_on_submit():
        # API bilgilerini kaydet
        current_user.api_key = form.api_key.data
        current_user.api_secret = form.api_secret.data
        current_user.balance = form.balance.data
        db.session.commit()
        # Trading ayarlarını kaydet
        existing_settings = TradingSettings.query.filter_by(
            user_id=current_user.id,
            symbol=form.symbol.data,
            timeframe=form.timeframe.data
        ).first()
        if existing_settings:
            existing_settings.leverage = form.leverage.data
            existing_settings.stop_loss = form.stop_loss.data
            existing_settings.take_profit = form.take_profit.data
            existing_settings.updated_at = datetime.utcnow()
        else:
            new_settings = TradingSettings(
                user_id=current_user.id,
                symbol=form.symbol.data,
                timeframe=form.timeframe.data,
                leverage=form.leverage.data,
                stop_loss=form.stop_loss.data,
                take_profit=form.take_profit.data
            )
            db.session.add(new_settings)
        db.session.commit()
        flash('Ayarlar başarıyla kaydedildi', 'success')
        return redirect(url_for('main.settings'))

    # GET ise mevcut ayarları forma doldur
    if request.method == 'GET':
        form.api_key.data = current_user.api_key
        form.api_secret.data = current_user.api_secret
        form.balance.data = current_user.balance
        last_settings = TradingSettings.query.filter_by(
            user_id=current_user.id
        ).order_by(TradingSettings.updated_at.desc()).first()
        if last_settings:
            form.symbol.data = last_settings.symbol
            form.timeframe.data = last_settings.timeframe
            form.leverage.data = last_settings.leverage
            form.stop_loss.data = last_settings.stop_loss
            form.take_profit.data = last_settings.take_profit
    return render_template('main/settings.html', form=form)

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
    """Trading ayarlarını seçilen parametre sonuçlarına göre günceller"""
    symbol = request.args.get('symbol')
    timeframe = request.args.get('timeframe')
    leverage = float(request.args.get('leverage', 1))
    stop_percentage = float(request.args.get('stop_percentage', 1))
    kar_al_percentage = float(request.args.get('kar_al_percentage', 2))
    
    if not all([symbol, timeframe, leverage, stop_percentage, kar_al_percentage]):
        flash('Gerekli parametreler eksik', 'error')
        return redirect(url_for('main.param_analysis'))
    
    # Önce tüm ayarları pasif yap
    user_settings = TradingSettings.query.filter_by(user_id=current_user.id).all()
    for setting in user_settings:
        setting.is_active = False
    
    # Mevcut ayarları kontrol et
    settings = TradingSettings.query.filter_by(
        user_id=current_user.id,
        symbol=symbol,
        timeframe=timeframe
    ).first()
    
    # Eğer ayar varsa güncelle, yoksa yeni oluştur
    if settings:
        settings.leverage = leverage
        settings.stop_loss = stop_percentage
        settings.take_profit = kar_al_percentage
        settings.is_active = True  # Bu ayarı aktif olarak işaretle
    else:
        settings = TradingSettings(
            user_id=current_user.id,
            symbol=symbol,
            timeframe=timeframe,
            leverage=leverage,
            stop_loss=stop_percentage,
            take_profit=kar_al_percentage,
            is_active=True  # Bu ayarı aktif olarak işaretle
        )
        db.session.add(settings)
    
    db.session.commit()
    
    # Trade bot'u hemen çalıştır
    try:
        import subprocess
        import sys
        subprocess.Popen([sys.executable, "trade.py"])
        flash(f'{symbol} {timeframe} için trading ayarları uygulandı ve trade bot yeniden başlatıldı', 'success')
    except Exception as e:
        current_app.logger.error(f"Trade bot başlatılırken hata: {e}")
        flash(f'{symbol} {timeframe} için trading ayarları uygulandı fakat trade bot başlatılamadı', 'warning')
    
    # Ayarlar sayfasında ilgili form alanlarını doldurmak için session değişkenlerini ayarla
    session['selected_symbol'] = symbol
    session['selected_timeframe'] = timeframe
    session['selected_leverage'] = leverage
    session['selected_stop_loss'] = stop_percentage
    session['selected_take_profit'] = kar_al_percentage
    
    return redirect(url_for('main.settings')) 