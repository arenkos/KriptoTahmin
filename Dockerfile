FROM python:3.11-slim as base

ENV DEBIAN_FRONTEND=noninteractive

ARG USERNAME=user
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN apt-get update -y && apt-get install -y sudo
# Create the user, no sudo password req
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME


ENV SHELL=/bin/bash
USER $USERNAME
WORKDIR /home/${USERNAME}

# Build essential
RUN sudo apt update -y && sudo apt-get install -y python3-pip \
    python3-venv build-essential make cmake \
    wget curl git
# Build tailib
RUN sudo apt-get update && \
    sudo apt-get install -y build-essential wget && \
    wget https://github.com/TA-Lib/ta-lib/releases/download/v0.6.4/ta-lib-0.6.4-src.tar.gz && \
    tar -xzf ta-lib-0.6.4-src.tar.gz && \
    cd ta-lib-0.6.4 && \
    ./configure && make && sudo make install && \
    sudo ldconfig &&\
    sudo rm -rf /var/lib/apt/lists/*
# Build proje
RUN sudo apt update -y && sudo -E apt install -y tmux python3-flask &&\
    pip3 install Flask-Migrate scikit-learn email_validator

RUN git clone https://github.com/arenkos/KriptoTahmin.git && cd KriptoTahmin &&\
    sed -i '/sqlite3/d' requirements.txt && sed -i '/argparse/d' requirements.txt && sed -i '/talib/d' requirements.txt &&\
    pip3 install -r requirements.txt

# give your own config or cp .env.example .env
COPY .env KriptoTahmin/.env

WORKDIR /home/${USERNAME}/KriptoTahmin
RUN git pull origin main

# Çalışma dizinini ayarla
WORKDIR /app

# Gereksinimleri kopyala ve yükle
COPY requirements.txt .
RUN  sed -i '/sqlite3/d' requirements.txt && sed -i '/argparse/d' requirements.txt && sed -i '/talib/d' requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

FROM base AS app
# Uygulama dosyalarını kopyala
RUN rm -rf /home/${USERNAME}/KriptoTahmin
COPY . .

# Ana scripti çalıştır
CMD ["python", "kripto.py", "--mode", "analyze", "--batch", "1"]
