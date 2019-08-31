import os
import sys
import codecs
import shutil
import logging
import configparser

from .exceptions import HelpfulError

log = logging.getLogger(__name__)


class Config:
    # noinspection PyUnresolvedReferences
    def __init__(self, config_file):
        self.config_file = config_file
        self.find_config()

        config = configparser.ConfigParser(interpolation=None)
        config.read(config_file, encoding='utf-8')

        confsections = {"Credentials", "Permissions", "Chat", "MusicBot"}.difference(config.sections())
        if confsections:
            raise HelpfulError(
                "1つ以上の必要な構成セクションが欠落しています。",
                "設定を修正します。  各[Section]は、他の何も持たない "
                "独自の行にある必要があります。  以下のセクションが欠落しています。: {}".format(
                    ', '.join(['[%s]' % s for s in confsections])
                ),
                preface="構成の解析中にエラーが発生しました:\n"
            )

        self._confpreface = "設定の読み取り中にエラーが発生しました：\n"
        self._confpreface2 = "設定の検証中にエラーが発生しました：\n"

        self._login_token = config.get('Credentials', 'Token', fallback=ConfigDefaults.token)

        self.auth = ()

        self.spotify_clientid = config.get('Credentials', 'Spotify_ClientID', fallback=ConfigDefaults.spotify_clientid)
        self.spotify_clientsecret = config.get('Credentials', 'Spotify_ClientSecret', fallback=ConfigDefaults.spotify_clientsecret)

        self.owner_id = config.get('Permissions', 'OwnerID', fallback=ConfigDefaults.owner_id)
        self.dev_ids = config.get('Permissions', 'DevIDs', fallback=ConfigDefaults.dev_ids)
        self.bot_exception_ids = config.get("Permissions", "BotExceptionIDs", fallback=ConfigDefaults.bot_exception_ids)

        self.command_prefix = config.get('Chat', 'CommandPrefix', fallback=ConfigDefaults.command_prefix)
        self.bound_channels = config.get('Chat', 'BindToChannels', fallback=ConfigDefaults.bound_channels)
        self.unbound_servers = config.getboolean('Chat', 'AllowUnboundServers', fallback=ConfigDefaults.unbound_servers)
        self.autojoin_channels =  config.get('Chat', 'AutojoinChannels', fallback=ConfigDefaults.autojoin_channels)
        self.dm_nowplaying = config.getboolean('Chat', 'DMNowPlaying', fallback=ConfigDefaults.dm_nowplaying)
        self.no_nowplaying_auto = config.getboolean('Chat', 'DisableNowPlayingAutomatic', fallback=ConfigDefaults.no_nowplaying_auto)
        self.nowplaying_channels =  config.get('Chat', 'NowPlayingChannels', fallback=ConfigDefaults.nowplaying_channels)
        self.delete_nowplaying = config.getboolean('Chat', 'DeleteNowPlaying', fallback=ConfigDefaults.delete_nowplaying)

        self.default_volume = config.getfloat('MusicBot', 'DefaultVolume', fallback=ConfigDefaults.default_volume)
        self.skips_required = config.getint('MusicBot', 'SkipsRequired', fallback=ConfigDefaults.skips_required)
        self.skip_ratio_required = config.getfloat('MusicBot', 'SkipRatio', fallback=ConfigDefaults.skip_ratio_required)
        self.save_videos = config.getboolean('MusicBot', 'SaveVideos', fallback=ConfigDefaults.save_videos)
        self.now_playing_mentions = config.getboolean('MusicBot', 'NowPlayingMentions', fallback=ConfigDefaults.now_playing_mentions)
        self.auto_summon = config.getboolean('MusicBot', 'AutoSummon', fallback=ConfigDefaults.auto_summon)
        self.auto_playlist = config.getboolean('MusicBot', 'UseAutoPlaylist', fallback=ConfigDefaults.auto_playlist)
        self.auto_playlist_random = config.getboolean('MusicBot', 'AutoPlaylistRandom', fallback=ConfigDefaults.auto_playlist_random)
        self.auto_pause = config.getboolean('MusicBot', 'AutoPause', fallback=ConfigDefaults.auto_pause)
        self.delete_messages = config.getboolean('MusicBot', 'DeleteMessages', fallback=ConfigDefaults.delete_messages)
        self.delete_invoking = config.getboolean('MusicBot', 'DeleteInvoking', fallback=ConfigDefaults.delete_invoking)
        self.persistent_queue = config.getboolean('MusicBot', 'PersistentQueue', fallback=ConfigDefaults.persistent_queue)
        self.status_message = config.get('MusicBot', 'StatusMessage', fallback=ConfigDefaults.status_message)
        self.write_current_song = config.getboolean('MusicBot', 'WriteCurrentSong', fallback=ConfigDefaults.write_current_song)
        self.allow_author_skip = config.getboolean('MusicBot', 'AllowAuthorSkip', fallback=ConfigDefaults.allow_author_skip)
        self.use_experimental_equalization = config.getboolean('MusicBot', 'UseExperimentalEqualization', fallback=ConfigDefaults.use_experimental_equalization)
        self.embeds = config.getboolean('MusicBot', 'UseEmbeds', fallback=ConfigDefaults.embeds)
        self.queue_length = config.getint('MusicBot', 'QueueLength', fallback=ConfigDefaults.queue_length)
        self.remove_ap = config.getboolean('MusicBot', 'RemoveFromAPOnError', fallback=ConfigDefaults.remove_ap)
        self.show_config_at_start = config.getboolean('MusicBot', 'ShowConfigOnLaunch', fallback=ConfigDefaults.show_config_at_start)
        self.legacy_skip = config.getboolean('MusicBot', 'LegacySkip', fallback=ConfigDefaults.legacy_skip)
        self.leavenonowners = config.getboolean('MusicBot', 'LeaveServersWithoutOwner', fallback=ConfigDefaults.leavenonowners)
        self.usealias = config.getboolean('MusicBot', 'UseAlias', fallback=ConfigDefaults.usealias)

        self.debug_level = config.get('MusicBot', 'DebugLevel', fallback=ConfigDefaults.debug_level)
        self.debug_level_str = self.debug_level
        self.debug_mode = False

        self.blacklist_file = config.get('Files', 'BlacklistFile', fallback=ConfigDefaults.blacklist_file)
        self.auto_playlist_file = config.get('Files', 'AutoPlaylistFile', fallback=ConfigDefaults.auto_playlist_file)
        self.i18n_file = config.get('Files', 'i18nFile', fallback=ConfigDefaults.i18n_file)
        self.auto_playlist_removed_file = None

        self.run_checks()

        self.missing_keys = set()
        self.check_changes(config)

        self.find_autoplaylist()

    def get_all_keys(self, conf):
        """Returns all config keys as a list"""
        sects = dict(conf.items())
        keys = []
        for k in sects:
            s = sects[k]
            keys += [key for key in s.keys()]
        return keys

    def check_changes(self, conf):
        exfile = 'config/example_options.ini'
        if os.path.isfile(exfile):
            usr_keys = self.get_all_keys(conf)
            exconf = configparser.ConfigParser(interpolation=None)
            if not exconf.read(exfile, encoding='utf-8'):
                return
            ex_keys = self.get_all_keys(exconf)
            if set(usr_keys) != set(ex_keys):
                self.missing_keys = set(ex_keys) - set(usr_keys)  # to raise this as an issue in bot.py later

    def run_checks(self):
        """
        Validation logic for bot settings.
        """
        if self.i18n_file != ConfigDefaults.i18n_file and not os.path.isfile(self.i18n_file):
            log.warning('i18nファイルが存在しません。 {0}にフォールバックしようとしています。'.format(ConfigDefaults.i18n_file))
            self.i18n_file = ConfigDefaults.i18n_file

        if not os.path.isfile(self.i18n_file):
            raise HelpfulError(
                "i18nファイルが見つからなかったため、フォールバックできませんでした。",
                "その結果、ボットは起動できません。 いくつかのファイルを移動しましたか？ "
                "Gitから最近の変更をプルするか、ローカルリポジトリをリセットしてください。",
                preface=self._confpreface
            )

        log.info('国際化の使用: {0}'.format(self.i18n_file))

        if not self._login_token:
            raise HelpfulError(
                "設定にボットトークンが指定されていません。",
                "Discordボットアカウントを使用する必要があります。"
                "詳細については、https://github.com/Just-Some-Bots/MusicBot/wiki/FAQを参照してください。",
                preface=self._confpreface
            )

        else:
            self.auth = (self._login_token,)

        if self.owner_id:
            self.owner_id = self.owner_id.lower()

            if self.owner_id.isdigit():
                if int(self.owner_id) < 10000:
                    raise HelpfulError(
                        "無効なOwnerIDが設定されました: {}".format(self.owner_id),

                        "OwnerIDを修正してください。 IDは単なる数字、約18文字の長さ、 "
                        "または'auto'でなければなりません。 IDがわからない場合は、 "
                        "オプションの指示を読むか、ヘルプサーバーに問い合わせてください。",
                        preface=self._confpreface
                    )
                self.owner_id = int(self.owner_id)

            elif self.owner_id == 'auto':
                pass # defer to async check

            else:
                self.owner_id = None

        if not self.owner_id:
            raise HelpfulError(
                "OwnerIDは設定されていません。",
                "{}でOwnerIDオプションを設定してください".format(self.config_file),
                preface=self._confpreface
            )

        if self.bot_exception_ids:
            try:
                self.bot_exception_ids = set(int(x) for x in self.bot_exception_ids.replace(',', ' ').split())
            except:
                log.warning("BotExceptionIDsデータは無効です。すべてのボットを無視します")
                self.bot_exception_ids = set()

        if self.bound_channels:
            try:
                self.bound_channels = set(x for x in self.bound_channels.replace(',', ' ').split() if x)
            except:
                log.warning("BindToChannelsデータは無効です。どのチャネルにもバインドしません")
                self.bound_channels = set()

        if self.autojoin_channels:
            try:
                self.autojoin_channels = set(x for x in self.autojoin_channels.replace(',', ' ').split() if x)
            except:
                log.warning("AutojoinChannelsデータは無効です。どのチャネルにも自動参加しません")
                self.autojoin_channels = set()

        if self.nowplaying_channels:
            try:
                self.nowplaying_channels = set(int(x) for x in self.nowplaying_channels.replace(',', ' ').split() if x)
            except:
                log.warning("NowPlayingChannelsデータは無効です。すべてのサーバーに対してデフォルトの動作を使用します")
                self.autojoin_channels = set()

        self._spotify = False
        if self.spotify_clientid and self.spotify_clientsecret:
            self._spotify = True

        self.delete_invoking = self.delete_invoking and self.delete_messages

        self.bound_channels = set(int(item) for item in self.bound_channels)

        self.autojoin_channels = set(int(item) for item in self.autojoin_channels)

        ap_path, ap_name = os.path.split(self.auto_playlist_file)
        apn_name, apn_ext = os.path.splitext(ap_name)
        self.auto_playlist_removed_file = os.path.join(ap_path, apn_name + '_removed' + apn_ext)

        if hasattr(logging, self.debug_level.upper()):
            self.debug_level = getattr(logging, self.debug_level.upper())
        else:
            log.warning("無効なDebugLevelオプション\"{}\"が指定され、INFOにフォールバック".format(self.debug_level_str))
            self.debug_level = logging.INFO
            self.debug_level_str = 'INFO'

        self.debug_mode = self.debug_level <= logging.DEBUG

        self.create_empty_file_ifnoexist('config/blacklist.txt')
        self.create_empty_file_ifnoexist('config/whitelist.txt')

    def create_empty_file_ifnoexist(self, path):
        if not os.path.isfile(path):
            open(path, 'a').close()
            log.warning('%sを作成しています' % path)

    # TODO: Add save function for future editing of options with commands
    #       Maybe add warnings about fields missing from the config file

    async def async_validate(self, bot):
        log.debug("オプションの検証...")

        if self.owner_id == 'auto':
            if not bot.user.bot:
                raise HelpfulError(
                    "OwnerIDオプションのパラメーター\"auto\"が無効です。",

                    "ボットアカウントのみが\"auto\"オプションを使用できます。"
                    "configでOwnerIDを設定してください。",

                    preface=self._confpreface2
                )

            self.owner_id = bot.cached_app_info.owner.id
            log.debug("API経由で取得したオーナーID")

        if self.owner_id == bot.user.id:
            raise HelpfulError(
                "OwnerIDが間違っているか、間違った資格情報を使用しました。",

                "ボットのユーザーIDとOwnerIDのIDは同一です。"
                "これは間違っています。 ボットが機能するにはボットアカウントが必要です。 "
                "つまり、自分のアカウントを使用してボットを実行することはできません。 "
                "OwnerIDは、ボットではなくオーナーのIDです。 "
                "どれがどれであるかを把握し、正しい情報を使用してください。",

                preface=self._confpreface2
            )


    def find_config(self):
        config = configparser.ConfigParser(interpolation=None)

        if not os.path.isfile(self.config_file):
            if os.path.isfile(self.config_file + '.ini'):
                shutil.move(self.config_file + '.ini', self.config_file)
                log.info("{0}を{1}に移動して、ファイル拡張子をオンにする必要があります。".format(
                    self.config_file + '.ini', self.config_file
                ))

            elif os.path.isfile('config/example_options.ini'):
                shutil.copy('config/example_options.ini', self.config_file)
                log.warning('example_options.iniをコピーして、オプションファイルが見つかりません')

            else:
                raise HelpfulError(
                    "設定ファイルがありません。 options.iniもexample_options.iniも見つかりませんでした。",
                    "アーカイブからファイルを取得するか、自分で再作成して、リポジトリからコンテンツを "
                    "コピーして貼り付けます。 重要なファイルの削除を停止してください！"
                )

        if not config.read(self.config_file, encoding='utf-8'):
            c = configparser.ConfigParser()
            try:
                # load the config again and check to see if the user edited that one
                c.read(self.config_file, encoding='utf-8')

                if not int(c.get('Permissions', 'OwnerID', fallback=0)): # jake pls no flame
                    print(flush=True)
                    log.critical("config/options.iniを設定し、ボットを再実行してください。")
                    sys.exit(1)

            except ValueError: # Config id value was changed but its not valid
                raise HelpfulError(
                    'OwnerIDの値「{}」が無効です。構成をロードできません。 '.format(
                        c.get('Permissions', 'OwnerID', fallback=None)
                    ),
                    "OwnerIDオプションには、ユーザーIDまたは'auto'が必要です。"
                )

            except Exception as e:
                print(flush=True)
                log.critical("config/example_options.iniを{}にコピーできません".format(self.config_file), exc_info=e)
                sys.exit(2)

    def find_autoplaylist(self):
        if not os.path.exists(self.auto_playlist_file):
            if os.path.exists('config/_autoplaylist.txt'):
                shutil.copy('config/_autoplaylist.txt', self.auto_playlist_file)
                log.debug("_autoplaylist.txtをautoplaylist.txtにコピー")
            else:
                log.warning("オートプレイリストファイルが見つかりません。")


    def write_default_config(self, location):
        pass


