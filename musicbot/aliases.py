import logging
import shutil
import json
from pathlib import Path

from .exceptions import HelpfulError

log = logging.getLogger(__name__)


class Aliases:
    def __init__(self, aliases_file):
        self.aliases_file = Path(aliases_file)
        self.aliases_seed = AliasesDefault.aliases_seed
        self.aliases = AliasesDefault.aliases

        # find aliases file
        if not self.aliases_file.is_file():
            example_aliases = Path('config/example_aliases.json')
            if example_aliases.is_file():
                shutil.copy(str(example_aliases), str(self.aliases_file))
                log.warning('example_aliases.jsonをコピーしている別名ファイルが見つかりません')
            else:
                raise HelpfulError(
                    "エイリアスファイルが見つかりません。 aliases.jsonもexample_aliases.jsonも見つかりませんでした。",
                    "アーカイブからファイルを取り戻すか、自分で作り直して内容をコピーして貼り付けてください。 "
                    "レポから。重要なファイルの削除をやめて！"
                )

        # parse json
        with self.aliases_file.open() as f:
            try:
                self.aliases_seed = json.load(f)
            except:
                raise HelpfulError(
                    "エイリアスファイルの解析に失敗しました。",
                    "{}が有効なjsonファイルであることを確認して、ボットを再起動してください。".format(str(self.aliases_file))
                )

        # construct
        for cmd, aliases in self.aliases_seed.items():
            if not isinstance(cmd, str) or not isinstance(aliases, list):
                raise HelpfulError(
                    "エイリアスファイルの解析に失敗しました。",
                    "ドキュメントとconfig {}を正しく参照してください。".format(str(self.aliases_file))
                )
            self.aliases.update({alias.lower(): cmd.lower() for alias in aliases})
    
    def get(self, arg):
        """
        Return cmd name (string) that given arg points.
        If arg is not registered as alias, empty string will be returned.
        supposed to be called from bot.on_message
        """
        ret = self.aliases.get(arg)
        return ret if ret else ''
            
class AliasesDefault:
    aliases_file = 'config/aliases.json'
    aliases_seed = {}
    aliases = {}
