import ccxt
from datetime import datetime
from app.models.database import Transaction
from config import Config

class BinanceAPI:
    def __init__(self, api_key, api_secret):
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'options': {
                'defaultType': 'future'
            },
            'enableRateLimit': True
        })
        
    def get_balance(self):
        """Get account balance"""
        try:
            balance = self.exchange.fetch_balance()
            return {
                'total': balance['total'],
                'free': balance['free'],
                'used': balance['used']
            }
        except Exception as e:
            return {'error': str(e)}
            
    def get_positions(self):
        """Get open positions"""
        try:
            positions = self.exchange.fetch_positions()
            return [{
                'symbol': pos['symbol'],
                'size': pos['contracts'],
                'entry_price': pos['entryPrice'],
                'mark_price': pos['markPrice'],
                'unrealized_pnl': pos['unrealizedPnl'],
                'leverage': pos['leverage']
            } for pos in positions if float(pos['contracts']) > 0]
        except Exception as e:
            return {'error': str(e)}
            
    def place_order(self, symbol, order_type, side, amount, leverage, stop_loss=None, take_profit=None):
        """Place a new order"""
        try:
            # Set leverage
            self.exchange.set_leverage(leverage, symbol)
            
            # Place main order
            order = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount
            )
            
            # Place stop loss if specified
            if stop_loss:
                stop_price = float(order['price']) * (1 - stop_loss/100) if side == 'buy' else float(order['price']) * (1 + stop_loss/100)
                self.exchange.create_order(
                    symbol=symbol,
                    type='stop',
                    side='sell' if side == 'buy' else 'buy',
                    amount=amount,
                    price=stop_price
                )
                
            # Place take profit if specified
            if take_profit:
                take_profit_price = float(order['price']) * (1 + take_profit/100) if side == 'buy' else float(order['price']) * (1 - take_profit/100)
                self.exchange.create_order(
                    symbol=symbol,
                    type='limit',
                    side='sell' if side == 'buy' else 'buy',
                    amount=amount,
                    price=take_profit_price
                )
                
            return order
        except Exception as e:
            return {'error': str(e)}
            
    def close_position(self, symbol, side, amount):
        """Close an open position"""
        try:
            order = self.exchange.create_order(
                symbol=symbol,
                type='market',
                side='sell' if side == 'buy' else 'buy',
                amount=amount
            )
            return order
        except Exception as e:
            return {'error': str(e)}
            
    def get_ohlcv(self, symbol, timeframe, since=None, limit=None):
        """Get OHLCV data"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=since,
                limit=limit
            )
            return ohlcv
        except Exception as e:
            return {'error': str(e)}
            
    def sync_trades(self, user_id):
        """Sync trades with database"""
        try:
            # Get open positions
            positions = self.get_positions()
            
            # Update or create transactions
            for pos in positions:
                transaction = Transaction.query.filter_by(
                    user_id=user_id,
                    symbol=pos['symbol'],
                    status='open'
                ).first()
                
                if transaction:
                    # Update existing transaction
                    transaction.amount = pos['size']
                    transaction.profit_loss = pos['unrealized_pnl']
                else:
                    # Create new transaction
                    transaction = Transaction(
                        user_id=user_id,
                        symbol=pos['symbol'],
                        type='buy' if float(pos['size']) > 0 else 'sell',
                        price=pos['entry_price'],
                        amount=abs(float(pos['size'])),
                        leverage=pos['leverage'],
                        status='open',
                        created_at=datetime.now()
                    )
                    db.session.add(transaction)
                    
            db.session.commit()
            return True
        except Exception as e:
            return {'error': str(e)} 