class ConfigDefaults:
    owner_id = None

    token = None
    dev_ids = set()
    bot_exception_ids = set()

    spotify_clientid = None
    spotify_clientsecret = None

    command_prefix = '!'
    bound_channels = set()
    unbound_servers = False
    autojoin_channels = set()
    dm_nowplaying = False
    no_nowplaying_auto = False
    nowplaying_channels = set()
    delete_nowplaying = True

    default_volume = 0.15
    skips_required = 4
    skip_ratio_required = 0.5
    save_videos = True
    now_playing_mentions = False
    auto_summon = True
    auto_playlist = True
    auto_playlist_random = True
    auto_pause = True
    delete_messages = True
    delete_invoking = False
    persistent_queue = True
    debug_level = 'INFO'
    status_message = None
    write_current_song = False
    allow_author_skip = True
    use_experimental_equalization = False
    embeds = True
    queue_length = 10
    remove_ap = True
    show_config_at_start = False
    legacy_skip = False
    leavenonowners = False
    usealias = True

    options_file = 'config/options.ini'
    blacklist_file = 'config/blacklist.txt'
    auto_playlist_file = 'config/autoplaylist.txt'  # this will change when I add playlists
    i18n_file = 'config/i18n/ja.json'

setattr(ConfigDefaults, codecs.decode(b'ZW1haWw=', '\x62\x61\x73\x65\x36\x34').decode('ascii'), None)
setattr(ConfigDefaults, codecs.decode(b'cGFzc3dvcmQ=', '\x62\x61\x73\x65\x36\x34').decode('ascii'), None)
setattr(ConfigDefaults, codecs.decode(b'dG9rZW4=', '\x62\x61\x73\x65\x36\x34').decode('ascii'), None)

# These two are going to be wrappers for the id lists, with add/remove/load/save functions
# and id/object conversion so types aren't an issue
class Blacklist:
    pass

class Whitelist:
    pass
