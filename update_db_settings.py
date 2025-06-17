from app import create_app
from app.models.database import TradingSettings
from app.extensions import db

app = create_app()

with app.app_context():
    # BTC/USDT ve 1m timeframe için ayarı bul
    settings_to_update = TradingSettings.query.filter_by(symbol='BTC/USDT', timeframe='1m').first()
    
    if settings_to_update:
        settings_to_update.is_active = True
        db.session.commit()
        print(f"BTC/USDT 1m TradingSettings kaydı güncellendi: Is Active -> {settings_to_update.is_active}")
    else:
        print("BTC/USDT 1m TradingSettings kaydı bulunamadı.")

    # Diğer tüm ayarları pasif yap
    TradingSettings.query.filter(TradingSettings.symbol != 'BTC/USDT').update({'is_active': False})
    db.session.commit()
    print("Diğer TradingSettings kayıtları pasif hale getirildi.") 