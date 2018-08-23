---
title: アップデートする
category: ボットの使用
order: 4
---

![GitHub release](https://img.shields.io/github/release/kosugikun/MusicBot.svg?style=flat-square)

アップデートする前に、[最新の変更点](/changelog)を確認してください。動作が大幅に変更されている可能性があります。

* **Linux/MacOS**: `./update.sh` (for Mac users: run this in a Terminal)
* **Windows**: Open `update.bat`.
* **Other**: Run `python update.py` on the command line.

## Manual update

```sh
git reset --hard  # Reset your current working directory
git pull  # Pull the latest changes from Git
python -m pip install -U -r requirements.txt  # Update the dependencies
```

### Common problems
#### error: Your local changes to the following files would be overwritten by merge
This indicates that you are trying to pull the latest updates from Git, but you've made changes to the bot's source files yourself. As a result, Git struggles to merge your changes with the bot's changes. To fix this, stash your changes first by running `git stash`, then run `git stash pop` after pulling.

Alternatively, discard your local changes by running `git reset --hard`.

> We do not support modification. If you are having issues updating because you have edited the bot's files, this is the most guidance you will get.

#### fatal: Not a git repository
This indicates that you have not installed the bot using Git. To be able to update, you need to install the bot using Git by following the guides on this site.
