from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from app.models.database import db, User
from config import Config

class TelegramBot:
    def __init__(self, token):
        self.application = Application.builder().token(token).build()
        
        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a message when the command /start is issued."""
        user = update.effective_user
        await update.message.reply_text(
            f'Merhaba {user.first_name}! Kripto Tahmin Botuna hoş geldiniz.\n'
            'Kullanmak için önce web sitesinden kayıt olmanız gerekiyor.'
        )
        
    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a message when the command /help is issued."""
        await update.message.reply_text(
            'Kullanılabilir komutlar:\n'
            '/start - Botu başlat\n'
            '/help - Yardım mesajını göster\n'
            '/status - Mevcut işlemlerinizi göster\n'
            '\nWeb sitesi: [Siteniz]'
        )
        
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a message when the command /status is issued."""
        chat_id = update.effective_chat.id
        user = User.query.filter_by(telegram_chat_id=str(chat_id)).first()
        
        if not user:
            await update.message.reply_text(
                'Önce web sitesinden kayıt olup Telegram ID\'nizi eklemeniz gerekiyor.'
            )
            return
            
        # Get user's active trades
        active_trades = user.transactions.filter_by(status='open').all()
        
        if not active_trades:
            await update.message.reply_text('Şu anda aktif işleminiz bulunmuyor.')
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
            
        await update.message.reply_text(message)
        
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the user message."""
        await update.message.reply_text(
            'Bu bot sadece komutları destekler. Kullanılabilir komutlar için /help yazın.'
        )
        
    async def send_trade_signal(self, user_id: int, signal: dict):
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
        
        await self.application.bot.send_message(
            chat_id=user.telegram_chat_id,
            text=message
        )
        
    async def send_trade_update(self, user_id: int, update_info: dict):
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
        
        await self.application.bot.send_message(
            chat_id=user.telegram_chat_id,
            text=message
        )
        
    def run(self):
        """Start the bot"""
        self.application.run_polling() 