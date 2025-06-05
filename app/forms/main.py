from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, FloatField, SubmitField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Optional, NumberRange, Length
from config import Config

class SettingsForm(FlaskForm):
    # Trading ayarları
    symbol = SelectField('Kripto Para', validators=[DataRequired()],
                        choices=[(s, s.replace('/USDT', '')) for s in Config.DEFAULT_SYMBOLS])
    timeframe = SelectField('Zaman Dilimi', validators=[DataRequired()],
                          choices=[(tf, tf) for tf in Config.DEFAULT_TIMEFRAMES])
    leverage = FloatField('Kaldıraç', validators=[
        DataRequired(),
        NumberRange(min=1, max=Config.MAX_LEVERAGE, message='Kaldıraç 1 ile {} arasında olmalıdır.'.format(Config.MAX_LEVERAGE))
    ], default=Config.DEFAULT_LEVERAGE)
    stop_loss = FloatField('Stop Kaybı (%)', validators=[
        DataRequired(),
        NumberRange(min=Config.MIN_STOP_LOSS, max=Config.MAX_STOP_LOSS, 
                   message='Stop kaybı {} ile {} arasında olmalıdır.'.format(Config.MIN_STOP_LOSS, Config.MAX_STOP_LOSS))
    ], default=Config.DEFAULT_STOP_LOSS)
    take_profit = FloatField('Kâr Al (%)', validators=[
        DataRequired(),
        NumberRange(min=Config.MIN_TAKE_PROFIT, max=Config.MAX_TAKE_PROFIT, 
                   message='Kâr al {} ile {} arasında olmalıdır.'.format(Config.MIN_TAKE_PROFIT, Config.MAX_TAKE_PROFIT))
    ], default=Config.DEFAULT_TAKE_PROFIT)
    atr_period = FloatField('ATR Periyodu', validators=[
        DataRequired(),
        NumberRange(min=1, max=100, message='ATR periyodu 1 ile 100 arasında olmalıdır.')
    ], default=14)
    atr_multiplier = FloatField('ATR Çarpanı', validators=[
        DataRequired(),
        NumberRange(min=0.1, max=10, message='ATR çarpanı 0.1 ile 10 arasında olmalıdır.')
    ], default=2.0)
    # API ayarları
    api_key = StringField('Binance API Key', validators=[Optional()])
    api_secret = StringField('Binance API Secret', validators=[Optional()])
    balance = FloatField('İşlem Bakiyesi (USDT)', validators=[Optional(), NumberRange(min=0)])
    submit = SubmitField('Ayarları Kaydet') 