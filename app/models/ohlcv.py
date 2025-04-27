from app.extensions import db
from datetime import datetime

class OHLCV(db.Model):
    __tablename__ = 'ohlcv_data'
    
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False)
    timeframe = db.Column(db.String(10), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    open = db.Column(db.Float, nullable=False)
    high = db.Column(db.Float, nullable=False)
    low = db.Column(db.Float, nullable=False)
    close = db.Column(db.Float, nullable=False)
    volume = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('symbol', 'timeframe', 'timestamp'),
        db.Index('idx_symbol_timeframe_timestamp', 'symbol', 'timeframe', 'timestamp')
    )

    def __repr__(self):
        return f'<OHLCV {self.symbol} {self.timeframe} {self.timestamp}>' 