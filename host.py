import asyncio
from config import Config
# from app.utils.notifications.telegram_bot import TelegramBot
from app import create_app
import sys
import threading
import argparse

app = create_app()


def run_bot():
    # Telegram bot'u başlat
    try:
        print("Telegram bot kullanımda değil.")
        # bot = TelegramBot(Config.TELEGRAM_BOT_TOKEN)
        # bot.run_polling()  # Botu başlatmak için run_polling kullanıyoruz
    except Exception as e:
        print(f"Telegram bot çalıştırılırken hata oluştu: {e}")
        print("Bot özelliği devre dışı bırakıldı, web uygulama normal çalışmaya devam edecek.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--port', help='port', required=False, default='5001')
    parser.add_argument('--host', help='host', required=False, default='127.0.0.1')
    args = parser.parse_args()

    port = None
    try:
        port = int(args.port)
    except Exception as e:
        raise Exception(f'Port degeri gecersiz: {args.port}')

    host = args.host

    # Telegram botunu çalıştırmak istemiyorsanız aşağıdaki satırları yorum satırı yapın
    enable_bot = False  # Telegram botunu çalıştırmak için True, kapatmak için False
    if enable_bot:
        bot_thread = threading.Thread(target=run_bot)
        bot_thread.daemon = True
        bot_thread.start()
    else:
        print("Telegram bot devre dışı bırakıldı. Sadece web uygulama çalışıyor.")

    # Web server'ı çalıştır
    app.run(debug=True, port=port, host=host)