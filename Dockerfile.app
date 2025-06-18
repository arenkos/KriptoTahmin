FROM registry.digitalocean.com/bitirme/base

ENV DEBIAN_FRONTEND=noninteractive

# Uygulama dosyalarını kopyala
RUN rm -rf /home/${USERNAME}/KriptoTahmin
COPY . .
RUN cp .env.example .env
# Ana scripti çalıştır
CMD ["python", "kripto.py", "--mode", "analyze", "--batch", "1"]
