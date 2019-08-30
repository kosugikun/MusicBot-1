import json
import logging

log = logging.getLogger(__name__)

class Json:
    def __init__(self, json_file):
        log.debug('{0}でJSONオブジェクトを初期化'.format(json_file))
        self.file = json_file
        self.data = self.parse()

    def parse(self):
        """Parse the file as JSON"""
        with open(self.file, encoding='utf-8') as data:
            try:
                parsed = json.load(data)
            except Exception:
                log.error('JSONとしての{0}の解析エラー'.format(self.file), exc_info=True)
                parsed = {}
        return parsed

    def get(self, item, fallback=None):
        """Gets an item from a JSON file"""
        try:
            data = self.data[item]
        except KeyError:
            log.warning('i18nキー{0}からデータを取得できませんでした。'.format(item, fallback))
            data = fallback
        return data
