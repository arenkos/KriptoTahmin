from flask import Blueprint, render_template
from app.services.analysis_service import AnalysisService

analysis_bp = Blueprint('analysis', __name__)

@analysis_bp.route('/analysis')
def analysis():
    # Periyotları sıralı şekilde tanımlayalım
    timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]
    
    # Her periyot için sonuçları alalım
    results = {}
    for timeframe in timeframes:
        results[timeframe] = AnalysisService.get_results_by_timeframe(timeframe)
    
    return render_template('analysis/index.html', results=results, timeframes=timeframes) 