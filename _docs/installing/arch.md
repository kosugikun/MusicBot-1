---
title: Arch
category: ボットのインストール
order: 7
---

<img class="doc-img" src="{{ site.baseurl }}/images/arch.png" alt="centos" style="width: 75px; float: right;"/>
Archへのインストールは主にテストされておらず、正式にサポートされていません。ご注意ください

~~~ bash
# システムパッケージを更新する
sudo pacman -Syu

# 依存関係のインストール
sudo pacman -S git python python-pip opus libffi libsodium ncurses gdbm glibc zlib sqlite tk openssl ffmpeg

# MusicBotを入れたいフォルダの中に、MusicBotをクローン
cd ~
git clone https://github.com/kosugikun/MusicBot.git MusicBot -b master
cd MusicBot

# 依存関係のインストール
sudo pip install --upgrade pip
sudo pip install --upgrade -r requirements.txt
~~~

上記が完了したら、MusicBotのコンフィグを設定して、`sh ./run.sh`で起動できます
