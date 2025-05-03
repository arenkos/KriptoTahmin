from pytz import timezone
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from app.models.database import db, User
from config import Config

class TelegramBot:
    def __init__(self, token):
        # python-telegram-bot 13.7 sürümüne göre yapılandırma
        self.updater = Updater(token=token, use_context=True)
        self.dispatcher = self.updater.dispatcher

        # Komutlar ekliyoruz
        self.dispatcher.add_handler(CommandHandler("start", self.start))
        self.dispatcher.add_handler(CommandHandler("help", self.help))
        self.dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, self.handle_message))

        # Bot değişkeni
        self.bot = self.updater.bot
        
        # ParseMode test
        print("TelegramBot sınıfı içinde ParseMode:", ParseMode)
        print("ParseMode.MARKDOWN:", ParseMode.MARKDOWN)
        print("ParseMode.HTML:", ParseMode.HTML)

    def start(self, update: Update, context: CallbackContext):
        """Send a message when the command /start is issued."""
        user = update.effective_user
        update.message.reply_text(
            f'Merhaba {user.first_name}! Kripto Tahmin Botuna hoş geldiniz.\n'
            'Kullanmak için önce web sitesinden kayıt olmanız gerekiyor.'
        )

    def help(self, update: Update, context: CallbackContext):
        """Send a message when the command /help is issued."""
        update.message.reply_text(
            'Kullanılabilir komutlar:\n'
            '/start - Botu başlat\n'
            '/help - Yardım mesajını göster'
        )
        
    def status(self, update: Update, context: CallbackContext):
        """Send a message when the command /status is issued."""
        chat_id = update.effective_chat.id
        user = User.query.filter_by(telegram_chat_id=str(chat_id)).first()
        
        if not user:
            update.message.reply_text(
                'Önce web sitesinden kayıt olup Telegram ID\'nizi eklemeniz gerekiyor.'
            )
            return
            
        # Get user's active trades
        active_trades = user.transactions.filter_by(status='open').all()
        
        if not active_trades:
            update.message.reply_text('Şu anda aktif işleminiz bulunmuyor.')
            return
            
        message = 'Aktif İşlemleriniz:\n\n'
        for trade in active_trades:
            message += (
                f'Sembol: {trade.symbol}\n'
                f'Tip: {trade.type}\n'
                f'Giriş Fiyatı: {trade.price}\n'
                f'Miktar: {trade.amount}\n'
                f'Kaldıraç: {trade.leverage}x\n'
                f'Giriş Zamanı: {trade.created_at}\n\n'
            )
            
        update.message.reply_text(message)
        
    def handle_message(self, update: Update, context: CallbackContext):
        """Handle the user message."""
        update.message.reply_text(
            'Bu bot sadece komutları destekler. Kullanılabilir komutlar için /help yazın.'
        )
        
    def send_trade_signal(self, user_id: int, signal: dict):
        """Send trade signal to user"""
        user = User.query.get(user_id)
        if not user or not user.telegram_chat_id:
            return
            
        message = (
            f'Yeni İşlem Sinyali!\n\n'
            f'Sembol: {signal["symbol"]}\n'
            f'Tip: {signal["type"]}\n'
            f'Giriş Fiyatı: {signal["price"]}\n'
            f'Stop Loss: {signal["stop_loss"]}%\n'
            f'Take Profit: {signal["take_profit"]}%\n'
            f'Kaldıraç: {signal["leverage"]}x\n'
        )
        
        self.bot.send_message(
            chat_id=user.telegram_chat_id,
            text=message,
            parse_mode=ParseMode.MARKDOWN  # ParseMode kullanımı örneği
        )
        
    def send_trade_update(self, user_id: int, update_info: dict):
        """Send trade update to user"""
        user = User.query.get(user_id)
        if not user or not user.telegram_chat_id:
            return
            
        message = (
            f'İşlem Güncellemesi!\n\n'
            f'Sembol: {update_info["symbol"]}\n'
            f'Tip: {update_info["type"]}\n'
            f'Durum: {update_info["status"]}\n'
            f'Kâr/Zarar: {update_info["profit_loss"]}%\n'
        )
        
        self.bot.send_message(
            chat_id=user.telegram_chat_id,
            text=message,
            parse_mode=ParseMode.MARKDOWN  # ParseMode kullanımı örneği
        )
    
    # Test metodu - sadece ParseMode'un çalıştığını kontrol etmek için
    def test_parsemode(self):
        """ParseMode testini yapar"""
        print("TelegramBot.test_parsemode() çalıştırılıyor")
        print(f"ParseMode: {ParseMode}")
        print(f"ParseMode.MARKDOWN: {ParseMode.MARKDOWN}")
        print(f"ParseMode.HTML: {ParseMode.HTML}")
        return True
        
    def run_polling(self):
        """Bot'u çalıştır"""
        self.updater.start_polling()