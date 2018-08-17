---
title: MacOS
category: ボットのインストール
order: 3
---

<img class="doc-img" src="{{ site.baseurl }}/images/mac.png" alt="Mac" style="width: 75px; float: right;"/>

MacにMusicBot JPをインストールするには、いくつかのライブラリとアプリケーションが必要です。最初に、あなたのパソコンにPython 3.5+をインストールしてください。エラーを減らしたいなら、3.5.4をお勧めします。Python 3.5.4をインストールします（インストールするpkgファイルをダブルクリックしてください）。次に、ターミナルを開いて次のコマンドを実行する必要があります：
```bash
# MAC用パッケージマネージャーのインストール
/usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
brew update
xcode-select --install

# 依存関係のインストール
brew install git
brew install ffmpeg
brew install opus
brew install libffi
brew install libsodium

# MusicBot JPをクローン
cd desktop
git clone https://github.com/kosugikun/MusicBot.git MusicBot -b master 

# Pythonの依存関係をインストール
cd MusicBot
python3 -m pip install -U pip
python3 -m pip install -U -r requirements.txt
```

その後、MusicBotあなたのデスクトップ上にフォルダがあると思います。。その後、あなたのbotを開き、あなたのbotの、コンフィグを設定してから、そのrun.shファイルをダブルクリックして実行することができます。これを実行できない場合は、「ターミナル」を開いてフォルダにcdしてchmod +x run.sh、ファイルに実行可能なアクセス権を与える必要があります。
