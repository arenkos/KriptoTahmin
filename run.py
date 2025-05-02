import asyncio
from config import Config
from app.utils.notifications.telegram_bot import TelegramBot
from app import create_app
import sys
import threading

app = create_app()

def run_bot():
    # Telegram bot'u başlat
    try:
        bot = TelegramBot(Config.TELEGRAM_BOT_TOKEN)
        bot.run_polling()  # Botu başlatmak için run_polling kullanıyoruz
    except Exception as e:
        print(f"Telegram bot çalıştırılırken hata oluştu: {e}")
        print("Bot özelliği devre dışı bırakıldı, web uygulama normal çalışmaya devam edecek.")

if __name__ == '__main__':
    port = 5001
    if len(sys.argv) > 2 and sys.argv[1] == '-port':
        try:
            port = int(sys.argv[2])
        except ValueError:
            print("Geçersiz port numarası")
            sys.exit(1)

    # Telegram botunu çalıştırmak istemiyorsanız aşağıdaki satırları yorum satırı yapın
    enable_bot = False  # Telegram botunu çalıştırmak için True, kapatmak için False
    if enable_bot:
        bot_thread = threading.Thread(target=run_bot)
        bot_thread.daemon = True
        bot_thread.start()
    else:
        print("Telegram bot devre dışı bırakıldı. Sadece web uygulama çalışıyor.")

    # Web server'ı çalıştır
    app.run(debug=True, port=port)