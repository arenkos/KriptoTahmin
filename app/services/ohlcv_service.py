from app.extensions import db
from app.models.ohlcv import OHLCV
from datetime import datetime, timedelta
import pandas as pd
import ccxt

class OHLCVService:
    def __init__(self, exchange):
        self.exchange = exchange

    def get_stored_data(self, symbol, timeframe, start_date, end_date):
        """Veritabanından belirli bir tarih aralığındaki verileri getirir."""
        return OHLCV.query.filter(
            OHLCV.symbol == symbol,
            OHLCV.timeframe == timeframe,
            OHLCV.timestamp.between(start_date, end_date)
        ).order_by(OHLCV.timestamp.asc()).all()

    def get_missing_ranges(self, symbol, timeframe, start_date, end_date):
        """Eksik veri aralıklarını bulur."""
        stored_data = self.get_stored_data(symbol, timeframe, start_date, end_date)
        
        if not stored_data:
            return [(start_date, end_date)]
            
        missing_ranges = []
        current_date = start_date
        
        for data in stored_data:
            if current_date < data.timestamp:
                missing_ranges.append((current_date, data.timestamp))
            current_date = data.timestamp + self.get_timeframe_delta(timeframe)
        
        if current_date < end_date:
            missing_ranges.append((current_date, end_date))
            
        return missing_ranges

    def get_timeframe_delta(self, timeframe):
        """Zaman dilimi için timedelta hesaplar."""
        unit = timeframe[-1]
        value = int(timeframe[:-1])
        
        if unit == 'm':
            return timedelta(minutes=value)
        elif unit == 'h':
            return timedelta(hours=value)
        elif unit == 'd':
            return timedelta(days=value)
        elif unit == 'w':
            return timedelta(weeks=value)
        return timedelta(minutes=1)

    def fetch_and_store_data(self, symbol, timeframe, start_date, end_date):
        """Eksik verileri çeker ve veritabanına kaydeder."""
        missing_ranges = self.get_missing_ranges(symbol, timeframe, start_date, end_date)
        
        for start, end in missing_ranges:
            # CCXT için timestamp'i milisaniyeye çevir
            since = int(start.timestamp() * 1000)
            
            try:
                # Veriyi çek
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, since=since)

                # Verileri kaydet
                for candle in ohlcv:
                    timestamp = datetime.fromtimestamp(candle[0] / 1000)
                    if timestamp > end:
                        break
                        
                    data = OHLCV(
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=timestamp,
                        open=candle[1],
                        high=candle[2],
                        low=candle[3],
                        close=candle[4],
                        volume=candle[5]
                    )
                    db.session.add(data)
                
                db.session.commit()
                
            except Exception as e:
                db.session.rollback()
                print(f"Error fetching data: {e}")
                continue

    def get_data_as_dataframe(self, symbol, timeframe, start_date, end_date):
        """Verileri pandas DataFrame formatında getirir."""
        # Önce eksik verileri çek ve kaydet
        self.fetch_and_store_data(symbol, timeframe, start_date, end_date)
        
        # Tüm verileri getir
        data = self.get_stored_data(symbol, timeframe, start_date, end_date)
        
        # DataFrame oluştur
        df = pd.DataFrame([{
            'timestamp': d.timestamp,
            'open': d.open,
            'high': d.high,
            'low': d.low,
            'close': d.close,
            'volume': d.volume
        } for d in data])
        
        return df

    def clean_old_data(self, days=365):
        """Eski verileri temizler."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        OHLCV.query.filter(OHLCV.timestamp < cutoff_date).delete()
        db.session.commit() 