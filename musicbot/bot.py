import os
import sys
import time
import shlex
import shutil
import random
import inspect
import logging
import asyncio
import pathlib
import traceback
import math
import re

import aiohttp
import discord
import colorlog

from io import BytesIO, StringIO
from functools import wraps
from textwrap import dedent
from datetime import timedelta
from collections import defaultdict

from discord.enums import ChannelType

from . import exceptions
from . import downloader

from .playlist import Playlist
from .player import MusicPlayer
from .entry import StreamPlaylistEntry
from .opus_loader import load_opus_lib
from .config import Config, ConfigDefaults
from .permissions import Permissions, PermissionsDefaults
from .aliases import Aliases, AliasesDefault
from .constructs import SkipState, Response
from .utils import load_file, write_file, fixg, ftimedelta, _func_, _get_variable
from .spotify import Spotify
from .json import Json

from .constants import VERSION as BOTVERSION
from .constants import DISCORD_MSG_CHAR_LIMIT, AUDIO_CACHE_PATH


load_opus_lib()

log = logging.getLogger(__name__)


class MusicBot(discord.Client):
    def __init__(self, config_file=None, perms_file=None, aliases_file=None):
        try:
            sys.stdout.write("\x1b]2;MusicBot {}\x07".format(BOTVERSION))
        except:
            pass

        print()

        if config_file is None:
            config_file = ConfigDefaults.options_file

        if perms_file is None:
            perms_file = PermissionsDefaults.perms_file

        if aliases_file is None:
            aliases_file = AliasesDefault.aliases_file

        self.players = {}
        self.exit_signal = None
        self.init_ok = False
        self.cached_app_info = None
        self.last_status = None

        self.config = Config(config_file)
        
        self._setup_logging()
        
        self.permissions = Permissions(perms_file, grant_all=[self.config.owner_id])
        self.str = Json(self.config.i18n_file)

        if self.config.usealias:
            self.aliases = Aliases(aliases_file)

        self.blacklist = set(load_file(self.config.blacklist_file))
        self.autoplaylist = load_file(self.config.auto_playlist_file)

        self.aiolocks = defaultdict(asyncio.Lock)
        self.downloader = downloader.Downloader(download_folder='audio_cache')

        log.info('MusicBot JP {}を起動中'.format(BOTVERSION))

        if not self.autoplaylist:
            log.warning("自動再生リストが空のため無効になっています。")
            self.config.auto_playlist = False
        else:
            log.info("{}個のエントリを含む自動再生リストを読み込みました".format(len(self.autoplaylist)))

        if self.blacklist:
            log.debug("{}個のエントリを含むブラックリストをロードしました".format(len(self.blacklist)))

        # TODO: Do these properly
        ssd_defaults = {
            'last_np_msg': None,
            'auto_paused': False,
            'availability_paused': False
        }
        self.server_specific_data = defaultdict(ssd_defaults.copy)

        super().__init__()
        self.aiosession = aiohttp.ClientSession(loop=self.loop)
        self.http.user_agent += ' MusicBot-JP/%s' % BOTVERSION

        self.spotify = None
        if self.config._spotify:
            try:
                self.spotify = Spotify(self.config.spotify_clientid, self.config.spotify_clientsecret, aiosession=self.aiosession, loop=self.loop)
                if not self.spotify.token:
                    log.warning('Spotifyは私達にトークンを提供しませんでした。無効にします。')
                    self.config._spotify = False
                else:
                    log.info('クライアントIDとシークレットを使用してSpotifyで認証されました。')
            except exceptions.SpotifyError as e:
                log.warning('Spotifyへの接続の初期化中に問題が発生しました。あなたのクライアントIDと秘密は正しいですか？詳細:{0} とにかく5秒で続けます...'.format(e))
                self.config._spotify = False
                time.sleep(5)  # make sure they see the problem

    # TODO: Add some sort of `denied` argument for a message to send when someone else tries to use it
    def owner_only(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Only allow the owner to use these commands
            orig_msg = _get_variable('message')

            if not orig_msg or orig_msg.author.id == self.config.owner_id:
                # noinspection PyCallingNonCallable
                return await func(self, *args, **kwargs)
            else:
                raise exceptions.PermissionsError("このコマンドを使用できるのはオーナーだけです。", expire_in=30)

        return wrapper

    def dev_only(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            orig_msg = _get_variable('message')

            if str(orig_msg.author.id) in self.config.dev_ids:
                # noinspection PyCallingNonCallable
                return await func(self, *args, **kwargs)
            else:
                raise exceptions.PermissionsError("このコマンドを使用できるのは、devユーザーだけです。", expire_in=30)

        wrapper.dev_cmd = True
        return wrapper

    def ensure_appinfo(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            await self._cache_app_info()
            # noinspection PyCallingNonCallable
            return await func(self, *args, **kwargs)

        return wrapper

    def _get_owner(self, *, server=None, voice=False):
            return discord.utils.find(
                lambda m: m.id == self.config.owner_id and (m.voice if voice else True),
                server.members if server else self.get_all_members()
            )

    def _delete_old_audiocache(self, path=AUDIO_CACHE_PATH):
        try:
            shutil.rmtree(path)
            return True
        except:
            try:
                os.rename(path, path + '__')
            except:
                return False
            try:
                shutil.rmtree(path)
            except:
                os.rename(path + '__', path)
                return False

        return True

    def _setup_logging(self):
        if len(logging.getLogger(__package__).handlers) > 1:
            log.debug("ロガーの設定をスキップしています、すでに設定されています")
            return

        shandler = logging.StreamHandler(stream=sys.stdout)
        shandler.setFormatter(colorlog.LevelFormatter(
            fmt = {
                'DEBUG': '{log_color}[{levelname}:{module}] {message}',
                'INFO': '{log_color}{message}',
                'WARNING': '{log_color}{levelname}: {message}',
                'ERROR': '{log_color}[{levelname}:{module}] {message}',
                'CRITICAL': '{log_color}[{levelname}:{module}] {message}',

                'EVERYTHING': '{log_color}[{levelname}:{module}] {message}',
                'NOISY': '{log_color}[{levelname}:{module}] {message}',
                'VOICEDEBUG': '{log_color}[{levelname}:{module}][{relativeCreated:.9f}] {message}',
                'FFMPEG': '{log_color}[{levelname}:{module}][{relativeCreated:.9f}] {message}'
            },
            log_colors = {
                'DEBUG':    'cyan',
                'INFO':     'white',
                'WARNING':  'yellow',
                'ERROR':    'red',
                'CRITICAL': 'bold_red',

                'EVERYTHING': 'white',
                'NOISY':      'white',
                'FFMPEG':     'bold_purple',
                'VOICEDEBUG': 'purple',
        },
            style = '{',
            datefmt = ''
        ))
        shandler.setLevel(self.config.debug_level)
        logging.getLogger(__package__).addHandler(shandler)

        log.debug("ログレベルを{}に設定します".format(self.config.debug_level_str))

        if self.config.debug_mode:
            dlogger = logging.getLogger('discord')
            dlogger.setLevel(logging.DEBUG)
            dhandler = logging.FileHandler(filename='logs/discord.log', encoding='utf-8', mode='w')
            dhandler.setFormatter(logging.Formatter('{asctime}:{levelname}:{name}: {message}', style='{'))
            dlogger.addHandler(dhandler)

    @staticmethod
    def _check_if_empty(vchannel: discord.abc.GuildChannel, *, excluding_me=True, excluding_deaf=False):
        def check(member):
            if excluding_me and member == vchannel.guild.me:
                return False

            if excluding_deaf and any([member.deaf, member.self_deaf]):
                return False

            return True

        return not sum(1 for m in vchannel.members if check(m))

    async def _join_startup_channels(self, channels, *, autosummon=True):
        joined_servers = set()
        channel_map = {c.guild: c for c in channels}

        def _autopause(player):
            if self._check_if_empty(player.voice_client.channel):
                log.info("空のチャンネルでの最初の自動停止")

                player.pause()
                self.server_specific_data[player.voice_client.channel.guild]['auto_paused'] = True

        for guild in self.guilds:
            if guild.unavailable or guild in channel_map:
                continue

            if guild.me.voice:
                log.info("再開可能な音声チャンネル{0.guild.name}/{0.name}が見つかりました".format(guild.me.voice.channel))
                channel_map[guild] = guild.me.voice.channel

            if autosummon:
                owner = self._get_owner(server=guild, voice=True)
                if owner:
                    log.info("\"{}\"に所有者が見つかりました".format(owner.voice.channel.name))
                    channel_map[guild] = owner.voice.channel

        for guild, channel in channel_map.items():
            if guild in joined_servers:
                log.info("スキップして、\"{}\"で既にチャンネルに参加しています".format(guild.name))
                continue

            if channel and isinstance(channel, discord.VoiceChannel):
                log.info("{0.guild.name}/{0.name}に参加しようとしています".format(channel))

                chperms = channel.permissions_for(guild.me)

                if not chperms.connect:
                    log.info("チャンネル\"{}\"に権限がないため参加できません。".format(channel.name))
                    continue

                elif not chperms.speak:
                    log.info("チャンネル\"{}\"に会話をする権限がないため参加しません。".format(channel.name))
                    continue

                try:
                    player = await self.get_player(channel, create=True, deserialize=self.config.persistent_queue)
                    joined_servers.add(guild)

                    log.info("{0.guild.name}/{0.name}に参加しました".format(channel))

                    if player.is_stopped:
                        player.play()

                    if self.config.auto_playlist:
                        if self.config.auto_pause:
                            player.once('play', lambda player, **_: _autopause(player))
                        if not player.playlist.entries:
                            await self.on_player_finished_playing(player)

                except Exception:
                    log.debug("{0.guild.name}/{0.name}への参加中にエラーが発生しました".format(channel), exc_info=True)
                    log.error("{0.guild.name}/{0.name}に参加できませんでした".format(channel))

            elif channel:
                log.warning("{0.guild.name}/{0.name}に参加できません。これはテキストチャンネルです。".format(channel))

            else:
                log.warning("無効なチャンネルのもの：{}".format(channel))

    async def _wait_delete_msg(self, message, after):
        await asyncio.sleep(after)
        await self.safe_delete_message(message, quiet=True)

    # TODO: Check to see if I can just move this to on_message after the response check
    async def _manual_delete_check(self, message, *, quiet=False):
        if self.config.delete_invoking:
            await self.safe_delete_message(message, quiet=quiet)

    async def _check_ignore_non_voice(self, msg):
        if msg.guild.me.voice:
            vc = msg.guild.me.voice.channel
        else:
            vc = None

        # If we've connected to a voice chat and we're in the same voice channel
        if not vc or (msg.author.voice and vc == msg.author.voice.channel):
            return True
        else:
            raise exceptions.PermissionsError(
                "音声チャンネルにいないときはこのコマンドを使用できません(%s)" % vc.name, expire_in=30)

    async def _cache_app_info(self, *, update=False):
        if not self.cached_app_info and not update and self.user.bot:
            log.debug("キャッシングアプリ情報")
            self.cached_app_info = await self.application_info()

        return self.cached_app_info


    async def remove_from_autoplaylist(self, song_url:str, *, ex:Exception=None, delete_from_ap=False):
        if song_url not in self.autoplaylist:
            log.debug("URL \"{}\"が自動再生リストにありません、無視します".format(song_url))
            return

        async with self.aiolocks[_func_()]:
            self.autoplaylist.remove(song_url)
            log.info("セッションの自動再生リストから再生できない曲を削除しています:%s" % song_url)

            with open(self.config.auto_playlist_removed_file, 'a', encoding='utf8') as f:
                f.write(
                    '# Entry removed {ctime}\n'
                    '# Reason: {ex}\n'
                    '{url}\n\n{sep}\n\n'.format(
                        ctime=time.ctime(),
                        ex=str(ex).replace('\n', '\n#' + ' ' * 10), # 10 spaces to line up with # Reason:
                        url=song_url,
                        sep='#' * 32
                ))

            if delete_from_ap:
                log.info("自動再生リストの更新")
                write_file(self.config.auto_playlist_file, self.autoplaylist)

    @ensure_appinfo
    async def generate_invite_link(self, *, permissions=discord.Permissions(70380544), guild=None):
        return discord.utils.oauth_url(self.cached_app_info.id, permissions=permissions, guild=guild)

    async def get_voice_client(self, channel: discord.abc.GuildChannel):
        if isinstance(channel, discord.Object):
            channel = self.get_channel(channel.id)

        if not isinstance(channel, discord.VoiceChannel):
            raise AttributeError('渡されるチャンネルは音声チャンネルでなければなりません')

        if channel.guild.voice_client:
            return channel.guild.voice_client
        else:
            return await channel.connect(timeout=60, reconnect=True)

    async def disconnect_voice_client(self, guild):
        vc = self.voice_client_in(guild)
        if not vc:
            return

        if guild.id in self.players:
            self.players.pop(guild.id).kill()

        await vc.disconnect()

    async def disconnect_all_voice_clients(self):
        for vc in list(self.voice_clients).copy():
            await self.disconnect_voice_client(vc.channel.guild)

    async def set_voice_state(self, vchannel, *, mute=False, deaf=False):
        if isinstance(vchannel, discord.Object):
            vchannel = self.get_channel(vchannel.id)

        if getattr(vchannel, 'type', ChannelType.text) != ChannelType.voice:
            raise AttributeError('渡されるチャンネルは音声チャンネルでなければなりません')

        await self.ws.voice_state(vchannel.guild.id, vchannel.id, mute, deaf)
        # I hope I don't have to set the channel here
        # instead of waiting for the event to update it

    def get_player_in(self, guild:discord.Guild) -> MusicPlayer:
        return self.players.get(guild.id)

    async def get_player(self, channel, create=False, *, deserialize=False) -> MusicPlayer:
        guild = channel.guild

        async with self.aiolocks[_func_() + ':' + str(guild.id)]:
            if deserialize:
                voice_client = await self.get_voice_client(channel)
                player = await self.deserialize_queue(guild, voice_client)

                if player:
                    log.debug("%sのエントリを持つギルド%sのデシリアライゼーションを介してプレイヤーを作成しました", len(player.playlist), guild.id)
                    # Since deserializing only happens when the bot starts, I should never need to reconnect
                    return self._init_player(player, guild=guild)

            if guild.id not in self.players:
                if not create:
                    raise exceptions.CommandError(
                        'ボットは音声チャンネルにありません。  '
                        'あなたの音声チャンネルにそれを召喚するために%ssummonを使用してください。' % self.config.command_prefix)

                voice_client = await self.get_voice_client(channel)

                playlist = Playlist(self)
                player = MusicPlayer(self, voice_client, playlist)
                self._init_player(player, guild=guild)

        return self.players[guild.id]

    def _init_player(self, player, *, guild=None):
        player = player.on('play', self.on_player_play) \
                       .on('resume', self.on_player_resume) \
                       .on('pause', self.on_player_pause) \
                       .on('stop', self.on_player_stop) \
                       .on('finished-playing', self.on_player_finished_playing) \
                       .on('entry-added', self.on_player_entry_added) \
                       .on('error', self.on_player_error)

        player.skip_state = SkipState()

        if guild:
            self.players[guild.id] = player

        return player

    async def on_player_play(self, player, entry):
        log.debug('on_player_playを実行する')
        await self.update_now_playing_status(entry)
        player.skip_state.reset()

        # This is the one event where its ok to serialize autoplaylist entries
        await self.serialize_queue(player.voice_client.channel.guild)

        if self.config.write_current_song:
            await self.write_current_song(player.voice_client.channel.guild, entry)

        channel = entry.meta.get('channel', None)
        author = entry.meta.get('author', None)

        if channel and author:
            last_np_msg = self.server_specific_data[channel.guild]['last_np_msg']
            if last_np_msg and last_np_msg.channel == channel:

                async for lmsg in channel.history(limit=1):
                    if lmsg != last_np_msg and last_np_msg:
                        await self.safe_delete_message(last_np_msg)
                        self.server_specific_data[channel.guild]['last_np_msg'] = None
                    break  # This is probably redundant

            author_perms = self.permissions.for_user(author)

            if author not in player.voice_client.channel.members and author_perms.skip_when_absent:
                newmsg = '次の`%s`にスキップする：`%s`がリクエストしました。 ' % (
                    player.voice_client.channel.name, entry.title, entry.meta['author'].name)
                player.skip()
            elif self.config.now_playing_mentions:
                newmsg = '%s  - あなたがリクエストした `%s`は現在`%s`で再生中です！' % (
                    entry.meta['author'].mention, entry.title, player.voice_client.channel.name)
            else:
                newmsg = '現在`%s`で再生中:`%s`は`%s`によって追加されました' % (
                    player.voice_client.channel.name, entry.title, entry.meta['author'].name)

            if self.server_specific_data[channel.guild]['last_np_msg']:
                self.server_specific_data[channel.guild]['last_np_msg'] = await self.safe_edit_message(last_np_msg, newmsg, send_if_fail=True)
            else:
                self.server_specific_data[channel.guild]['last_np_msg'] = await self.safe_send_message(channel, newmsg)

        # TODO: Check channel voice state?

    async def on_player_resume(self, player, entry, **_):
        log.debug('on_player_resumeを実行')
        await self.update_now_playing_status(entry)

    async def on_player_pause(self, player, entry, **_):
        log.debug('on_player_resumeを実行')
        await self.update_now_playing_status(entry, True)
        # await self.serialize_queue(player.voice_client.channel.guild)

    async def on_player_stop(self, player, **_):
        log.debug('on_player_stopを実行')
        await self.update_now_playing_status()

    async def on_player_finished_playing(self, player, **_):
        log.debug('on_player_finished_playingを実行')
        def _autopause(player):
            if self._check_if_empty(player.voice_client.channel):
                log.info("プレーヤーが再生を終了し、空のチャンネルで自動一時停止")

                player.pause()
                self.server_specific_data[player.voice_client.channel.guild]['auto_paused'] = True

        if not player.playlist.entries and not player.current_entry and self.config.auto_playlist:
            if not player.autoplaylist:
                if not self.autoplaylist:
                    # TODO: When I add playlist expansion, make sure that's not happening during this check
                    log.warning("自動再生リストに再生可能な曲がありません。無効にしています。")
                    self.config.auto_playlist = False
                else:
                    log.debug("現在の自動再生リストにコンテンツがありません。新しい音楽でいっぱい...")
                    player.autoplaylist = list(self.autoplaylist)

            while player.autoplaylist:
                if self.config.auto_playlist_random:
                    random.shuffle(player.autoplaylist)
                    song_url = random.choice(player.autoplaylist)
                else:
                    song_url = player.autoplaylist[0]
                player.autoplaylist.remove(song_url)

                info = {}

                try:
                    info = await self.downloader.extract_info(player.playlist.loop, song_url, download=False, process=False)
                except downloader.youtube_dl.utils.DownloadError as e:
                    if 'YouTube said:' in e.args[0]:
                        # url is bork, remove from list and put in removed list
                        log.error("YouTubeのURLの処理中にエラーが発生しました:\n{}".format(e.args[0]))

                    else:
                        # Probably an error from a different extractor, but I've only seen youtube's
                        log.error("\"{url}\"の処理中にエラーが発生しました {ex}".format(url=song_url, ex=e))

                    await self.remove_from_autoplaylist(song_url, ex=e, delete_from_ap=self.config.remove_ap)
                    continue

                except Exception as e:
                    log.error("\"{url}\"の処理中にエラーが発生しました:{ex}".format(url=song_url, ex=e))
                    log.exception()

                    self.autoplaylist.remove(song_url)
                    continue

                if info.get('entries', None):  # or .get('_type', '') == 'playlist'
                    log.debug("再生リストは見つかりましたが、現時点ではサポートされていません。スキップします。")
                    # TODO: Playlist expansion

                # Do I check the initial conditions again?
                # not (not player.playlist.entries and not player.current_entry and self.config.auto_playlist)

                if self.config.auto_pause:
                    player.once('play', lambda player, **_: _autopause(player))

                try:
                    await player.playlist.add_entry(song_url, channel=None, author=None)
                except exceptions.ExtractionError as e:
                    log.error("自動再生リストからの曲の追加中にエラーが発生しました: {}".format(e))
                    log.debug('', exc_info=True)
                    continue

                break

            if not self.autoplaylist:
                # TODO: When I add playlist expansion, make sure that's not happening during this check
                log.warning("自動再生リストに再生可能な曲がありません。無効にしています。")
                self.config.auto_playlist = False

        else: # Don't serialize for autoplaylist events
            await self.serialize_queue(player.voice_client.channel.guild)

        if not player.is_stopped and not player.is_dead:
            player.play(_continue=True)

    async def on_player_entry_added(self, player, playlist, entry, **_):
        log.debug('on_player_entry_added を実行')
        if entry.meta.get('author') and entry.meta.get('channel'):
            await self.serialize_queue(player.voice_client.channel.guild)

    async def on_player_error(self, player, entry, ex, **_):
        if 'channel' in entry.meta:
            await self.safe_send_message(
                entry.meta['channel'],
                "```\n FFmpegからのエラー:\n{}\n```".format(ex)
            )
        else:
            log.exception("プレイヤーエラー", exc_info=ex)

    async def update_now_playing_status(self, entry=None, is_paused=False):
        game = None

        if not self.config.status_message:
            if self.user.bot:
                activeplayers = sum(1 for p in self.players.values() if p.is_playing)
                if activeplayers > 1:
                    game = discord.Game(type=0, name="%sギルドの音楽" % activeplayers)
                    entry = None

                elif activeplayers == 1:
                    player = discord.utils.get(self.players.values(), is_playing=True)
                    entry = player.current_entry

            if entry:
                prefix = u'\u275A\u275A ' if is_paused else ''

                name = u'{}{}'.format(prefix, entry.title)[:128]
                game = discord.Game(type=0, name=name)
        else:
            game = discord.Game(type=0, name=self.config.status_message.strip()[:128])

        async with self.aiolocks[_func_()]:
            if game != self.last_status:
                await self.change_presence(activity=game)
                self.last_status = game

    async def update_now_playing_message(self, guild, message, *, channel=None):
        lnp = self.server_specific_data[guild]['last_np_msg']
        m = None

        if message is None and lnp:
            await self.safe_delete_message(lnp, quiet=True)

        elif lnp:  # If there was a previous lp message
            oldchannel = lnp.channel

            if lnp.channel == oldchannel:  # If we have a channel to update it in
                async for lmsg in lnp.channel.history(limit=1):
                    if lmsg != lnp and lnp:  # If we need to resend it
                        await self.safe_delete_message(lnp, quiet=True)
                        m = await self.safe_send_message(channel, message, quiet=True)
                    else:
                        m = await self.safe_edit_message(lnp, message, send_if_fail=True, quiet=False)

            elif channel: # If we have a new channel to send it to
                await self.safe_delete_message(lnp, quiet=True)
                m = await self.safe_send_message(channel, message, quiet=True)

            else:  # we just resend it in the old channel
                await self.safe_delete_message(lnp, quiet=True)
                m = await self.safe_send_message(oldchannel, message, quiet=True)

        elif channel: # No previous message
            m = await self.safe_send_message(channel, message, quiet=True)

        self.server_specific_data[guild]['last_np_msg'] = m


    async def serialize_queue(self, guild, *, dir=None):
        """
        Serialize the current queue for a server's player to json.
        """

        player = self.get_player_in(guild)
        if not player:
            return

        if dir is None:
            dir = 'data/%s/queue.json' % guild.id

        async with self.aiolocks['queue_serialization' + ':' + str(guild.id)]:
            log.debug("%sのキューを直列化しています", guild.id)

            with open(dir, 'w', encoding='utf8') as f:
                f.write(player.serialize(sort_keys=True))

    async def serialize_all_queues(self, *, dir=None):
        coros = [self.serialize_queue(s, dir=dir) for s in self.guilds]
        await asyncio.gather(*coros, return_exceptions=True)

    async def deserialize_queue(self, guild, voice_client, playlist=None, *, dir=None) -> MusicPlayer:
        """
        Deserialize a saved queue for a server into a MusicPlayer.  If no queue is saved, returns None.
        """

        if playlist is None:
            playlist = Playlist(self)

        if dir is None:
            dir = 'data/%s/queue.json' % guild.id

        async with self.aiolocks['queue_serialization' + ':' + str(guild.id)]:
            if not os.path.isfile(dir):
                return None

            log.debug("%sのキューを逆シリアル化します", guild.id)

            with open(dir, 'r', encoding='utf8') as f:
                data = f.read()

        return MusicPlayer.from_json(data, self, voice_client, playlist)

    async def write_current_song(self, guild, entry, *, dir=None):
        """
        Writes the current song to file
        """
        player = self.get_player_in(guild)
        if not player:
            return

        if dir is None:
            dir = 'data/%s/current.txt' % guild.id

        async with self.aiolocks['current_song' + ':' + str(guild.id)]:
            log.debug("現在の曲を%sに書き込んでいます", guild.id)

            with open(dir, 'w', encoding='utf8') as f:
                f.write(entry.title)

    @ensure_appinfo
    async def _on_ready_sanity_checks(self):
        # Ensure folders exist
        await self._scheck_ensure_env()

        # Server permissions check
        await self._scheck_server_permissions()

        # playlists in autoplaylist
        await self._scheck_autoplaylist()

        # config/permissions async validate?
        await self._scheck_configs()


    async def _scheck_ensure_env(self):
        log.debug("dataフォルダを確認します。")
        for guild in self.guilds:
            pathlib.Path('data/%s/' % guild.id).mkdir(exist_ok=True)

        with open('data/server_names.txt', 'w', encoding='utf8') as f:
            for guild in sorted(self.guilds, key=lambda s:int(s.id)):
                f.write('{:<22} {}\n'.format(guild.id, guild.name))

        if not self.config.save_videos and os.path.isdir(AUDIO_CACHE_PATH):
            if self._delete_old_audiocache():
                log.debug("古いオーディオキャッシュを削除しました")
            else:
                log.debug("古いオーディオキャッシュを削除できませんでした。")


    async def _scheck_server_permissions(self):
        log.debug("サーバーの権限を確認する")
        pass # TODO

    async def _scheck_autoplaylist(self):
        log.debug("自動再生リストの監査")
        pass # TODO

    async def _scheck_configs(self):
        log.debug("設定の検証")
        await self.config.async_validate(self)

        log.debug("パーミッション設定の検証")
        await self.permissions.async_validate(self)



#######################################################################################################################


    async def safe_send_message(self, dest, content, **kwargs):
        tts = kwargs.pop('tts', False)
        quiet = kwargs.pop('quiet', False)
        expire_in = kwargs.pop('expire_in', 0)
        allow_none = kwargs.pop('allow_none', True)
        also_delete = kwargs.pop('also_delete', None)

        msg = None
        lfunc = log.debug if quiet else log.warning

        try:
            if content is not None or allow_none:
                if isinstance(content, discord.Embed):
                    msg = await dest.send(embed=content)
                else:
                    msg = await dest.send(content, tts=tts)

        except discord.Forbidden:
            lfunc("メッセージを\"%s\"に送信できません、権限がありません", dest.name)

        except discord.NotFound:
            lfunc("無効なチャンネル、\"%s\"にメッセージを送信できませんか？", dest.name)

        except discord.HTTPException:
            if len(content) > DISCORD_MSG_CHAR_LIMIT:
                lfunc("メッセージがメッセージサイズ制限(%s)を超えています", DISCORD_MSG_CHAR_LIMIT)
            else:
                lfunc("メッセージを送信できませんでした")
                log.noise("HTTPExceptionがメッセージを%sに送信しようとしました:%s", dest, content)

        finally:
            if msg and expire_in:
                asyncio.ensure_future(self._wait_delete_msg(msg, expire_in))

            if also_delete and isinstance(also_delete, discord.Message):
                asyncio.ensure_future(self._wait_delete_msg(also_delete, expire_in))

        return msg

    async def safe_delete_message(self, message, *, quiet=False):
        lfunc = log.debug if quiet else log.warning

        try:
            return await message.delete()

        except discord.Forbidden:
            lfunc("メッセージ\"{}\"を削除できません、権限がありません".format(message.clean_content))

        except discord.NotFound:
            lfunc("メッセージ\"{}\"を削除できません。メッセージが見つかりません".format(message.clean_content))

    async def safe_edit_message(self, message, new, *, send_if_fail=False, quiet=False):
        lfunc = log.debug if quiet else log.warning

        try:
            return await message.edit(content=new)

        except discord.NotFound:
            lfunc("メッセージ\"{}\"を編集できません。メッセージが見つかりません".format(message.clean_content))
            if send_if_fail:
                lfunc("代わりにメッセージを送信する")
                return await self.safe_send_message(message.channel, new)

    async def send_typing(self, destination):
        try:
            return await destination.trigger_typing()
        except discord.Forbidden:
            log.warning("{}に入力を送信できませんでした。権限がありません".format(destination))

    async def restart(self):
        self.exit_signal = exceptions.RestartSignal()
        await self.logout()

    def restart_threadsafe(self):
        asyncio.run_coroutine_threadsafe(self.restart(), self.loop)

    def _cleanup(self):
        try:
            self.loop.run_until_complete(self.logout())
            self.loop.run_until_complete(self.aiosession.close())
        except: pass

        pending = asyncio.Task.all_tasks()
        gathered = asyncio.gather(*pending)

        try:
            gathered.cancel()
            self.loop.run_until_complete(gathered)
            gathered.exception()
        except: pass

    # noinspection PyMethodOverriding
    def run(self):
        try:
            self.loop.run_until_complete(self.start(*self.config.auth))

        except discord.errors.LoginFailure:
            # Add if token, else
            raise exceptions.HelpfulError(
                "ボットはログインできません、不適切な資格情報。",
                "オプションファイルでトークンを修正してください。  "
                "各フィールドはそれぞれ独自の行になければなりません。"
            )  #     ^^^^ In theory self.config.auth should never have no items

        finally:
            try:
                self._cleanup()
            except Exception:
                log.error("クリーンアップエラー", exc_info=True)

            if self.exit_signal:
                raise self.exit_signal # pylint: disable=E0702

    async def logout(self):
        await self.disconnect_all_voice_clients()
        return await super().logout()

    async def on_error(self, event, *args, **kwargs):
        ex_type, ex, stack = sys.exc_info()

        if ex_type == exceptions.HelpfulError:
            log.error("{}の例外:\n{}".format(event, ex.message))

            await asyncio.sleep(2)  # don't ask
            await self.logout()

        elif issubclass(ex_type, exceptions.Signal):
            self.exit_signal = ex_type
            await self.logout()

        else:
            log.error("{}の例外".format(event), exc_info=True)

    async def on_resumed(self):
        log.info("\nDiscordに再接続しました。\n")

    async def on_ready(self):
        dlogger = logging.getLogger('discord')
        for h in dlogger.handlers:
            if getattr(h, 'terminator', None) == '':
                dlogger.removeHandler(h)
                print()

        log.debug("接続が確立されました。")

        self.ws._keep_alive.name = 'Gateway Keepalive'

        if self.init_ok:
            log.debug("追加のREADYイベントを受信しました。再開に失敗した可能性があります")
            return

        await self._on_ready_sanity_checks()

        self.init_ok = True

        ################################

        log.info("接続済み:{0}/{1}#{2}".format(
            self.user.id,
            self.user.name,
            self.user.discriminator
        ))

        owner = self._get_owner(voice=True) or self._get_owner()
        if owner and self.guilds:
            log.info("オーナー:{0}/{1}#{2}\n".format(
                owner.id,
                owner.name,
                owner.discriminator
            ))

            log.info('ギルドリスト:')
            unavailable_servers = 0
            for s in self.guilds:
                ser = ('{} (unavailable)'.format(s.name) if s.unavailable else s.name)
                log.info(' - ' + ser)
                if self.config.leavenonowners:
                    if s.unavailable:
                        unavailable_servers += 1
                    else:
                        check = s.get_member(owner.id)
                        if check == None:
                            await s.leave()
                            log.info('ボットの所有者が見つからない{}'.format(s.name))
            if unavailable_servers != 0:
                log.info('利用できないため、{}サーバーでチェックを進めていません'.format(str(unavailable_servers))) 

        elif self.guilds:
            log.warning("所有者はどのギルドにも見つかりませんでした(id:%s)\n" % self.config.owner_id)

            log.info('ギルドリスト:')
            for s in self.guilds:
                ser = ('{} (unavailable)'.format(s.name) if s.unavailable else s.name)
                log.info(' - ' + ser)

        else:
            log.warning("オーナー不明、ボットはギルドに入っていません。")
            if self.user.bot:
                log.warning(
                    "ボットをギルドに参加させるには、このリンクをブラウザに貼り付けてください。\n"
                    "注意：あなたはあなたのメインアカウントにログインしていなければなりません。 \n"
                    "ボットに参加させたいギルドのサーバー権限を管理します。\n"
                    "  " + await self.generate_invite_link()
                )

        print(flush=True)

        if self.config.bound_channels:
            chlist = set(self.get_channel(i) for i in self.config.bound_channels if i)
            chlist.discard(None)

            invalids = set()
            invalids.update(c for c in chlist if isinstance(c, discord.VoiceChannel))

            chlist.difference_update(invalids)
            self.config.bound_channels.difference_update(invalids)

            if chlist:
                log.info("テキストチャンネルにバインド：")
                [log.info(' - {}/{}'.format(ch.guild.name.strip(), ch.name.strip())) for ch in chlist if ch]
            else:
                print("どのテキストチャンネルにもバインドされていません")

            if invalids and self.config.debug_mode:
                print(flush=True)
                log.info("音声チャネルにバインドしない:")
                [log.info(' - {}/{}'.format(ch.guild.name.strip(), ch.name.strip())) for ch in invalids if ch]

            print(flush=True)

        else:
            log.info("どのテキストチャンネルにもバインドされていません")

        if self.config.autojoin_channels:
            chlist = set(self.get_channel(i) for i in self.config.autojoin_channels if i)
            chlist.discard(None)

            invalids = set()
            invalids.update(c for c in chlist if isinstance(c, discord.TextChannel))

            chlist.difference_update(invalids)
            self.config.autojoin_channels.difference_update(invalids)

            if chlist:
                log.info("自動参加音声チャンネル:")
                [log.info(' - {}/{}'.format(ch.guild.name.strip(), ch.name.strip())) for ch in chlist if ch]
            else:
                log.info("どの音声チャンネルにも自動参加しない")

            if invalids and self.config.debug_mode:
                print(flush=True)
                log.info("テキストチャンネルに自動参加できません。")
                [log.info(' - {}/{}'.format(ch.guild.name.strip(), ch.name.strip())) for ch in invalids if ch]

            self.autojoin_channels = chlist

        else:
            log.info("どの音声チャンネルにも自動参加しない")
            self.autojoin_channels = set()
        
        if self.config.show_config_at_start:
            print(flush=True)
            log.info("オプション:")

            log.info("  コマンドプレフィックス: " + self.config.command_prefix)
            log.info("  デフォルトのボリューム: {}%".format(int(self.config.default_volume * 100)))
            log.info("  しきい値をスキップ：{}票または{}%".format(
                self.config.skips_required, fixg(self.config.skip_ratio_required * 100)))
            log.info("  Now Playing @mentions: " + ['Disabled', 'Enabled'][self.config.now_playing_mentions])
            log.info("  Auto-Summon: " + ['Disabled', 'Enabled'][self.config.auto_summon])
            log.info("  Auto-Playlist: " + ['Disabled', 'Enabled'][self.config.auto_playlist] + " (order: " + ['sequential', 'random'][self.config.auto_playlist_random] + ")")
            log.info("  Auto-Pause: " + ['Disabled', 'Enabled'][self.config.auto_pause])
            log.info("  Delete Messages: " + ['Disabled', 'Enabled'][self.config.delete_messages])
            if self.config.delete_messages:
                log.info("    Delete Invoking: " + ['Disabled', 'Enabled'][self.config.delete_invoking])
            log.info("  Debug Mode: " + ['Disabled', 'Enabled'][self.config.debug_mode])
            log.info("  Downloaded songs will be " + ['deleted', 'saved'][self.config.save_videos])
            if self.config.status_message:
                log.info("  Status message: " + self.config.status_message)
            log.info("  Write current songs to file: " + ['Disabled', 'Enabled'][self.config.write_current_song])
            log.info("  Author insta-skip: " + ['Disabled', 'Enabled'][self.config.allow_author_skip])
            log.info("  Embeds: " + ['Disabled', 'Enabled'][self.config.embeds])
            log.info("  Spotify integration: " + ['Disabled', 'Enabled'][self.config._spotify])
            log.info("  Legacy skip: " + ['Disabled', 'Enabled'][self.config.legacy_skip])
            log.info("  Leave non owners: " + ['Disabled', 'Enabled'][self.config.leavenonowners])

        print(flush=True)

        await self.update_now_playing_status()

        # maybe option to leave the ownerid blank and generate a random command for the owner to use
        # wait_for_message is pretty neato

        await self._join_startup_channels(self.autojoin_channels, autosummon=self.config.auto_summon)

        # we do this after the config stuff because it's a lot easier to notice here
        if self.config.missing_keys:
            log.warning('設定にいくつかのオプションがありません。最近更新した場合は'
                        'example_options.iniファイルを調べて新しいオプションがあるかどうか確認してください'
                        '不足しているオプション: {0}'.format(self.config.missing_keys))
            print(flush=True)

        # t-t-th-th-that's all folks!

    def _gen_embed(self):
        """Provides a basic template for embeds"""
        e = discord.Embed()
        e.colour = 7506394
        e.set_footer(text='Cosgy-Dev/MusicBot ({})'.format(BOTVERSION), icon_url='https://www.cosgy.jp/wp-content/uploads/2019/03/06542A4E-BEA6-44D7-BDFD-E65BE9225210.jpeg')
        e.set_author(name=self.user.name, url='https://github.com/Cosgy-Dev/MusicBot', icon_url=self.user.avatar_url)
        return e

    async def cmd_resetplaylist(self, player, channel):
        """
        使用方法:
            {command_prefix}resetplaylist

        サーバーの自動再生リストをリセットします。
        """
        player.autoplaylist = list(set(self.autoplaylist))
        return Response(self.str.get('cmd-resetplaylist-response', '\N{OK HAND SIGN}'), delete_after=15)

    async def cmd_help(self, message, channel, command=None):
        """
        使用方法:
            {command_prefix}help [command]

        ヘルプメッセージを送信します。
        コマンドが指定されている場合は、そのコマンドのヘルプメッセージを表示します。
        それ以外の場合は、利用可能なコマンドが一覧表示されます。
        """
        self.commands = []
        self.is_all = False
        prefix = self.config.command_prefix

        if command:
            if command.lower() == 'all':
                self.is_all = True
                await self.gen_cmd_list(message, list_all_cmds=True)

            else:
                cmd = getattr(self, 'cmd_' + command, None)
                if cmd and not hasattr(cmd, 'dev_cmd'):
                    return Response(
                        "```\n{}```".format(
                            dedent(cmd.__doc__)
                        ).format(command_prefix=self.config.command_prefix),
                        delete_after=60
                    )
                else:
                    raise exceptions.CommandError(self.str.get('cmd-help-invalid', "そのようなコマンドはありません"), expire_in=10)

        elif message.author.id == self.config.owner_id:
            await self.gen_cmd_list(message, list_all_cmds=True)

        else:
            await self.gen_cmd_list(message)

        desc = '```\n' + ', '.join(self.commands) + '\n```\n' + self.str.get(
            'cmd-help-response', '特定のコマンドについては、 `{}help [command]`を実行してください。\n'
                                 '詳細については、https://Cosgy-Dev.github.io/MusicBot/を参照してください。').format(prefix)
        if not self.is_all:
            desc += self.str.get('cmd-help-all', '\n使用できるコマンドのみを表示します。全コマンドの一覧を見るには、 `{}help all`を実行してください。').format(prefix)

        return Response(desc, reply=True, delete_after=60)

    async def cmd_blacklist(self, message, user_mentions, option, something):
        """
        使用法:
            {command_prefix}blacklist [ + | - | add | remove ] @UserName [@UserName2 ...]

        ブラックリストにユーザーを追加または削除します。
        ブラックリストに登録されているユーザーは、ボットコマンドを使用することが禁止されています。
        """

        if not user_mentions:
            raise exceptions.CommandError("ユーザーが表示されていません。", expire_in=20)

        if option not in ['+', '-', 'add', 'remove']:
            raise exceptions.CommandError(
                self.str.get('cmd-blacklist-invalid', '無効なオプション "{0}"が指定されています。+、 - 、add、またはremoveを使用してください').format(option), expire_in=20
            )

        for user in user_mentions.copy():
            if user.id == self.config.owner_id:
                print("[Commands:Blacklist] 所有者をブラックリストに登録することはできません。")
                user_mentions.remove(user)

        old_len = len(self.blacklist)

        if option in ['+', 'add']:
            self.blacklist.update(user.id for user in user_mentions)

            write_file(self.config.blacklist_file, self.blacklist)

            return Response(
                self.str.get('cmd-blacklist-added', '{0}人のユーザーがブラックリストに追加されました').format(len(self.blacklist) - old_len),
                reply=True, delete_after=10
            )

        else:
            if self.blacklist.isdisjoint(user.id for user in user_mentions):
                return Response(self.str.get('cmd-blacklist-none', 'それらのユーザーのどれもブラックリストにありません。'), reply=True, delete_after=10)

            else:
                self.blacklist.difference_update(user.id for user in user_mentions)
                write_file(self.config.blacklist_file, self.blacklist)

                return Response(
                    self.str.get('cmd-blacklist-removed', '{0}人のユーザーがブラックリストから削除されました').format(old_len - len(self.blacklist)),
                    reply=True, delete_after=10
                )

    async def cmd_id(self, author, user_mentions):
        """
        使用法:
            {command_prefix}id [@user]

        自分のIDまたは別のユーザーのIDをユーザーに伝えます。
        """
        if not user_mentions:
            return Response(self.str.get('cmd-id-self', 'あなたのIDは `{0}`です').format(author.id), reply=True, delete_after=35)
        else:
            usr = user_mentions[0]
            return Response(self.str.get('cmd-id-other', '**{0}**s ID is `{1}`').format(usr.name, usr.id), reply=True, delete_after=35)

    async def cmd_save(self, player, url=None):
        """
        使用法:
            {command_prefix}save [url]

        指定した曲、または指定していない場合は現在の曲をオートプレイリストに保存します。
        """
        if url or (player.current_entry and not isinstance(player.current_entry, StreamPlaylistEntry)):
            if not url:
                url = player.current_entry.url

            if url not in self.autoplaylist:
                self.autoplaylist.append(url)
                write_file(self.config.auto_playlist_file, self.autoplaylist)
                log.debug("自動再生リストに{}を追加しました".format(url))
                return Response(self.str.get('cmd-save-success', '自動再生リストに<{0}>を追加しました。').format(url))
            else:
                raise exceptions.CommandError(self.str.get('cmd-save-exists', 'この曲はすでにオートプレイリストに登録されています。'))
        else:
            raise exceptions.CommandError(self.str.get('cmd-save-invalid', '有効な曲が再生されていません。'))

    @owner_only
    async def cmd_joinserver(self, message, server_link=None):
        """
        使用法:
            {command_prefix}joinserver invite_link

        ボットにサーバーへの参加を依頼します。注：ボットアカウントは招待リンクを使用できません。
        """

        url = await self.generate_invite_link()
        return Response(
            self.str.get('cmd-joinserver-response', "ボットを追加するにはこのURLをクリックしてください: \n{}").format(url),
            reply=True, delete_after=30
        )

    async def cmd_karaoke(self, player, channel, author):
        """
        使用法:
            {command_prefix}karaoke

        カラオケモードを有効にします。カラオケモード中は、BypassKaraokeModeを持つグループのみ
        設定ファイルの許可は音楽をキューに入れることができます。
        """
        player.karaoke_mode = not player.karaoke_mode
        return Response("\N{OK HAND SIGN} カラオケモードは現在" + ['無効', '有効'][player.karaoke_mode], delete_after=15)

    async def _do_playlist_checks(self, permissions, player, author, testobj):
        num_songs = sum(1 for _ in testobj)

        # I have to do exe extra checks anyways because you can request an arbitrary number of search results
        if not permissions.allow_playlists and num_songs > 1:
            raise exceptions.PermissionsError(self.str.get('playlists-noperms', "再生リストをリクエストすることは許可されていません"), expire_in=30)

        if permissions.max_playlist_length and num_songs > permissions.max_playlist_length:
            raise exceptions.PermissionsError(
                self.str.get('playlists-big', "再生リストに含まれるエントリが多すぎます({0}> {1})").format(num_songs, permissions.max_playlist_length),
                expire_in=30
            )

        # This is a little bit weird when it says (x + 0 > y), I might add the other check back in
        if permissions.max_songs and player.playlist.count_for_user(author) + num_songs > permissions.max_songs:
            raise exceptions.PermissionsError(
                self.str.get('playlists-limit', "プレイリストのエントリ数+既にキューに入っている曲が上限に達しました({0}+{1}>{2})").format(
                    num_songs, player.playlist.count_for_user(author), permissions.max_songs),
                expire_in=30
            )
        return True

    async def cmd_play(self, message, player, channel, author, permissions, leftover_args, song_url):
        """
        使用法:
            {command_prefix}play song_link
            {command_prefix}play text to search for
            {command_prefix}play spotify_uri

        プレイリストに曲を追加します。リンクが提供されていない場合は、最初の
        YouTube検索の結果がキューに追加されます。

        設定で有効にした場合、ボットはSpotify URIもサポートします、しかし
        YouTubeを見つけるためにメタデータ（例えば曲名やアーティスト）を使います。
        歌と同じです。 Spotifyからストリーミングすることはできません。
        """

        song_url = song_url.strip('<>')

        await self.send_typing(channel)

        if leftover_args:
            song_url = ' '.join([song_url, *leftover_args])
        leftover_args = None  # prevent some crazy shit happening down the line

        # Make sure forward slashes work properly in search queries
        linksRegex = '((http(s)*:[/][/]|www.)([a-z]|[A-Z]|[0-9]|[/.]|[~])*)'
        pattern = re.compile(linksRegex)
        matchUrl = pattern.match(song_url)
        song_url = song_url.replace('/', '%2F') if matchUrl is None else song_url

        # Rewrite YouTube playlist URLs if the wrong URL type is given
        playlistRegex = r'watch\?v=.+&(list=[^&]+)'
        matches = re.search(playlistRegex, song_url)
        groups = matches.groups() if matches is not None else []
        song_url = "https://www.youtube.com/playlist?" + groups[0] if len(groups) > 0 else song_url

        if self.config._spotify:
            if 'open.spotify.com' in song_url:
                song_url = 'spotify:' + re.sub('(http[s]?:\/\/)?(open.spotify.com)\/', '', song_url).replace('/', ':')
            if song_url.startswith('spotify:'):
                parts = song_url.split(":")
                try:
                    if 'track' in parts:
                        res = await self.spotify.get_track(parts[-1])
                        song_url = res['artists'][0]['name'] + ' ' + res['name'] 

                    elif 'album' in parts:
                        res = await self.spotify.get_album(parts[-1])
                        await self._do_playlist_checks(permissions, player, author, res['tracks']['items'])
                        procmesg = await self.safe_send_message(channel, self.str.get('cmd-play-spotify-album-process', 'アルバム `{0}` (`{1}`)を処理中です。').format(res['name'], song_url))
                        for i in res['tracks']['items']:
                            song_url = i['name'] + ' ' + i['artists'][0]['name']
                            log.debug('Processing {0}'.format(song_url))
                            await self.cmd_play(message, player, channel, author, permissions, leftover_args, song_url)
                        await self.safe_delete_message(procmesg)
                        return Response(self.str.get('cmd-play-spotify-album-queued', "**{1}**曲で `{0}`をエンキューしました。").format(res['name'], len(res['tracks']['items'])))
                    
                    elif 'playlist' in parts:
                        res = []
                        r = await self.spotify.get_playlist_tracks(parts[-1])
                        while True:
                            res.extend(r['items'])
                            if r['next'] is not None:
                                r = await self.spotify.make_spotify_req(r['next'])
                                continue
                            else:
                                break
                        await self._do_playlist_checks(permissions, player, author, res)
                        procmesg = await self.safe_send_message(channel, self.str.get('cmd-play-spotify-playlist-process', '処理プレイリスト `{0}`(`{1}`)').format(parts[-1], song_url))
                        for i in res:
                            song_url = i['track']['name'] + ' ' + i['track']['artists'][0]['name']
                            log.debug('処理{0}'.format(song_url))
                            await self.cmd_play(message, player, channel, author, permissions, leftover_args, song_url)
                        await self.safe_delete_message(procmesg)
                        return Response(self.str.get('cmd-play-spotify-playlist-queued', "**{1}**曲で`{0}`をエンキューしました。").format(parts[-1], len(res)))
                    
                    else:
                        raise exceptions.CommandError(self.str.get('cmd-play-spotify-unsupported', 'これはサポートされているSpotify URIではありません。'), expire_in=30)
                except exceptions.SpotifyError:
                    raise exceptions.CommandError(self.str.get('cmd-play-spotify-invalid', '無効なURIを指定したか、問題がありました。'))

        async with self.aiolocks[_func_() + ':' + str(author.id)]:
            if permissions.max_songs and player.playlist.count_for_user(author) >= permissions.max_songs:
                raise exceptions.PermissionsError(
                    self.str.get('cmd-play-limit', "あなたはキューに入っている曲の上限に達しました({0})").format(permissions.max_songs), expire_in=30
                )

            if player.karaoke_mode and not permissions.bypass_karaoke_mode:
                raise exceptions.PermissionsError(
                    self.str.get('karaoke-enabled', "カラオケモードが有効になっています。無効になってからもう一度お試しください。"), expire_in=30
                )

            try:
                info = await self.downloader.extract_info(player.playlist.loop, song_url, download=False, process=False)
            except Exception as e:
                if 'unknown url type' in str(e):
                    song_url = song_url.replace(':', '')  # it's probably not actually an extractor
                    info = await self.downloader.extract_info(player.playlist.loop, song_url, download=False, process=False)
                else:
                    raise exceptions.CommandError(e, expire_in=30)

            if not info:
                raise exceptions.CommandError(
                    self.str.get('cmd-play-noinfo', "そのビデオは再生できません。 {0}streamコマンドを使用してみてください。").format(self.config.command_prefix),
                    expire_in=30
                )

            log.debug(info)

            if info.get('extractor', '') not in permissions.extractors and permissions.extractors:
                raise exceptions.PermissionsError(
                    self.str.get('cmd-play-badextractor', "このサービスからメディアを再生する権限がありません。"), expire_in=30
                )

            # abstract the search handling away from the user
            # our ytdl options allow us to use search strings as input urls
            if info.get('url', '').startswith('ytsearch'):
                # print("[Command:play] Searching for \"%s\"" % song_url)
                info = await self.downloader.extract_info(
                    player.playlist.loop,
                    song_url,
                    download=False,
                    process=True,    # ASYNC LAMBDAS WHEN
                    on_error=lambda e: asyncio.ensure_future(
                        self.safe_send_message(channel, "```\n%s\n```" % e, expire_in=120), loop=self.loop),
                    retry_on_error=True
                )

                if not info:
                    raise exceptions.CommandError(
                        self.str.get('cmd-play-nodata', "検索文字列から情報を抽出中にエラーが発生しました。youtubedlはデータを返しませんでした。"
                                                        "それでも解決しない場合は、ボットを再起動する必要があります。"), expire_in=30
                    )

                if not all(info.get('entries', [])):
                    # empty list, no data
                    log.debug("空のリストになった、データなし")
                    return

                # TODO: handle 'webpage_url' being 'ytsearch:...' or extractor type
                song_url = info['entries'][0]['webpage_url']
                info = await self.downloader.extract_info(player.playlist.loop, song_url, download=False, process=False)
                # Now I could just do: return await self.cmd_play(player, channel, author, song_url)
                # But this is probably fine

            # TODO: Possibly add another check here to see about things like the bandcamp issue
            # TODO: Where ytdl gets the generic extractor version with no processing, but finds two different urls

            if 'entries' in info:
                await self._do_playlist_checks(permissions, player, author, info['entries'])

                num_songs = sum(1 for _ in info['entries'])

                if info['extractor'].lower() in ['youtube:playlist', 'soundcloud:set', 'bandcamp:album']:
                    try:
                        return await self._cmd_play_playlist_async(player, channel, author, permissions, song_url, info['extractor'])
                    except exceptions.CommandError:
                        raise
                    except Exception as e:
                        log.error("再生リストのキューイングエラー", exc_info=True)
                        raise exceptions.CommandError(self.str.get('cmd-play-playlist-error', "再生リストのキューイングエラー:\n`{0}`").format(e), expire_in=30)

                t0 = time.time()

                # My test was 1.2 seconds per song, but we maybe should fudge it a bit, unless we can
                # monitor it and edit the message with the estimated time, but that's some ADVANCED SHIT
                # I don't think we can hook into it anyways, so this will have to do.
                # It would probably be a thread to check a few playlists and get the speed from that
                # Different playlists might download at different speeds though
                wait_per_song = 1.2

                procmesg = await self.safe_send_message(
                    channel,
                    self.str.get('cmd-play-playlist-gathering-1', '{0}曲{1}のプレイリスト情報を収集しています').format(
                        num_songs,
                        self.str.get('cmd-play-playlist-gathering-2', ', ETA: {0} seconds').format(fixg(
                            num_songs * wait_per_song)) if num_songs >= 10 else '.'))

                # We don't have a pretty way of doing this yet.  We need either a loop
                # that sends these every 10 seconds or a nice context manager.
                await self.send_typing(channel)

                # TODO: I can create an event emitter object instead, add event functions, and every play list might be asyncified
                #       Also have a "verify_entry" hook with the entry as an arg and returns the entry if its ok

                entry_list, position = await player.playlist.import_from(song_url, channel=channel, author=author)

                tnow = time.time()
                ttime = tnow - t0
                listlen = len(entry_list)
                drop_count = 0

                if permissions.max_song_length:
                    for e in entry_list.copy():
                        if e.duration > permissions.max_song_length:
                            player.playlist.entries.remove(e)
                            entry_list.remove(e)
                            drop_count += 1
                            # Im pretty sure there's no situation where this would ever break
                            # Unless the first entry starts being played, which would make this a race condition
                    if drop_count:
                        print("%s曲を削除しました" % drop_count)

                log.info("{:.2f} /ソング、{:+.2g} /ソング({}s)で{}秒以内に{}曲を処理しました".format(
                    listlen,
                    fixg(ttime),
                    ttime / listlen if listlen else 0,
                    ttime / listlen - wait_per_song if listlen - wait_per_song else 0,
                    fixg(wait_per_song * num_songs))
                )

                await self.safe_delete_message(procmesg)

                if not listlen - drop_count:
                    raise exceptions.CommandError(
                        self.str.get('cmd-play-playlist-maxduration', "曲が追加されていない、すべての曲が最大期間(%ss)を超えています") % permissions.max_song_length,
                        expire_in=30
                    )

                reply_text = self.str.get('cmd-play-playlist-reply', "再生する** %s**曲をキューに入れました。キュー内の位置:%s")
                btext = str(listlen - drop_count)

            else:
                if info.get('extractor', '').startswith('youtube:playlist'):
                    try:
                        info = await self.downloader.extract_info(player.playlist.loop, 'https://www.youtube.com/watch?v=%s' % info.get('url', ''), download=False, process=False)
                    except Exception as e:
                        raise exceptions.CommandError(e, expire_in=30)

                if permissions.max_song_length and info.get('duration', 0) > permissions.max_song_length:
                    raise exceptions.PermissionsError(
                        self.str.get('cmd-play-song-limit', "曲の長さが制限を超えています({0}> {1})").format(info['duration'], permissions.max_song_length),
                        expire_in=30
                    )

                try:
                    entry, position = await player.playlist.add_entry(song_url, channel=channel, author=author)

                except exceptions.WrongEntryTypeError as e:
                    if e.use_url == song_url:
                        log.warning("誤ったエントリタイプを特定しましたが、提案されたURLは同じです。助けて。")

                    log.debug("url\"%s\"は単一のエントリであり、実際は再生リストであると想定されています" % song_url)
                    log.debug("代わりに\"%s\"を使用してください" % e.use_url)

                    return await self.cmd_play(player, channel, author, permissions, leftover_args, e.use_url)

                reply_text = self.str.get('cmd-play-song-reply', "再生するために`%s`をエンキューしました。キュー内の位置:%s")
                btext = entry.title


            if position == 1 and player.is_stopped:
                position = self.str.get('cmd-play-next', '次!')
                reply_text %= (btext, position)

            else:
                try:
                    time_until = await player.playlist.estimate_time_until(position, player)
                    reply_text += self.str.get('cmd-play-eta', ' - 再生までの推定時間: %s')
                except:
                    traceback.print_exc()
                    time_until = ''

                reply_text %= (btext, position, ftimedelta(time_until))

        return Response(reply_text, delete_after=30)

    async def _cmd_play_playlist_async(self, player, channel, author, permissions, playlist_url, extractor_type):
        """
        Secret handler to use the async wizardry to make playlist queuing non-"blocking"
        """

        await self.send_typing(channel)
        info = await self.downloader.extract_info(player.playlist.loop, playlist_url, download=False, process=False)

        if not info:
            raise exceptions.CommandError(self.str.get('cmd-play-playlist-invalid', "そのプレイリストは再生できません。"))

        num_songs = sum(1 for _ in info['entries'])
        t0 = time.time()

        busymsg = await self.safe_send_message(
            channel, self.str.get('cmd-play-playlist-process', "{0}曲を処理しています...").format(num_songs))  # TODO: From playlist_title
        await self.send_typing(channel)

        entries_added = 0
        if extractor_type == 'youtube:playlist':
            try:
                entries_added = await player.playlist.async_process_youtube_playlist(
                    playlist_url, channel=channel, author=author)
                # TODO: Add hook to be called after each song
                # TODO: Add permissions

            except Exception:
                log.error("再生リストの処理中にエラーが発生しました", exc_info=True)
                raise exceptions.CommandError(self.str.get('cmd-play-playlist-queueerror', '再生リスト{0}のキュー処理中にエラーが発生しました。').format(playlist_url), expire_in=30)

        elif extractor_type.lower() in ['soundcloud:set', 'bandcamp:album']:
            try:
                entries_added = await player.playlist.async_process_sc_bc_playlist(
                    playlist_url, channel=channel, author=author)
                # TODO: Add hook to be called after each song
                # TODO: Add permissions

            except Exception:
                log.error("再生リストの処理中にエラーが発生しました", exc_info=True)
                raise exceptions.CommandError(self.str.get('cmd-play-playlist-queueerror', '再生リスト{0}のキュー処理中にエラーが発生しました。').format(playlist_url), expire_in=30)


        songs_processed = len(entries_added)
        drop_count = 0
        skipped = False

        if permissions.max_song_length:
            for e in entries_added.copy():
                if e.duration > permissions.max_song_length:
                    try:
                        player.playlist.entries.remove(e)
                        entries_added.remove(e)
                        drop_count += 1
                    except:
                        pass

            if drop_count:
                log.debug("%s曲を削除しました" % drop_count)

            if player.current_entry and player.current_entry.duration > permissions.max_song_length:
                await self.safe_delete_message(self.server_specific_data[channel.guild]['last_np_msg'])
                self.server_specific_data[channel.guild]['last_np_msg'] = None
                skipped = True
                player.skip()
                entries_added.pop()

        await self.safe_delete_message(busymsg)

        songs_added = len(entries_added)
        tnow = time.time()
        ttime = tnow - t0
        wait_per_song = 1.2
        # TODO: actually calculate wait per song in the process function and return that too

        # This is technically inaccurate since bad songs are ignored but still take up time
        # ここの翻訳はよくわからん
        log.info("Processed {}/{} songs in {} seconds at {:.2f}s/song, {:+.2g}/song from expected ({}s)".format(
            songs_processed,
            num_songs,
            fixg(ttime),
            ttime / num_songs if num_songs else 0,
            ttime / num_songs - wait_per_song if num_songs - wait_per_song else 0,
            fixg(wait_per_song * num_songs))
        )

        if not songs_added:
            basetext = self.str.get('cmd-play-playlist-maxduration', "曲が追加されていない、すべての曲が最大期間(%ss)を超えています") % permissions.max_song_length
            if skipped:
                basetext += self.str.get('cmd-play-playlist-skipped', "\nさらに、現在の曲は長すぎるためスキップされました。")

            raise exceptions.CommandError(basetext, expire_in=30)

        return Response(self.str.get('cmd-play-playlist-reply-secs', "{0}曲が{1}秒で再生されました").format(
            songs_added, fixg(ttime, 1)), delete_after=30)

    async def cmd_stream(self, player, channel, author, permissions, song_url):
        """
        使用法:
            {command_prefix}stream song_link

        メディアストリームをエンキューします。
        これは、Twitchやshoutcastなどの実際のストリーム、あるいは単にストリーミングを意味する可能性があります。
        それをプレダウンロードせずにメディア。注:FFmpegは、処理が苦手なことで有名です。
        特に貧弱な接続でのストリーム。あなたは警告されました。
        """

        song_url = song_url.strip('<>')

        if permissions.max_songs and player.playlist.count_for_user(author) >= permissions.max_songs:
            raise exceptions.PermissionsError(
                self.str.get('cmd-stream-limit', "あなたはキューに入っている曲の上限に達しました({0})").format(permissions.max_songs), expire_in=30
            )

        if player.karaoke_mode and not permissions.bypass_karaoke_mode:
            raise exceptions.PermissionsError(
                self.str.get('karaoke-enabled', "カラオケモードが有効になっています。無効になってからもう一度お試しください。"), expire_in=30
            )

        await self.send_typing(channel)
        await player.playlist.add_stream_entry(song_url, channel=channel, author=author)

        return Response(self.str.get('cmd-stream-success', "ストリーミング"), delete_after=6)

    async def cmd_search(self, message, player, channel, author, permissions, leftover_args):
        """
        使用法:
            {command_prefix}search [service] [number] query

        サービスを探してビデオを探し、それをキューに追加します。
         -  service：以下のいずれかのサービス
             -  youtube（yt）（指定されていない場合はデフォルト）
             - サウンドクラウド（sc）
             - ヤフー（yh）
         - 数値：動画の検索結果の件数を返し、ユーザーが選択するのを待ちます
           - 指定されていない場合、デフォルトは3です。
           - 注：検索クエリが数字で始まる場合は、
                  クエリを引用符で囲む必要があります
             - 例:{command_prefix}search 2「カモメを走った」
        コマンド発行者は反応を使用して各結果に対する応答を示すことができます。
        """

        if permissions.max_songs and player.playlist.count_for_user(author) > permissions.max_songs:
            raise exceptions.PermissionsError(
                self.str.get('cmd-search-limit', "再生リストのアイテム数の上限に達しました({0})").format(permissions.max_songs),
                expire_in=30
            )

        if player.karaoke_mode and not permissions.bypass_karaoke_mode:
            raise exceptions.PermissionsError(
                self.str.get('karaoke-enabled', "カラオケモードが有効になっています。無効になってからもう一度お試しください。"), expire_in=30
            )

        def argcheck():
            if not leftover_args:
                # noinspection PyUnresolvedReferences
                raise exceptions.CommandError(
                    self.str.get('cmd-search-noquery', "検索クエリを指定してください。\n%s") % dedent(
                        self.cmd_search.__doc__.format(command_prefix=self.config.command_prefix)),
                    expire_in=60
                )

        argcheck()

        try:
            leftover_args = shlex.split(' '.join(leftover_args))
        except ValueError:
            raise exceptions.CommandError(self.str.get('cmd-search-noquote', "検索クエリを正しく引用してください。"), expire_in=30)

        service = 'youtube'
        items_requested = 3
        max_items = permissions.max_search_items
        services = {
            'youtube': 'ytsearch',
            'soundcloud': 'scsearch',
            'yahoo': 'yvsearch',
            'yt': 'ytsearch',
            'sc': 'scsearch',
            'yh': 'yvsearch'
        }

        if leftover_args[0] in services:
            service = leftover_args.pop(0)
            argcheck()

        if leftover_args[0].isdigit():
            items_requested = int(leftover_args.pop(0))
            argcheck()

            if items_requested > max_items:
                raise exceptions.CommandError(self.str.get('cmd-search-searchlimit', "%sを超える動画を検索できません") % max_items)

        # Look jake, if you see this and go "what the fuck are you doing"
        # and have a better idea on how to do this, i'd be delighted to know.
        # I don't want to just do ' '.join(leftover_args).strip("\"'")
        # Because that eats both quotes if they're there
        # where I only want to eat the outermost ones
        if leftover_args[0][0] in '\'"':
            lchar = leftover_args[0][0]
            leftover_args[0] = leftover_args[0].lstrip(lchar)
            leftover_args[-1] = leftover_args[-1].rstrip(lchar)

        search_query = '%s%s:%s' % (services[service], items_requested, ' '.join(leftover_args))

        search_msg = await self.safe_send_message(channel, self.str.get('cmd-search-searching', "動画を検索しています..."))
        await self.send_typing(channel)

        try:
            info = await self.downloader.extract_info(player.playlist.loop, search_query, download=False, process=True)

        except Exception as e:
            await self.safe_edit_message(search_msg, str(e), send_if_fail=True)
            return
        else:
            await self.safe_delete_message(search_msg)

        if not info:
            return Response(self.str.get('cmd-search-none', "動画が見つかりませんでした。"), delete_after=30)

        for e in info['entries']:
            result_message = await self.safe_send_message(channel, self.str.get('cmd-search-result', "結果{0}/{1}:{2}").format(
                info['entries'].index(e) + 1, len(info['entries']), e['webpage_url']))

            def check(reaction, user):
                return user == message.author and reaction.message.id == result_message.id  # why can't these objs be compared directly?

            reactions = ['\u2705', '\U0001F6AB', '\U0001F3C1']
            for r in reactions:
                await result_message.add_reaction(r)

            try:
                reaction, user = await self.wait_for('reaction_add', timeout=30.0, check=check)
            except asyncio.TimeoutError:
                await self.safe_delete_message(result_message)
                return

            if str(reaction.emoji) == '\u2705':  # check
                await self.safe_delete_message(result_message)
                await self.cmd_play(message, player, channel, author, permissions, [], e['webpage_url'])
                return Response(self.str.get('cmd-search-accept', "さて、すぐに来て！"), delete_after=30)
            elif str(reaction.emoji) == '\U0001F6AB':  # cross
                await self.safe_delete_message(result_message)
                continue
            else:
                await self.safe_delete_message(result_message)
                break

        return Response(self.str.get('cmd-search-decline', "Oh well :("), delete_after=30)

    async def cmd_np(self, player, channel, guild, message):
        """
        使用法:
            {command_prefix}np

        チャット中の現在の曲を表示します。
        """

        if player.current_entry:
            if self.server_specific_data[guild]['last_np_msg']:
                await self.safe_delete_message(self.server_specific_data[guild]['last_np_msg'])
                self.server_specific_data[guild]['last_np_msg'] = None

            # TODO: Fix timedelta garbage with util function
            song_progress = ftimedelta(timedelta(seconds=player.progress))
            song_total = ftimedelta(timedelta(seconds=player.current_entry.duration))

            streaming = isinstance(player.current_entry, StreamPlaylistEntry)
            prog_str = ('`[{progress}]`' if streaming else '`[{progress}/{total}]`').format(
                progress=song_progress, total=song_total
            )
            prog_bar_str = ''

            # percentage shows how much of the current song has already been played
            percentage = 0.0
            if player.current_entry.duration > 0:
                percentage = player.progress / player.current_entry.duration

            # create the actual bar
            progress_bar_length = 30
            for i in range(progress_bar_length):
                if (percentage < 1 / progress_bar_length * i):
                    prog_bar_str += '□'
                else:
                    prog_bar_str += '■'

            action_text = self.str.get('cmd-np-action-streaming', 'ストリーミング') if streaming else self.str.get('cmd-np-action-playing', '再生中')

            if player.current_entry.meta.get('channel', False) and player.current_entry.meta.get('author', False):
                np_text = self.str.get('cmd-np-reply-author', "Now {action}: **{title}** added by **{author}**\nProgress: {progress_bar} {progress}\n\N{WHITE RIGHT POINTING BACKHAND INDEX} <{url}>").format(
                    action=action_text,
                    title=player.current_entry.title,
                    author=player.current_entry.meta['author'].name,
                    progress_bar=prog_bar_str,
                    progress=prog_str,
                    url=player.current_entry.url
                )
            else:

                np_text = self.str.get('cmd-np-reply-noauthor', "現在 {action}: **{title}**\n次は: {progress_bar} {progress}\n\N{WHITE RIGHT POINTING BACKHAND INDEX} <{url}>").format(

                    action=action_text,
                    title=player.current_entry.title,
                    progress_bar=prog_bar_str,
                    progress=prog_str,
                    url=player.current_entry.url
                )

            self.server_specific_data[guild]['last_np_msg'] = await self.safe_send_message(channel, np_text)
            await self._manual_delete_check(message)
        else:
            return Response(
                self.str.get('cmd-np-none', '現在キューに曲がありません! {0}playで曲をリクエストして下さい。') .format(self.config.command_prefix),
                delete_after=30
            )

    async def cmd_summon(self, channel, guild, author, voice_channel):
        """
        使用法:
            {command_prefix}summon

        ボットをコマンドを実行した人がいる音声チャネルに呼び出します。
        """

        if not author.voice:
            raise exceptions.CommandError(self.str.get('cmd-summon-novc', 'You are not connected to voice. Try joining a voice channel!'))

        voice_client = self.voice_client_in(guild)
        if voice_client and guild == author.voice.channel.guild:
            await voice_client.move_to(author.voice.channel)
        else:
            # move to _verify_vc_perms?
            chperms = author.voice.channel.permissions_for(guild.me)

            if not chperms.connect:
                log.warning("Cannot join channel '{0}', no permission.".format(author.voice.channel.name))
                raise exceptions.CommandError(
                    self.str.get('cmd-summon-noperms-connect', "Cannot join channel `{0}`, no permission to connect.").format(author.voice.channel.name),
                    expire_in=25
                )

            elif not chperms.speak:
                log.warning("チャンネル '{0}'に参加できません。会話する権限がありません。".format(author.voice.channel.name))
                raise exceptions.CommandError(
                    self.str.get('cmd-summon-noperms-speak', "Cannot join channel `{0}`, no permission to speak.").format(author.voice.channel.name),
                    expire_in=25
                )

            player = await self.get_player(author.voice.channel, create=True, deserialize=self.config.persistent_queue)

            if player.is_stopped:
                player.play()

            if self.config.auto_playlist:
                await self.on_player_finished_playing(player)

        log.info("{0.guild.name}/{0.name}に参加中".format(author.voice.channel))

        return Response(self.str.get('cmd-summon-reply', 'Connected to `{0.name}`').format(author.voice.channel))

    async def cmd_pause(self, player):
        """
        使用法:
            {command_prefix}pause

        現在の曲の再生を一時停止します。
        """

        if player.is_playing:
            player.pause()
            return Response(self.str.get('cmd-pause-reply', 'Paused music in `{0.name}`').format(player.voice_client.channel))

        else:
            raise exceptions.CommandError(self.str.get('cmd-pause-none', 'Player is not playing.'), expire_in=30)

    async def cmd_resume(self, player):
        """
        使用法:
            {command_prefix}resume

        一時停止した曲の再生を再開します。
        """

        if player.is_paused:
            player.resume()
            return Response(self.str.get('cmd-resume-reply', 'Resumed music in `{0.name}`').format(player.voice_client.channel), delete_after=15)

        else:
            raise exceptions.CommandError(self.str.get('cmd-resume-none', 'Player is not paused.'), expire_in=30)

    async def cmd_shuffle(self, channel, player):
        """
        使用法:
            {command_prefix}shuffle

        サーバーのキューをシャッフルします。
        """

        player.playlist.shuffle()

        cards = ['\N{BLACK SPADE SUIT}', '\N{BLACK CLUB SUIT}', '\N{BLACK HEART SUIT}', '\N{BLACK DIAMOND SUIT}']
        random.shuffle(cards)

        hand = await self.safe_send_message(channel, ' '.join(cards))
        await asyncio.sleep(0.6)

        for x in range(4):
            random.shuffle(cards)
            await self.safe_edit_message(hand, ' '.join(cards))
            await asyncio.sleep(0.6)

        await self.safe_delete_message(hand, quiet=True)
        return Response(self.str.get('cmd-shuffle-reply', "Shuffled `{0}`'s queue.").format(player.voice_client.channel.guild), delete_after=15)

    async def cmd_clear(self, player, author):
        """
        使用法:
            {command_prefix}clear

        プレイリストを消去します。
        """

        player.playlist.clear()
        return Response(self.str.get('cmd-clear-reply', "Cleared `{0}`'s queue").format(player.voice_client.channel.guild), delete_after=20)

    async def cmd_remove(self, user_mentions, message, author, permissions, channel, player, index=None):
        """
        使用法:
            {command_prefix}remove [# in queue]

        キューに入っている曲を削除します。番号が指定されている場合は、キュー内のその曲を削除します。それ以外の場合は、最後にキューに入れられた曲を削除します。
        """

        if not player.playlist.entries:
            raise exceptions.CommandError(self.str.get('cmd-remove-none', "There's nothing to remove!"), expire_in=20)

        if user_mentions:
            for user in user_mentions:
                if permissions.remove or author == user:
                    try:
                        entry_indexes = [e for e in player.playlist.entries if e.meta.get('author', None) == user]
                        for entry in entry_indexes:
                            player.playlist.entries.remove(entry)
                        entry_text = '%s ' % len(entry_indexes) + 'item'
                        if len(entry_indexes) > 1:
                            entry_text += 's'
                        return Response(self.str.get('cmd-remove-reply', "Removed `{0}` added by `{1}`").format(entry_text, user.name).strip())

                    except ValueError:
                        raise exceptions.CommandError(self.str.get('cmd-remove-missing', "Nothing found in the queue from user `%s`") % user.name, expire_in=20)

                raise exceptions.PermissionsError(
                    self.str.get('cmd-remove-noperms', "You do not have the valid permissions to remove that entry from the queue, make sure you're the one who queued it or have instant skip permissions"), expire_in=20)

        if not index:
            index = len(player.playlist.entries)

        try:
            index = int(index)
        except (TypeError, ValueError):
            raise exceptions.CommandError(self.str.get('cmd-remove-invalid', "Invalid number. Use {}queue to find queue positions.").format(self.config.command_prefix), expire_in=20)

        if index > len(player.playlist.entries):
            raise exceptions.CommandError(self.str.get('cmd-remove-invalid', "Invalid number. Use {}queue to find queue positions.").format(self.config.command_prefix), expire_in=20)

        if permissions.remove or author == player.playlist.get_entry_at_index(index - 1).meta.get('author', None):
            entry = player.playlist.delete_entry_at_index((index - 1))
            await self._manual_delete_check(message)
            if entry.meta.get('channel', False) and entry.meta.get('author', False):
                return Response(self.str.get('cmd-remove-reply-author', "Removed entry `{0}` added by `{1}`").format(entry.title, entry.meta['author'].name).strip())
            else:
                return Response(self.str.get('cmd-remove-reply-noauthor', "Removed entry `{0}`").format(entry.title).strip())
        else:
            raise exceptions.PermissionsError(
                self.str.get('cmd-remove-noperms', "You do not have the valid permissions to remove that entry from the queue, make sure you're the one who queued it or have instant skip permissions"), expire_in=20
            )

    async def cmd_skip(self, player, channel, author, message, permissions, voice_channel, param=''):
        """
        使用法:
            {command_prefix}skip [force/f]

        十分な票が投​​じられたときに現在の曲をスキップします。
        所有者とinstaskip権限を持つユーザーは、スキップを強制するコマンドの後に 'force'または 'f'を追加できます。
        """

        if player.is_stopped:
            raise exceptions.CommandError(self.str.get('cmd-skip-none', "Can't skip! The player is not playing!"), expire_in=20)

        if not player.current_entry:
            if player.playlist.peek():
                if player.playlist.peek()._is_downloading:
                    return Response(self.str.get('cmd-skip-dl', "The next song (`%s`) is downloading, please wait.") % player.playlist.peek().title)

                elif player.playlist.peek().is_downloaded:
                    print("次の曲はまもなく再生されます。お待ちください。")
                else:
                    print("変なことが起こっています。  "
                          "動作しない場合は、ボットを再起動することをお勧めします。")
            else:
                print("奇妙なことが起こっています。  "
                      "動作しない場合は、ボットを再起動することをお勧めします。")
        
        current_entry = player.current_entry

        if (param.lower() in ['force', 'f']) or self.config.legacy_skip:
            if permissions.instaskip \
                or (self.config.allow_author_skip and author == player.current_entry.meta.get('author', None)):

                player.skip()  # TODO: check autopause stuff here
                await self._manual_delete_check(message)
                return Response(self.str.get('cmd-skip-force', 'Force skipped `{}`.').format(current_entry.title), reply=True, delete_after=30)
            else:
                raise exceptions.PermissionsError(self.str.get('cmd-skip-force-noperms', 'You do not have permission to force skip.'), expire_in=30)

        # TODO: ignore person if they're deaf or take them out of the list or something?
        # Currently is recounted if they vote, deafen, then vote

        num_voice = sum(1 for m in voice_channel.members if not (
            m.voice.deaf or m.voice.self_deaf or m == self.user))
        if num_voice == 0: num_voice = 1 # incase all users are deafened, to avoid divison by zero

        num_skips = player.skip_state.add_skipper(author.id, message)

        skips_remaining = min(
            self.config.skips_required,
            math.ceil(self.config.skip_ratio_required / (1 / num_voice))  # Number of skips from config ratio
        ) - num_skips

        if skips_remaining <= 0:
            player.skip()  # check autopause stuff here
            # @TheerapakG: Check for pausing state in the player.py make more sense
            return Response(
                self.str.get('cmd-skip-reply-skipped-1', 'Your skip for `{0}` was acknowledged.\nThe vote to skip has been passed.{1}').format(
                    current_entry.title,
                    self.str.get('cmd-skip-reply-skipped-2', ' Next song coming up!') if player.playlist.peek() else ''
                ),
                reply=True,
                delete_after=20
            )

        else:
            # TODO: When a song gets skipped, delete the old x needed to skip messages
            return Response(
                self.str.get('cmd-skip-reply-voted-1', 'Your skip for `{0}` was acknowledged.\n**{1}** more {2} required to vote to skip this song.').format(
                    current_entry.title,
                    skips_remaining,
                    self.str.get('cmd-skip-reply-voted-2', 'person is') if skips_remaining == 1 else self.str.get('cmd-skip-reply-voted-3', 'people are')
                ),
                reply=True,
                delete_after=20
            )

    async def cmd_volume(self, message, player, new_volume=None):
        """
        使用法:
            {command_prefix}volume (+/-)[volume]

        再生音量を設定します。許容値は1〜100です。
        音量の前に+または - を付けると、現在の音量を基準にして音量が変わります。
        """

        if not new_volume:
            return Response(self.str.get('cmd-volume-current', 'Current volume: `%s%%`') % int(player.volume * 100), reply=True, delete_after=20)

        relative = False
        if new_volume[0] in '+-':
            relative = True

        try:
            new_volume = int(new_volume)

        except ValueError:
            raise exceptions.CommandError(self.str.get('cmd-volume-invalid', '`{0}` is not a valid number').format(new_volume), expire_in=20)

        vol_change = None
        if relative:
            vol_change = new_volume
            new_volume += (player.volume * 100)

        old_volume = int(player.volume * 100)

        if 0 < new_volume <= 100:
            player.volume = new_volume / 100.0

            return Response(self.str.get('cmd-volume-reply', 'Updated volume from **%d** to **%d**') % (old_volume, new_volume), reply=True, delete_after=20)

        else:
            if relative:
                raise exceptions.CommandError(
                    self.str.get('cmd-volume-unreasonable-relative', 'Unreasonable volume change provided: {}{:+} -> {}%.  Provide a change between {} and {:+}.').format(
                        old_volume, vol_change, old_volume + vol_change, 1 - old_volume, 100 - old_volume), expire_in=20)
            else:
                raise exceptions.CommandError(
                    self.str.get('cmd-volume-unreasonable-absolute', 'Unreasonable volume provided: {}%. Provide a value between 1 and 100.').format(new_volume), expire_in=20)

    @owner_only
    async def cmd_option(self, player, option, value):
        """
        使用法:
            {command_prefix}option [option] [on/y/enabled/off/n/disabled]

        ボットを再起動せずに設定オプションを変更します。変更は恒久的なものではありません
        ボットが再起動されるまで続きます。恒久的な変更を加えるには、
        設定ファイル

        有効なオプション：
            自動再生リスト、save_videos、now_playing_mentions、auto_playlist_random、auto_pause、
            delete_messages、delete_invoking、write_current_song

        これらのオプションについては、設定ファイル内のオプションのコメントを参照してください。
        """

        option = option.lower()
        value = value.lower()
        bool_y = ['on', 'y', 'enabled']
        bool_n = ['off', 'n', 'disabled']
        generic = ['save_videos', 'now_playing_mentions', 'auto_playlist_random',
                   'auto_pause', 'delete_messages', 'delete_invoking',
                   'write_current_song']  # these need to match attribute names in the Config class
        if option in ['autoplaylist', 'auto_playlist']:
            if value in bool_y:
                if self.config.auto_playlist:
                    raise exceptions.CommandError(self.str.get('cmd-option-autoplaylist-enabled', 'The autoplaylist is already enabled!'))
                else:
                    if not self.autoplaylist:
                        raise exceptions.CommandError(self.str.get('cmd-option-autoplaylist-none', 'There are no entries in the autoplaylist file.'))
                    self.config.auto_playlist = True
                    await self.on_player_finished_playing(player)
            elif value in bool_n:
                if not self.config.auto_playlist:
                    raise exceptions.CommandError(self.str.get('cmd-option-autoplaylist-disabled', 'The autoplaylist is already disabled!'))
                else:
                    self.config.auto_playlist = False
            else:
                raise exceptions.CommandError(self.str.get('cmd-option-invalid-value', 'The value provided was not valid.'))
            return Response("自動再生リストは " + ['無効', '有効'][self.config.auto_playlist] + '.')
        else:
            is_generic = [o for o in generic if o == option]  # check if it is a generic bool option
            if is_generic and (value in bool_y or value in bool_n):
                name = is_generic   [0]
                log.debug('設定属性{0}'.format(name))
                setattr(self.config, name, True if value in bool_y else False)  # this is scary but should work
                attr = getattr(self.config, name)
                res = "オプション{0}は ".format(option) + ['無効', '有効'][attr] + '.'
                log.warning('このセッションでオーバーライドされたオプション:{0}'.format(res))
                return Response(res)
            else:
                raise exceptions.CommandError(self.str.get('cmd-option-invalid-param' ,'The parameters provided were invalid.'))

    async def cmd_queue(self, channel, player):
        """
        使用法:
            {command_prefix}queue

        現在のソングキューを印刷します。
        """

        lines = []
        unlisted = 0
        andmoretext = '* ... and %s more*' % ('x' * len(player.playlist.entries))

        if player.is_playing:
            # TODO: Fix timedelta garbage with util function
            song_progress = ftimedelta(timedelta(seconds=player.progress))
            song_total = ftimedelta(timedelta(seconds=player.current_entry.duration))
            prog_str = '`[%s/%s]`' % (song_progress, song_total)

            if player.current_entry.meta.get('channel', False) and player.current_entry.meta.get('author', False):
                lines.append(self.str.get('cmd-queue-playing-author', "Currently playing: `{0}` added by `{1}` {2}\n").format(
                    player.current_entry.title, player.current_entry.meta['author'].name, prog_str))
            else:
                lines.append(self.str.get('cmd-queue-playing-noauthor', "Currently playing: `{0}` {1}\n").format(player.current_entry.title, prog_str))


        for i, item in enumerate(player.playlist, 1):
            if item.meta.get('channel', False) and item.meta.get('author', False):
                nextline = self.str.get('cmd-queue-entry-author', '{0} -- `{1}` by `{2}`').format(i, item.title, item.meta['author'].name).strip()
            else:
                nextline = self.str.get('cmd-queue-entry-noauthor', '{0} -- `{1}`').format(i, item.title).strip()

            currentlinesum = sum(len(x) + 1 for x in lines)  # +1 is for newline char

            if (currentlinesum + len(nextline) + len(andmoretext) > DISCORD_MSG_CHAR_LIMIT) or (i > self.config.queue_length):
                if currentlinesum + len(andmoretext):
                    unlisted += 1
                    continue

            lines.append(nextline)

        if unlisted:
            lines.append(self.str.get('cmd-queue-more', '\n... and %s more') % unlisted)

        if not lines:
            lines.append(
                self.str.get('cmd-queue-none', 'There are no songs queued! Queue something with {}play.').format(self.config.command_prefix))

        message = '\n'.join(lines)
        return Response(message, delete_after=30)

    async def cmd_clean(self, message, channel, guild, author, search_range=50):
        """
        使用法:
            {command_prefix}clean [range]

        ボットがチャットに投稿した[範囲]メッセージまで削除します。デフォルト：50、最大：1000
        """

        try:
            float(search_range)  # lazy check
            search_range = min(int(search_range), 1000)
        except:
            return Response(self.str.get('cmd-clean-invalid', "Invalid parameter. Please provide a number of messages to search."), reply=True, delete_after=8)

        await self.safe_delete_message(message, quiet=True)

        def is_possible_command_invoke(entry):
            valid_call = any(
                entry.content.startswith(prefix) for prefix in [self.config.command_prefix])  # can be expanded
            return valid_call and not entry.content[1:2].isspace()

        delete_invokes = True
        delete_all = channel.permissions_for(author).manage_messages or self.config.owner_id == author.id

        def check(message):
            if is_possible_command_invoke(message) and delete_invokes:
                return delete_all or message.author == author
            return message.author == self.user

        if self.user.bot:
            if channel.permissions_for(guild.me).manage_messages:
                deleted = await channel.purge(check=check, limit=search_range, before=message)
                return Response(self.str.get('cmd-clean-reply', 'Cleaned up {0} message{1}.').format(len(deleted), 's' * bool(deleted)), delete_after=15)

    async def cmd_pldump(self, channel, author, song_url):
        """
        使用法:
            {command_prefix}pldump url

        プレイリストの個々のURLをダンプします
        """

        try:
            info = await self.downloader.extract_info(self.loop, song_url.strip('<>'), download=False, process=False)
        except Exception as e:
            raise exceptions.CommandError("入力URLから情報を抽出できませんでした。\n%s\n" % e, expire_in=25)

        if not info:
            raise exceptions.CommandError("入力URLから情報を抽出できませんでした。データがありません。", expire_in=25)

        if not info.get('entries', None):
            # TODO: Retarded playlist checking
            # set(url, webpageurl).difference(set(url))

            if info.get('url', None) != info.get('webpage_url', info.get('url', None)):
                raise exceptions.CommandError("これは再生リストではないようです。", expire_in=25)
            else:
                return await self.cmd_pldump(channel, info.get(''))

        linegens = defaultdict(lambda: None, **{
            "youtube":    lambda d: 'https://www.youtube.com/watch?v=%s' % d['id'],
            "soundcloud": lambda d: d['url'],
            "bandcamp":   lambda d: d['url']
        })

        exfunc = linegens[info['extractor'].split(':')[0]]

        if not exfunc:
            raise exceptions.CommandError("入力URL、サポートされていない再生リストタイプから情報を抽出できませんでした。", expire_in=25)

        with BytesIO() as fcontent:
            for item in info['entries']:
                fcontent.write(exfunc(item).encode('utf8') + b'\n')

            fcontent.seek(0)
            await author.send("これは<%s>の再生リストのダンプです。" % song_url, file=discord.File(fcontent, filename='playlist.txt'))

        return Response("プレイリストファイル付きのメッセージを送信しました。", delete_after=20)

    async def cmd_listids(self, guild, author, leftover_args, cat='all'):
        """
        使用法:
            {command_prefix}listids [categories]

        さまざまなもののIDをリストします。カテゴリーは以下のとおりです。
           すべて、ユーザー、ロール、チャンネル
        """

        cats = ['channels', 'roles', 'users']

        if cat not in cats and cat != 'all':
            return Response(
                "Valid categories: " + ' '.join(['`%s`' % c for c in cats]),
                reply=True,
                delete_after=25
            )

        if cat == 'all':
            requested_cats = cats
        else:
            requested_cats = [cat] + [c.strip(',') for c in leftover_args]

        data = ['あなたの ID: %s' % author.id]

        for cur_cat in requested_cats:
            rawudata = None

            if cur_cat == 'users':
                data.append("\nユーザー ID:")
                rawudata = ['%s #%s: %s' % (m.name, m.discriminator, m.id) for m in guild.members]

            elif cur_cat == 'roles':
                data.append("\n権限 ID:")
                rawudata = ['%s: %s' % (r.name, r.id) for r in guild.roles]

            elif cur_cat == 'channels':
                data.append("\nテキストチャンネル ID:")
                tchans = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
                rawudata = ['%s: %s' % (c.name, c.id) for c in tchans]

                rawudata.append("\nボイスチャンネル ID:")
                vchans = [c for c in guild.channels if isinstance(c, discord.VoiceChannel)]
                rawudata.extend('%s: %s' % (c.name, c.id) for c in vchans)

            if rawudata:
                data.extend(rawudata)

        with BytesIO() as sdata:
            sdata.writelines(d.encode('utf8') + b'\n' for d in data)
            sdata.seek(0)

            # TODO: Fix naming (Discord20API-ids.txt)
            await author.send(file=discord.File(sdata, filename='%s-ids-%s.txt' % (guild.name.replace(' ', '_'), cat)))

        return Response("IDのリストを含むメッセージを送信しました。", delete_after=20)


    async def cmd_perms(self, author, user_mentions, channel, guild, permissions):
        """
        使用法:
            {command_prefix}perms [@user]

        ユーザーにその権限のリスト、または指定されたユーザーの権限を送信します。
        """

        lines = ['%sのコマンド許可\n' % guild.name, '```', '```']

        if user_mentions:
            user = user_mentions[0]
            permissions = self.permissions.for_user(user)

        for perm in permissions.__dict__:
            if perm in ['user_list'] or permissions.__dict__[perm] == set():
                continue

            lines.insert(len(lines) - 1, "%s: %s" % (perm, permissions.__dict__[perm]))

        await self.safe_send_message(author, '\n'.join(lines))
        return Response("\N{OPEN MAILBOX WITH RAISED FLAG}", delete_after=20)


    @owner_only
    async def cmd_setname(self, leftover_args, name):
        """
        使用法:
            {command_prefix}setname name

        ボットのユーザー名を変更します。
        注:この操作は不和によって1時間に2回に制限されています。
        """

        name = ' '.join([name, *leftover_args])

        try:
            await self.user.edit(username=name)

        except discord.HTTPException:
            raise exceptions.CommandError(
                "名前を変更できませんでした。名前を何度も変更しましたか。  "
                "名前の変更は1時間に2回に制限されています。")

        except Exception as e:
            raise exceptions.CommandError(e, expire_in=20)

        return Response("ボットのユーザー名を**{0}**に設定してください".format(name), delete_after=20)

    async def cmd_setnick(self, guild, channel, leftover_args, nick):
        """
        使用法:
            {command_prefix}setnick nick

        ボットのニックネームを変更します。
        """

        if not channel.permissions_for(guild.me).change_nickname:
            raise exceptions.CommandError("ニックネームを変更できません:許可なし。")

        nick = ' '.join([nick, *leftover_args])

        try:
            await guild.me.edit(nick=nick)
        except Exception as e:
            raise exceptions.CommandError(e, expire_in=20)

        return Response("ボットのニックネームを `{0}`に設定します".format(nick), delete_after=20)

    @owner_only
    async def cmd_setavatar(self, message, url=None):
        """
        使用法:
            {command_prefix}setavatar [url]

        ボットのアバターを変更します。
        ファイルを添付し、urlパラメータを空白のままにしても機能します。
        """

        if message.attachments:
            thing = message.attachments[0].url
        elif url:
            thing = url.strip('<>')
        else:
            raise exceptions.CommandError("URLを入力するかファイルを添付する必要があります。", expire_in=20)

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with self.aiosession.get(thing, timeout=timeout) as res:
                await self.user.edit(avatar=await res.read())

        except Exception as e:
            raise exceptions.CommandError("アバターを変更できません:{}".format(e), expire_in=20)

        return Response("ボットのアバターを変更しました。", delete_after=20)


    async def cmd_disconnect(self, guild):
        """
        使用法:
            {command_prefix}disconnect
        
        ボットが現在の音声チャネルを離れるように強制します。
        """
        await self.disconnect_voice_client(guild)
        return Response("`{0.name}`から切断されました".format(guild), delete_after=20)

    async def cmd_restart(self, channel):
        """
        使用法:
            {command_prefix}restart
        
        ボットを再起動します。
        完全にシャットダウンしない限り、新しい依存関係またはファイル更新を正しくロードしません
        そして再開しました。
        """
        await self.safe_send_message(channel, "\N{WAVING HAND SIGN} Restarting. If you have updated your bot "
            "or its dependencies, you need to restart the bot properly, rather than using this command.")

        player = self.get_player_in(channel.guild)
        if player and player.is_paused:
            player.resume()

        await self.disconnect_all_voice_clients()
        raise exceptions.RestartSignal()

    async def cmd_shutdown(self, channel):
        """
        使用法:
            {command_prefix}shutdown
        
        音声チャネルから切断し、ボットプロセスを閉じます。
        """
        await self.safe_send_message(channel, "\N{WAVING HAND SIGN}")
        
        player = self.get_player_in(channel.guild)
        if player and player.is_paused:
            player.resume()
        
        await self.disconnect_all_voice_clients()
        raise exceptions.TerminateSignal()

    async def cmd_leaveserver(self, val, leftover_args):
        """
        使用法:
            {command_prefix}leaveserver <name/ID>

        ボットがサーバーを離れるように強制します。
        名前を提供するとき、名前は大文字と小文字を区別します。
        """
        if leftover_args:
            val = ' '.join([val, *leftover_args])

        t = self.get_guild(val)
        if t is None:
            t = discord.utils.get(self.guilds, name=val)
            if t is None:
                raise exceptions.CommandError('IDまたは名前が `{0}`のギルドは見つかりませんでした'.format(val))
        await t.leave()
        return Response('ギルドを去った:`{0.name}`(所有者:`{0.owner.name}`、ID:`{0.id}`)'.format(t))

    @dev_only
    async def cmd_breakpoint(self, message):
        log.critical("デバッグブレークポイントを有効にする")
        return

    @dev_only
    async def cmd_objgraph(self, channel, func='most_common_types()'):
        import objgraph

        await self.send_typing(channel)

        if func == 'growth':
            f = StringIO()
            objgraph.show_growth(limit=10, file=f)
            f.seek(0)
            data = f.read()
            f.close()

        elif func == 'leaks':
            f = StringIO()
            objgraph.show_most_common_types(objects=objgraph.get_leaking_objects(), file=f)
            f.seek(0)
            data = f.read()
            f.close()

        elif func == 'leakstats':
            data = objgraph.typestats(objects=objgraph.get_leaking_objects())

        else:
            data = eval('objgraph.' + func)

        return Response(data, codeblock='py')

    @dev_only
    async def cmd_debug(self, message, _player, *, data):
        codeblock = "```py\n{}\n```"
        result = None

        if data.startswith('```') and data.endswith('```'):
            data = '\n'.join(data.rstrip('`\n').split('\n')[1:])

        code = data.strip('` \n')

        try:
            result = eval(code)
        except:
            try:
                exec(code)
            except Exception as e:
                traceback.print_exc(chain=False)
                return Response("{}: {}".format(type(e).__name__, e))

        if asyncio.iscoroutine(result):
            result = await result

        return Response(codeblock.format(result))

    async def on_message(self, message):
        await self.wait_until_ready()

        message_content = message.content.strip()
        if not message_content.startswith(self.config.command_prefix):
            return

        if message.author == self.user:
            log.warning("自分からのコマンドを無視しています({})".format(message.content))
            return

        if self.config.bound_channels and message.channel.id not in self.config.bound_channels:
            if self.config.unbound_servers:
                for channel in message.guild.channels:
                    if channel.id in self.config.bound_channels:
                        return
            else:
                return  # if I want to log this I just move it under the prefix check

        if (not isinstance(message.channel, discord.abc.GuildChannel)) and (not isinstance(message.channel, discord.abc.PrivateChannel)):
            return

        command, *args = message_content.split(' ')  # Uh, doesn't this break prefixes with spaces in them (it doesn't, config parser already breaks them)
        command = command[len(self.config.command_prefix):].lower().strip()

        # [] produce [''] which is not what we want (it break things)
        if args:
            args = ' '.join(args).lstrip(' ').split(' ')
        else:
            args = []

        handler = getattr(self, 'cmd_' + command, None)
        if not handler:
            # alias handler
            if self.config.usealias:
                command = self.aliases.get(command)
                handler = getattr(self, 'cmd_' + command, None)
                if not handler:
                    return
            else:
                return

        if isinstance(message.channel, discord.abc.PrivateChannel):
            if not (message.author.id == self.config.owner_id and command == 'joinserver'):
                await self.safe_send_message(message.channel, 'このボットをプライベートメッセージに使用することはできません。')
                return

        if message.author.id in self.blacklist and message.author.id != self.config.owner_id:
            log.warning("ユーザーをブラックリストに登録:{0.id}/{0!s} ({1})".format(message.author, command))
            return

        else:
            log.info("{0.id}/{0!s}: {1}".format(message.author, message_content.replace('\n', '\n... ')))

        user_permissions = self.permissions.for_user(message.author)

        argspec = inspect.signature(handler)
        params = argspec.parameters.copy()

        sentmsg = response = None

        # noinspection PyBroadException
        try:
            if user_permissions.ignore_non_voice and command in user_permissions.ignore_non_voice:
                await self._check_ignore_non_voice(message)

            handler_kwargs = {}
            if params.pop('message', None):
                handler_kwargs['message'] = message

            if params.pop('channel', None):
                handler_kwargs['channel'] = message.channel

            if params.pop('author', None):
                handler_kwargs['author'] = message.author

            if params.pop('guild', None):
                handler_kwargs['guild'] = message.guild

            if params.pop('player', None):
                handler_kwargs['player'] = await self.get_player(message.channel)

            if params.pop('_player', None):
                handler_kwargs['_player'] = self.get_player_in(message.guild)

            if params.pop('permissions', None):
                handler_kwargs['permissions'] = user_permissions

            if params.pop('user_mentions', None):
                handler_kwargs['user_mentions'] = list(map(message.guild.get_member, message.raw_mentions))

            if params.pop('channel_mentions', None):
                handler_kwargs['channel_mentions'] = list(map(message.guild.get_channel, message.raw_channel_mentions))

            if params.pop('voice_channel', None):
                handler_kwargs['voice_channel'] = message.guild.me.voice.channel if message.guild.me.voice else None

            if params.pop('leftover_args', None):
                handler_kwargs['leftover_args'] = args

            args_expected = []
            for key, param in list(params.items()):

                # parse (*args) as a list of args
                if param.kind == param.VAR_POSITIONAL:
                    handler_kwargs[key] = args
                    params.pop(key)
                    continue

                # parse (*, args) as args rejoined as a string
                # multiple of these arguments will have the same value
                if param.kind == param.KEYWORD_ONLY and param.default == param.empty:
                    handler_kwargs[key] = ' '.join(args)
                    params.pop(key)
                    continue

                doc_key = '[{}={}]'.format(key, param.default) if param.default is not param.empty else key
                args_expected.append(doc_key)

                # Ignore keyword args with default values when the command had no arguments
                if not args and param.default is not param.empty:
                    params.pop(key)
                    continue

                # Assign given values to positional arguments
                if args:
                    arg_value = args.pop(0)
                    handler_kwargs[key] = arg_value
                    params.pop(key)

            if message.author.id != self.config.owner_id:
                if user_permissions.command_whitelist and command not in user_permissions.command_whitelist:
                    raise exceptions.PermissionsError(
                        "このコマンドはあなたのグループ({})では有効になっていません。".format(user_permissions.name),
                        expire_in=20)

                elif user_permissions.command_blacklist and command in user_permissions.command_blacklist:
                    raise exceptions.PermissionsError(
                        "このコマンドはあなたのグループ({})では無効です。".format(user_permissions.name),
                        expire_in=20)

            # Invalid usage, return docstring
            if params:
                docs = getattr(handler, '__doc__', None)
                if not docs:
                    docs = '使用法: {}{} {}'.format(
                        self.config.command_prefix,
                        command,
                        ' '.join(args_expected)
                    )

                docs = dedent(docs)
                await self.safe_send_message(
                    message.channel,
                    '```\n{}\n```'.format(docs.format(command_prefix=self.config.command_prefix)),
                    expire_in=60
                )
                return

            response = await handler(**handler_kwargs)
            if response and isinstance(response, Response):
                if not isinstance(response.content, discord.Embed) and self.config.embeds:
                    content = self._gen_embed()
                    content.title = command
                    content.description = response.content
                else:
                    content = response.content

                if response.reply:
                    if isinstance(content, discord.Embed):
                        content.description = '{} {}'.format(message.author.mention, content.description if content.description is not discord.Embed.Empty else '')
                    else:
                        content = '{}: {}'.format(message.author.mention, content)

                sentmsg = await self.safe_send_message(
                    message.channel, content,
                    expire_in=response.delete_after if self.config.delete_messages else 0,
                    also_delete=message if self.config.delete_invoking else None
                )

        except (exceptions.CommandError, exceptions.HelpfulError, exceptions.ExtractionError) as e:
            log.error("{0}のエラー: {1.__class__.__name__}: {1.message}".format(command, e), exc_info=True)

            expirein = e.expire_in if self.config.delete_messages else None
            alsodelete = message if self.config.delete_invoking else None

            if self.config.embeds:
                content = self._gen_embed()
                content.add_field(name='Error', value=e.message, inline=False)
                content.colour = 13369344
            else:
                content = '```\n{}\n```'.format(e.message)

            await self.safe_send_message(
                message.channel,
                content,
                expire_in=expirein,
                also_delete=alsodelete
            )

        except exceptions.Signal:
            raise

        except Exception:
            log.error("on_messageの例外", exc_info=True)
            if self.config.debug_mode:
                await self.safe_send_message(message.channel, '```\n{}\n```'.format(traceback.format_exc()))

        finally:
            if not sentmsg and not response and self.config.delete_invoking:
                await asyncio.sleep(5)
                await self.safe_delete_message(message, quiet=True)

    async def gen_cmd_list(self, message, list_all_cmds=False):
        for att in dir(self):
            # This will always return at least cmd_help, since they needed perms to run this command
            if att.startswith('cmd_') and not hasattr(getattr(self, att), 'dev_cmd'):
                user_permissions = self.permissions.for_user(message.author)
                command_name = att.replace('cmd_', '').lower()
                whitelist = user_permissions.command_whitelist
                blacklist = user_permissions.command_blacklist
                if list_all_cmds:
                    self.commands.append('{}{}'.format(self.config.command_prefix, command_name))

                elif blacklist and command_name in blacklist:
                    pass

                elif whitelist and command_name not in whitelist:
                    pass

                else:
                    self.commands.append("{}{}".format(self.config.command_prefix, command_name))

    async def on_voice_state_update(self, member, before, after):
        if not self.init_ok:
            return  # Ignore stuff before ready

        if before.channel:
            channel = before.channel
        elif after.channel:
            channel = after.channel
        else:
            return

        if not self.config.auto_pause:
            return

        autopause_msg = "{state} in {channel.guild.name}/{channel.name} {reason}"

        auto_paused = self.server_specific_data[channel.guild]['auto_paused']
        player = await self.get_player(channel)

        if not player:
            return

        if not member == self.user:  # if the user is not the bot
            if player.voice_client.channel != before.channel and player.voice_client.channel == after.channel:  # if the person joined
                if auto_paused and player.is_paused:
                    log.info(autopause_msg.format(
                        state = "Unpausing",
                        channel = player.voice_client.channel,
                        reason = ""
                    ).strip())

                    self.server_specific_data[player.voice_client.guild]['auto_paused'] = False
                    player.resume()
            elif player.voice_client.channel == before.channel and player.voice_client.channel != after.channel:
                if len(player.voice_client.channel.members) == 1:
                    if not auto_paused and player.is_playing:
                        log.info(autopause_msg.format(
                            state = "Pausing",
                            channel = player.voice_client.channel,
                            reason = "(empty channel)"
                        ).strip())

                        self.server_specific_data[player.voice_client.guild]['auto_paused'] = True
                        player.pause()
        else:
            if len(player.voice_client.channel.members) > 0:  # channel is not empty
                if auto_paused and player.is_paused:
                    log.info(autopause_msg.format(
                        state = "Unpausing",
                        channel = player.voice_client.channel,
                        reason = ""
                    ).strip())
 
                    self.server_specific_data[player.voice_client.guild]['auto_paused'] = False
                    player.resume()

    async def on_guild_update(self, before:discord.Guild, after:discord.Guild):
        if before.region != after.region:
            log.warning("ギルド\"%s\"が地域を変更しました:%s  ->%s" % (after.name, before.region, after.region))

    async def on_guild_join(self, guild:discord.Guild):
        log.info("ボットはギルドに追加されました: {}".format(guild.name))
        owner = self._get_owner(voice=True) or self._get_owner()
        if self.config.leavenonowners:
            check = guild.get_member(owner.id)
            if check == None:
                await guild.leave()
                log.info('ボットの所有者が見つからなかったため、{}を残しました。'.format(guild.name))
                await owner.send(self.str.get('left-no-owner-guilds', 'Left `{}` due to bot owner not being found in it.'.format(guild.name)))

        log.debug("ギルド%sのデータフォルダを作成しています", guild.id)
        pathlib.Path('data/%s/' % guild.id).mkdir(exist_ok=True)

    async def on_guild_remove(self, guild:discord.Guild):
        log.info("ボットはギルドから削除されました:{}".format(guild.name))
        log.debug('ギルドリストを更新:')
        [log.debug(' - ' + s.name) for s in self.guilds]

        if guild.id in self.players:
            self.players.pop(guild.id).kill()


    async def on_guild_available(self, guild:discord.Guild):
        if not self.init_ok:
            return # Ignore pre-ready events

        log.debug("ギルド\"{}\"が利用可能になりました。".format(guild.name))

        player = self.get_player_in(guild)

        if player and player.is_paused:
            av_paused = self.server_specific_data[guild]['availability_paused']

            if av_paused:
                log.debug("空室状況により\"{}\"でプレーヤーを再開しています。".format(guild.name))
                self.server_specific_data[guild]['availability_paused'] = False
                player.resume()


    async def on_guild_unavailable(self, guild:discord.Guild):
        log.debug("ギルド\"{}\"は使用できなくなりました。".format(guild.name))

        player = self.get_player_in(guild)

        if player and player.is_playing:
            log.debug("利用できないため、\"{}\"でプレーヤーを一時停止しています。".format(guild.name))
            self.server_specific_data[guild]['availability_paused'] = True
            player.pause()

    def voice_client_in(self, guild):
        for vc in self.voice_clients:
            if vc.guild == guild:
                return vc
        return None
