from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required
from app.utils.indicators.analysis import CryptoAnalyzer

bp = Blueprint('trading', __name__)

@bp.route('/trading')
@login_required
def trading_page():
    return render_template('trading.html')

@bp.route('/api/analyze', methods=['POST'])
@login_required
def analyze():
    data = request.get_json()
    symbol = data.get('symbol', 'BTC/USDT')
    timeframe = data.get('timeframe', '1h')
    
    analyzer = CryptoAnalyzer(symbol)
    analysis = analyzer.analyze(timeframe)
    
    return jsonify(analysis) 