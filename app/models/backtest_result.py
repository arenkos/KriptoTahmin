from datetime import datetime
from app.extensions import db

class BacktestResult(db.Model):
    __tablename__ = 'backtest_results'
    
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    leverage = db.Column(db.Float, nullable=False)
    stop_percentage = db.Column(db.Float, nullable=False)
    atr_period = db.Column(db.Integer, nullable=False)
    atr_multiplier = db.Column(db.Float, nullable=False)
    success_rate = db.Column(db.Float, nullable=False)
    profit_rate = db.Column(db.Float, nullable=False)
    successful_trades = db.Column(db.Integer, nullable=False)
    unsuccessful_trades = db.Column(db.Integer, nullable=False)
    final_balance = db.Column(db.Float, nullable=False)
    win_rate = db.Column(db.Float, nullable=True)
    average_win = db.Column(db.Float, nullable=True)
    average_loss = db.Column(db.Float, nullable=True)
    max_drawdown = db.Column(db.Float, nullable=True)
    risk_reward_ratio = db.Column(db.Float, nullable=True)
    sharpe_ratio = db.Column(db.Float, nullable=True)
    total_trades = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # İndeksler
    __table_args__ = (
        db.UniqueConstraint('symbol', 'timeframe', name='uix_backtest_results_symbol_timeframe'),
        db.Index('idx_backtest_results_symbol', 'symbol'),
        db.Index('idx_backtest_results_timeframe', 'timeframe'),
    )
    
    def __repr__(self):
        return f"<BacktestResult {self.symbol}_{self.timeframe}>"
        
    def to_dict(self):
        return {
            'id': self.id,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'leverage': self.leverage,
            'stop_percentage': self.stop_percentage,
            'atr_period': self.atr_period,
            'atr_multiplier': self.atr_multiplier,
            'success_rate': self.success_rate,
            'profit_rate': self.profit_rate,
            'successful_trades': self.successful_trades,
            'unsuccessful_trades': self.unsuccessful_trades,
            'final_balance': self.final_balance,
            'win_rate': self.win_rate,
            'average_win': self.average_win,
            'average_loss': self.average_loss,
            'max_drawdown': self.max_drawdown,
            'risk_reward_ratio': self.risk_reward_ratio,
            'sharpe_ratio': self.sharpe_ratio,
            'total_trades': self.total_trades,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        } 