import os
import subprocess
import sys

def y_n(q):
    while True:
        ri = input('{} (y/n): '.format(q))
        if ri.lower() in ['yes', 'y']: return True
        elif ri.lower() in ['no', 'n']: return False

def main():
    print('起動...')

    # Make sure that we're in a Git repository
    if not os.path.isdir('.git'):
        raise EnvironmentError("これはGitリポジトリではありません。")

    # Make sure that we can actually use Git on the command line
    # because some people install Git Bash without allowing access to Windows CMD
    try:
        subprocess.check_call('git --version', shell=True, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        raise EnvironmentError("CLIでGitを使用できませんでした。 git pullを自分で実行する必要があります。")

    print("渡されたGitのチェック...")

    # Check that the current working directory is clean
    sp = subprocess.check_output('git status --porcelain', shell=True, universal_newlines=True)
    if sp:
        oshit = y_n('Gitによって追跡されるファイル（例えば、botのソースファイル）を変更しました。\n'
                    '私たちはあなたのためにあなたのクリーンバージョンにあなたのフォルダをリセットしようとすることができます。持続する？')
        if oshit:
            try:
                subprocess.check_call('git reset --hard', shell=True)
            except subprocess.CalledProcessError:
                raise OSError("ディレクトリをクリーンな状態にリセットできませんでした。")
        else:
            print('はい。今すぐ更新プロセスをキャンセルします。')
            return

    print("Gitを使ってボットを更新しようとしています...")

    try:
        subprocess.check_call('git pull', shell=True)
    except subprocess.CalledProcessError:
        raise OSError("ボットを更新できませんでした。 git pullを自分で実行する必要があります。")

    print("依存関係を更新しようとしています...")

    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-U', '-r', 'requirements.txt'], shell=True)
    except subprocess.CalledProcessError:
        raise OSError("依存関係を更新できませんでした。 '{0} -m pip install -U -r requirements.txt'を実行する必要があります。".format(sys.executable))


    try:
        from musicbot.constants import VERSION
        print('MusicBot JPはバージョン{0}です'.format(VERSION))
    except Exception:
        pass

    print("完了!")

if __name__ == '__main__':
    main()
