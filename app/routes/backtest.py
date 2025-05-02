from flask import Blueprint, render_template, request, jsonify
from app.services.backtest_service import BacktestService
import json

backtest_bp = Blueprint('backtest', __name__, url_prefix='/backtest')

@backtest_bp.route('/')
def index():
    """Backtest sonuçlarını görüntülemek için ana sayfa"""
    return render_template('backtest/index.html')

@backtest_bp.route('/results')
def get_results():
    """Tüm backtest sonuçlarını döndürür"""
    symbol = request.args.get('symbol', None)
    results = BacktestService.get_all_results(symbol)
    return jsonify(results)

@backtest_bp.route('/result/<symbol>/<timeframe>')
def get_result(symbol, timeframe):
    """Belirli bir symbol ve timeframe için backtest sonucunu döndürür"""
    result = BacktestService.get_result(symbol, timeframe)
    if result:
        return jsonify(result)
    return jsonify({"error": "Result not found"}), 404

@backtest_bp.route('/run', methods=['POST'])
def run_backtest():
    """Yeni bir backtest çalıştırır"""
    from main_strategy import analyze_symbol
    import ccxt
    
    data = request.json
    symbol = data.get('symbol', 'BTC/USDT')
    timeframe = data.get('timeframe', '1h')
    
    # Sadece yetkili kullanıcılar için bir kontrol eklenebilir
    
    # Exchange oluştur
    exchange = ccxt.binance({
        "apiKey": 'G2dI1suDiH3bCKo1lpx1Ho4cdTjmWh9eQEUSajcshC1rcQ0T1yATZnKukHiqo6IN',
        "secret": 'ow4J1QLRTXhzuhtBcFNOUSPq2uRYhrkqHaLri0zdAiMhoDCfJgEfXz0mSwvgpnPx',
        'options': {
            'defaultType': 'future'
        },
        'enableRateLimit': True
    })
    
    try:
        analysis_result = analyze_symbol(symbol, timeframe, exchange)
        
        if analysis_result:
            symbol_short = symbol.split('/')[0]
            BacktestService.save_result(
                symbol_short, 
                timeframe, 
                analysis_result['result']
            )
            return jsonify({"success": True, "result": analysis_result['result']})
        else:
            return jsonify({"success": False, "error": "Analysis failed"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500 