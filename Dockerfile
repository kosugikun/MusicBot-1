FROM alpine:edge

# プロジェクトソースを追加
WORKDIR /usr/src/musicbot
COPY . ./

# 依存関係をインストールする
RUN apk update \
&& apk add --no-cache \
  ca-certificates \
  ffmpeg \
  opus \
  python3 \
  libsodium-dev \
\
# ビルドの依存関係をインストールする
&& apk add --no-cache --virtual .build-deps \
  gcc \
  git \
  libffi-dev \
  make \
  musl-dev \
  python3-dev \
\
# pip依存関係をインストールする
&& pip3 install --no-cache-dir -r requirements.txt \
&& pip3 install --upgrade --force-reinstall --version websockets==4.0.1 \
\
# ビルドの依存関係をクリーンアップする
&& apk del .build-deps

# 構成をマッピングするためのボリュームを作成します
VOLUME /usr/src/musicbot/config

ENV APP_ENV=docker

ENTRYPOINT ["python3", "dockerentry.py"]
