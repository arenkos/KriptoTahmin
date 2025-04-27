from app import create_app
# from app.utils.notifications.telegram_bot import TelegramBot
from config import Config
import sys

app = create_app()

if __name__ == '__main__':
    # Port parametresini kontrol et
    port = 5001
    if len(sys.argv) > 2 and sys.argv[1] == 'port':
        try:
            port = int(sys.argv[2])
        except ValueError:
            print("Geçersiz port numarası")
            sys.exit(1)
    
    # Telegram bot'u geçici olarak devre dışı bırakıyoruz
    # bot = TelegramBot(Config.TELEGRAM_BOT_TOKEN)
    # bot.start()
    app.run(debug=True, port=port) 