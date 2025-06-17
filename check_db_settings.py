from app import create_app
from app.models.database import TradingSettings
from app.extensions import db

app = create_app()

with app.app_context():
    settings = TradingSettings.query.all()
    print('Mevcut TradingSettings kayıtları:')
    if settings:
        for s in settings:
            print(f'ID: {s.id}, Symbol: {s.symbol}, Timeframe: {s.timeframe}, Is Active: {s.is_active}, User ID: {s.user_id}, Balance: {s.balance}')
    else:
        print('Hiç TradingSettings kaydı bulunamadı.') 