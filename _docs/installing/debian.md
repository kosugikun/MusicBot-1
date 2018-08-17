---
title: Debian
category: ボットのインストール
order: 5
---

<img class="doc-img" src="{{ site.baseurl }}/images/debian.png" alt="debian" style="width: 75px; float: right;"/>

DebianのボットをインストールのはUbuntuに似ていますが、aptをインストールする必要があります`apt`.

~~~ bash
# システムリポジトリを更新する
sudo apt-get update -y
sudo apt-get upgrade -y

# 依存関係をインストールする 
sudo apt-get install git libopus-dev libffi-dev libsodium-dev ffmpeg -y
sudo apt-get install build-essential libncursesw5-dev libgdbm-dev libc6-dev zlib1g-dev libsqlite3-dev tk-dev libssl-dev openssl -y

# DebianにPythonがインストールされていない場合は、インストールが必要になります。
sudo apt-get install python3.5 -y

# 自分の好きなディレクトリにMusicBot JPを複製
cd ~
git clone https://github.com/kosugikun/MusicBot.git MusicBot -b master
cd MusicBot

# 依存関係のインストール
sudo -H python3.5 -m pip install --upgrade pip
sudo -H python3.5 -m pip install --upgrade -r requirements.txt
~~~

この後MusicBotが、設定したディテクトリにあると思います。見つかったら、コンフィグを設定して./run.shし、次に実行してボットを起動します。
