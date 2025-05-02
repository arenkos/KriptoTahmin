from app.extensions import db
from datetime import datetime

class AnalysisResult(db.Model):
    __tablename__ = 'analysis_results'
    
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    leverage = db.Column(db.Integer, nullable=False)
    stop_percentage = db.Column(db.Float, nullable=False)
    success_rate = db.Column(db.Float, nullable=False)
    profit_rate = db.Column(db.Float, nullable=False)
    successful_trades = db.Column(db.Integer, nullable=False)
    unsuccessful_trades = db.Column(db.Integer, nullable=False)
    final_balance = db.Column(db.Float, nullable=False)
    atr_period = db.Column(db.Integer, nullable=False)
    atr_multiplier = db.Column(db.Float, nullable=False)
    analysis_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    total_trades = db.Column(db.Integer, nullable=False)
    win_rate = db.Column(db.Float, nullable=False)
    average_win = db.Column(db.Float, nullable=False)
    average_loss = db.Column(db.Float, nullable=False)
    max_drawdown = db.Column(db.Float, nullable=False)
    risk_reward_ratio = db.Column(db.Float, nullable=False)
    sharpe_ratio = db.Column(db.Float, nullable=False)
    
    __table_args__ = (
        db.UniqueConstraint('symbol', 'timeframe', 'is_active'),
    )

    def __repr__(self):
        return f'<AnalysisResult {self.symbol} {self.timeframe}>' 