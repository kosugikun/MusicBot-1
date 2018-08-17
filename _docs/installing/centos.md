---
title: CentOS
category: ボットのインストール
order: 6
---

<img class="doc-img" src="{{ site.baseurl }}/images/centos.png" alt="centos" style="width: 75px; float: right;"/>
CentOSへのインストールは、主に未テストであり、**問​​題のため正式にサポートされていません**。サポートを求めるときは、この点を念頭に置いてください。

CentOSのインストール手順は、ご使用のOSのバージョンによって異なります。

## CentOS 6.9

~~~sh
# 依存関係をインストールする
sudo yum -y update
sudo yum -y groupinstall "Development Tools"
sudo yum -y install https://centos6.iuscommunity.org/ius-release.rpm
sudo yum -y install yum-utils opus-devel libffi-devel libsodium-devel python35u python35u-devel python35u-pip

# FFmpegをインストールする
sudo rpm --import http://li.nux.ro/download/nux/RPM-GPG-KEY-nux.ro
sudo rpm -Uvh http://li.nux.ro/download/nux/dextop/el6/x86_64/nux-dextop-release-0-2.el6.nux.noarch.rpm
sudo yum -y install ffmpeg ffmpeg-devel -y

# ソースからlibsodiumをインストールする
mkdir libsodium && cd libsodium
curl -o libsodium.tar.gz https://download.libsodium.org/libsodium/releases/LATEST.tar.gz
tar -zxvf libsodium.tar.gz && cd libsodium-stable
./configure
make && make check
sudo make install
cd ../.. && rm -rf libsodium

# MusicBot JPをクローン
git clone https://github.com/kosugikun/MusicBot.git MusicBot -b master
cd MusicBot

# ボットの要件をインストールする
sudo pip3.5 install -U -r requirements.txt
sudo pip3.5 install -U pynacl
~~~

## CentOS 7.4

~~~
# 依存関係をインストールする
sudo yum -y update
sudo yum -y groupinstall "Development Tools"
sudo yum -y install https://centos7.iuscommunity.org/ius-release.rpm
sudo yum -y install curl opus-devel libffi-devel libsodium-devel python35u python35u-devel python35u-pip

# FFmpegをインストールする
sudo rpm --import http://li.nux.ro/download/nux/RPM-GPG-KEY-nux.ro
sudo rpm -Uvh http://li.nux.ro/download/nux/dextop/el7/x86_64/nux-dextop-release-0-5.el7.nux.noarch.rpm
sudo yum -y install ffmpeg ffmpeg-devel -y

# MusicBot JPをクローン
git clone https://github.com/kosugikun/MusicBot.git MusicBot -b master
cd MusicBot

# ボットの要件をインストールする
sudo python3.5 -m pip install -U -r requirements.txt
~~~
{: title="CentOS 7.4" }

上記が完了したら、ボットのコンフィグを設定し`sudo ./run.sh`を実行すると、起動できます。
