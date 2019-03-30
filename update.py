#!/usr/bin/env python3

import os
import subprocess
import sys

def y_n(q):
    while True:
        ri = input('{} (y/n): '.format(q))
        if ri.lower() in ['yes', 'y']: return True
        elif ri.lower() in ['no', 'n']: return False

def update_deps():
    print("依存関係を更新しようとしています...")

    try:
        subprocess.check_call('"{}" -m pip install -U -r requirements.txt'.format(sys.executable), shell=True)
    except subprocess.CalledProcessError:
        raise OSError("依存関係を更新できませんでした。自分で '\"{0}\" -m pip install -U -r requirements.txt'を実行する必要があります。".format(sys.executable))

def finalize():
    try:
        from musicbot.constants import VERSION
        print('The current MusicBot version is {0}.'.format(VERSION))
    except Exception:
        print('現在のボットバージョンの取得中に問題が発生しました。インストールが正しく完了していない可能性があります。')

    print("完了しました。")

def main():
    print('Starting...')

    # Make sure that we're in a Git repository
    if not os.path.isdir('.git'):
        raise EnvironmentError("This isn't a Git repository.")

    # Make sure that we can actually use Git on the command line
    # because some people install Git Bash without allowing access to Windows CMD
    try:
        subprocess.check_call('git --version', shell=True, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        raise EnvironmentError("CLIでGitを使用できませんでした。あなたは自身で 'git pull'を実行する必要があります。")

    print("Gitチェックに合格しました...")

    # Check that the current working directory is clean
    sp = subprocess.check_output('git status --porcelain', shell=True, universal_newlines=True)
    if sp:
        oshit = y_n('Gitによって追跡されているファイル（例えばbotのソースファイル）を修正しました。\n'
                    'レポジトリをリセットしてみるべきでしょうか。あなたはローカルの修正を失うでしょう。')
        if oshit:
            try:
                subprocess.check_call('git reset --hard', shell=True)
            except subprocess.CalledProcessError:
                raise OSError("Could not reset the directory to a clean state.")
        else:
            wowee = y_n('OK、ボットの更新をスキップします。まだ依存関係を更新しますか？')
            if wowee:
                update_deps()
            else:
                finalize()
            return

    print("ボットを更新する必要があるかどうかを確認しています...")

    
    try:
        subprocess.check_call('git pull', shell=True)
    except subprocess.CalledProcessError:
        raise OSError("ボットを更新できませんでした。あなたは自身で 'git pull'を実行する必要があります。")

    update_deps()
    finalize()

if __name__ == '__main__':
    main()
