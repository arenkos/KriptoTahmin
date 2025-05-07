# Kripto Tahmin Sistemi

Bu proje, kripto para piyasalarında otomatik alım-satım yapabilen ve teknik analiz gerçekleştiren bir sistemdir.

## Docker Hızlı Başlangıç

```bash
docker build -t kripto_app:latest .
docker run -it --network=host -v /mnt/dbvolume/crypto_data.db:/home/user/KriptoTahmin/crypto_data.db -v /mnt/dbvolume/app.db:/home/user/KriptoTahmin/ain/app.db kripto_app:latest python3 host.py --host 0.0.0.0
```

## Özellikler

- Çoklu kripto para desteği
- Farklı zaman dilimlerinde analiz (1m, 15m, 1h, 4h, 1d)
- Otomatik kaldıraç ve risk yönetimi
- Telegram bot entegrasyonu
- Binance API entegrasyonu
- Web arayüzü
- Kullanıcı yönetimi
- Gerçek zamanlı analiz ve sinyal üretimi

## Kurulum

1. Gerekli paketleri yükleyin:
```bash
pip install -r requirements.txt
```

2. `.env` dosyasını oluşturun:
```bash
cp .env.example .env
```

3. `.env` dosyasını düzenleyin:
```
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///app.db
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
BINANCE_API_KEY=your-binance-api-key
BINANCE_API_SECRET=your-binance-api-secret
```

4. Veritabanını oluşturun:
```bash
flask db init
flask db migrate
flask db upgrade
```

5. Uygulamayı başlatın:
```bash
python run.py
```

## Kullanım

1. Web arayüzüne giriş yapın
2. Binance API bilgilerinizi girin
3. Trading ayarlarınızı yapılandırın
4. Telegram botunu başlatın
5. Trading'i başlatın

## Güvenlik

- API anahtarlarınızı güvenli bir şekilde saklayın
- Şifrelerinizi güçlü seçin
- İki faktörlü kimlik doğrulama kullanın

## Lisans

Bu proje Doğuş Üniversitesi Bitirme Projesi kapsamında yapılmıştır.
