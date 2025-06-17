import asyncio
import websockets
import json
import sqlite3
import threading
import time
from datetime import datetime
from typing import Optional, Callable
import logging
import ssl

# Logging konfigürasyonu
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BinanceWebSocketClient:
    def __init__(self, db_path: str = 'crypto_data.db'):
        self.db_path = db_path
        self.websocket = None
        self.running = False
        self.symbol = None
        self.last_kline_data = None
        self.data_callback = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10

    def set_data_callback(self, callback: Callable):
        """Yeni veri geldiğinde çağrılacak callback fonksiyonunu ayarla"""
        self.data_callback = callback

    async def connect(self, symbol: str = 'btcusdt'):
        """WebSocket bağlantısını başlat"""
        self.symbol = symbol.lower()
        self.running = True

        # Binance WebSocket URL'i - 1 dakikalık kline verileri için
        url = f"wss://fstream.binance.com/ws/{self.symbol}@kline_1m"

        try:
            logger.info(f"WebSocket bağlantısı kuruluyor: {url}")
            ssl_context = ssl._create_unverified_context()
            async with websockets.connect(url, ssl=ssl_context, ping_interval=20, ping_timeout=10) as websocket:
                self.websocket = websocket
                self.reconnect_attempts = 0
                logger.info(f"WebSocket bağlantısı kuruldu: {symbol}")

                async for message in websocket:
                    if not self.running:
                        break

                    try:
                        data = json.loads(message)
                        await self.process_kline_data(data)
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON parse hatası: {e}")
                    except Exception as e:
                        logger.error(f"Veri işleme hatası: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket bağlantısı kapandı")
            if self.running:
                await self.reconnect()
        except Exception as e:
            logger.error(f"WebSocket bağlantı hatası: {e}")
            if self.running:
                await self.reconnect()

    async def reconnect(self):
        """Bağlantıyı yeniden kur"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error("Maksimum yeniden bağlantı denemesi aşıldı")
            self.running = False
            return

        self.reconnect_attempts += 1
        wait_time = min(60, 5 * self.reconnect_attempts)
        logger.info(
            f"Yeniden bağlanma denemesi {self.reconnect_attempts}/{self.max_reconnect_attempts} - {wait_time} saniye bekleniyor")

        await asyncio.sleep(wait_time)

        if self.running:
            await self.connect(self.symbol)

    async def process_kline_data(self, data):
        """Gelen kline verisini işle"""
        if 'k' not in data:
            return

        kline = data['k']

        # Kline verisini parse et
        kline_data = {
            'symbol': kline['s'],
            'timestamp': int(kline['t']),  # Kline başlangıç zamanı
            'close_time': int(kline['T']),  # Kline bitiş zamanı
            'open': float(kline['o']),
            'high': float(kline['h']),
            'low': float(kline['l']),
            'close': float(kline['c']),
            'volume': float(kline['v']),
            'is_closed': kline['x']  # Kline kapandı mı (True/False)
        }

        # Sadece kapanan kline'ları kaydet (is_closed = True)
        if kline_data['is_closed']:
            logger.info(
                f"Yeni kapanan kline: {datetime.fromtimestamp(kline_data['timestamp'] / 1000)} - Close: {kline_data['close']}")
            self.save_to_database(kline_data)

            # Callback fonksiyonunu çağır
            if self.data_callback:
                try:
                    self.data_callback(kline_data)
                except Exception as e:
                    logger.error(f"Callback fonksiyonu hatası: {e}")
        else:
            # Henüz kapanmayan kline'ı geçici olarak sakla
            self.last_kline_data = kline_data

    def save_to_database(self, kline_data):
        """Kline verisini veritabanına kaydet"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Tabloyu oluştur (yoksa)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ohlcv_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    timeframe TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    UNIQUE(symbol, timestamp, timeframe)
                )
            ''')

            # Veriyi kaydet
            symbol_formatted = kline_data['symbol'].replace('USDT', '/USDT')

            cursor.execute('''
                INSERT OR REPLACE INTO ohlcv_data 
                (symbol, timestamp, timeframe, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                symbol_formatted,
                kline_data['timestamp'],
                '1m',
                kline_data['open'],
                kline_data['high'],
                kline_data['low'],
                kline_data['close'],
                kline_data['volume']
            ))

            conn.commit()
            conn.close()

            logger.debug(
                f"Veri kaydedildi: {symbol_formatted} - {datetime.fromtimestamp(kline_data['timestamp'] / 1000)}")

        except sqlite3.Error as e:
            logger.error(f"Veritabanı hatası: {e}")
        except Exception as e:
            logger.error(f"Veri kaydetme hatası: {e}")

    def get_last_price(self) -> Optional[float]:
        """Son fiyatı döndür"""
        if self.last_kline_data:
            return self.last_kline_data['close']
        return None

    def stop(self):
        """WebSocket bağlantısını durdur"""
        logger.info("WebSocket bağlantısı durduruluyor...")
        self.running = False
        if self.websocket:
            asyncio.create_task(self.websocket.close())


class WebSocketManager:
    """WebSocket yöneticisi - async kodu sync ortamda çalıştırmak için"""

    def __init__(self, db_path: str = 'crypto_data.db'):
        self.db_path = db_path
        self.ws_client = None
        self.thread = None
        self.loop = None
        self.running = False

    def start(self, symbol: str = 'btcusdt', data_callback: Callable = None):
        """WebSocket'i ayrı thread'de başlat"""
        if self.running:
            logger.warning("WebSocket zaten çalışıyor")
            return

        self.running = True
        self.ws_client = BinanceWebSocketClient(self.db_path)

        if data_callback:
            self.ws_client.set_data_callback(data_callback)

        # Ayrı thread'de async loop çalıştır
        self.thread = threading.Thread(target=self._run_async_loop, args=(symbol,))
        self.thread.daemon = True
        self.thread.start()

        logger.info(f"WebSocket manager başlatıldı: {symbol}")

    def _run_async_loop(self, symbol: str):
        """Async loop'u çalıştır"""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.ws_client.connect(symbol))
        except Exception as e:
            logger.error(f"Async loop hatası: {e}")
        finally:
            if self.loop:
                self.loop.close()

    def stop(self):
        """WebSocket'i durdur"""
        if not self.running:
            return

        logger.info("WebSocket manager durduruluyor...")
        self.running = False

        if self.ws_client:
            self.ws_client.stop()

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)

        logger.info("WebSocket manager durduruldu")

    def get_last_price(self) -> Optional[float]:
        """Son fiyatı döndür"""
        if self.ws_client:
            return self.ws_client.get_last_price()
        return None

    def is_running(self) -> bool:
        """WebSocket çalışıyor mu?"""
        return self.running and self.ws_client and self.ws_client.running


# Test fonksiyonu
def test_websocket():
    """WebSocket test fonksiyonu"""

    def on_new_data(kline_data):
        print(
            f"Yeni veri: {kline_data['symbol']} - {kline_data['close']} - {datetime.fromtimestamp(kline_data['timestamp'] / 1000)}")

    manager = WebSocketManager()
    manager.start('btcusdt', on_new_data)

    try:
        while True:
            time.sleep(10)
            last_price = manager.get_last_price()
            if last_price:
                print(f"Son fiyat: {last_price}")
    except KeyboardInterrupt:
        print("Test durduruluyor...")
    finally:
        manager.stop()


if __name__ == "__main__":
    test_websocket()