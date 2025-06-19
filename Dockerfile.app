FROM registry.digitalocean.com/bitirme/base

ENV DEBIAN_FRONTEND=noninteractive

# Uygulama dosyalarını kopyala
RUN rm -rf /home/${USERNAME}/KriptoTahmin
COPY . .
RUN cp .env.example .env
# Ana scripti çalıştır

RUN  sed -i '/sqlite3/d' requirements.txt && sed -i '/argparse/d' requirements.txt && sed -i '/talib/d' requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

CMD ["python", "kripto.py", "--mode", "analyze", "--batch", "1"]
