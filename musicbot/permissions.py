import shutil
import logging
import traceback
import configparser

import discord

log = logging.getLogger(__name__)


class PermissionsDefaults:
    perms_file = 'config/permissions.ini'
    #now it's unpermissive by default for most
    CommandWhiteList = set()
    CommandBlackList = set()
    IgnoreNonVoice = set()
    GrantToRoles = set()
    UserList = set()

    MaxSongs = 8
    MaxSongLength = 210
    MaxPlaylistLength = 0
    MaxSearchItems = 10

    AllowPlaylists = True
    InstaSkip = False
    Remove = False
    SkipWhenAbsent = True
    BypassKaraokeMode = False

    Extractors = "youtube youtube:playlist"
	
	class Permissive:
	    CommandWhiteList = set()
	    CommandBlackList = set()
	    IgnoreNonVoice = set()
	    GrantToRoles = set()
	    UserList = set()
	
	    MaxSongs = 0
	    MaxSongLength = 0
	    MaxPlaylistLength = 0
	    MaxSearchItems = 10
	
	    AllowPlaylists = True
	    InstaSkip = True
	    Remove = True
	    SkipWhenAbsent = False
	    BypassKaraokeMode = True

        Extractors = ""

class Permissions:
    
    def __init__(self, config_file, grant_all=None):
        self.config_file = config_file
        self.config = configparser.ConfigParser(interpolation=None)

        if not self.config.read(config_file, encoding='utf-8'):
            log.info("許可ファイルが見つからない、example_permissions.iniをコピーする")

            try:
                shutil.copy('config/example_permissions.ini', config_file)
                self.config.read(config_file, encoding='utf-8')

            except Exception as e:
                traceback.print_exc()
                raise RuntimeError("config/example_permissions.iniを{}にコピーできません:{}".format(config_file, e))

        self.default_group = PermissionGroup('Default', self.config['Default'])
        self.groups = set()

        for section in self.config.sections():
            if section != 'Owner (auto)':
	                self.groups.add(PermissionGroup(section, self.config[section]))
	
	        if self.config.has_section('Owner (auto)'):
	            owner_group = PermissionGroup('Owner (auto)', self.config['Owner (auto)'], fallback=Permissive)
	
	        else:
	            log.info("[Owner (auto)] section not found, falling back to permissive default")
	            # Create a fake section to fallback onto the default non-permissive values to grant to the owner emulating the old behavior
	            # noinspection PyTypeChecker
	            owner_group = PermissionGroup("Owner (auto)", configparser.SectionProxy(self.config, Permissive))
	
        if hasattr(grant_all, '__iter__'):
            owner_group.user_list = set(grant_all)

        self.groups.add(owner_group)

    async def async_validate(self, bot):
        log.debug("権限の検証中...")

        og = discord.utils.get(self.groups, name="オーナー (auto)")
        if 'auto' in og.user_list:
            log.debug("自動所有者グループの修正")
            og.user_list = {bot.config.owner_id}

    def save(self):
        with open(self.config_file, 'w') as f:
            self.config.write(f)

    def for_user(self, user):
        """
        ユーザーが属している最初のPermissionGroupを返します。
        :param user:不一致ユーザーまたはメンバーオブジェクト
        """

        for group in self.groups:
            if user.id in group.user_list:
                return group

        # The only way I could search for roles is if I add a `server=None` param and pass that too
        if type(user) == discord.User:
            return self.default_group

        # We loop again so that we don't return a role based group before we find an assigned one
        for group in self.groups:
            for role in user.roles:
                if role.id in group.granted_to_roles:
                    return group

        return self.default_group

    def create_group(self, name, **kwargs):
        self.config.read_dict({name:kwargs})
        self.groups.add(PermissionGroup(name, self.config[name]))
        # TODO: Test this


class PermissionGroup:
    def __init__(self, name, section_data, fallback=PermissionsDefaults):
        self.name = name
        
	    self.command_whitelist = section_data.get('CommandWhiteList', fallback=fallback.CommandWhiteList)
	    self.command_blacklist = section_data.get('CommandBlackList', fallback=fallback.CommandBlackList)
	    self.ignore_non_voice = section_data.get('IgnoreNonVoice', fallback=fallback.IgnoreNonVoice)
	    self.granted_to_roles = section_data.get('GrantToRoles', fallback=fallback.GrantToRoles)
	    self.user_list = section_data.get('UserList', fallback=fallback.UserList)
	
	    self.max_songs = section_data.get('MaxSongs', fallback=fallback.MaxSongs)
	    self.max_song_length = section_data.get('MaxSongLength', fallback=fallback.MaxSongLength)
	    self.max_playlist_length = section_data.get('MaxPlaylistLength', fallback=fallback.MaxPlaylistLength)
	    self.max_search_items = section_data.get('MaxSearchItems', fallback=fallback.MaxSearchItems)
	
	    self.allow_playlists = section_data.get('AllowPlaylists', fallback=fallback.AllowPlaylists)
	    self.instaskip = section_data.get('InstaSkip', fallback=fallback.InstaSkip)
	    self.remove = section_data.get('Remove', fallback=fallback.Remove)
	    self.skip_when_absent = section_data.get('SkipWhenAbsent', fallback=fallback.SkipWhenAbsent)
	    self.bypass_karaoke_mode = section_data.get('BypassKaraokeMode', fallback=fallback.BypassKaraokeMode)
	
	    self.extractors = section_data.get('Extractors', fallback=fallback.Extractors)        self.extractors = section_data.get('Extractors', fallback=PermissionsDefaults.Extractors)

        self.validate()

    def validate(self):
        if self.command_whitelist:
            self.command_whitelist = set(self.command_whitelist.lower().split())

        if self.command_blacklist:
            self.command_blacklist = set(self.command_blacklist.lower().split())

        if self.ignore_non_voice:
            self.ignore_non_voice = set(self.ignore_non_voice.lower().split())

        if self.granted_to_roles:
            self.granted_to_roles = set([int(x) for x in self.granted_to_roles.split()])

        if self.user_list:
            self.user_list = set([int(x) for x in self.user_list.split()])

        if self.extractors:
            self.extractors = set(self.extractors.split())

        try:
            self.max_songs = max(0, int(self.max_songs))
        except:
            self.max_songs = PermissionsDefaults.MaxSongs

        try:
            self.max_song_length = max(0, int(self.max_song_length))
        except:
            self.max_song_length = PermissionsDefaults.MaxSongLength

        try:
            self.max_playlist_length = max(0, int(self.max_playlist_length))
        except:
            self.max_playlist_length = PermissionsDefaults.MaxPlaylistLength
                                  
        try:
             self.max_search_items = max(0, int(self.max_search_items))
        except:
             self.max_search_items = PermissionsDefaults.MaxSearchItems

        if int(self.max_search_items) > 100:
             log.warning('最大検索項目は100より大きくすることはできません。100以下に設定してください。')
             self.max_search_items = 100

        self.allow_playlists = configparser.RawConfigParser.BOOLEAN_STATES.get(
            self.allow_playlists, PermissionsDefaults.AllowPlaylists
        )

        self.instaskip = configparser.RawConfigParser.BOOLEAN_STATES.get(
            self.instaskip, PermissionsDefaults.InstaSkip
        )

        self.remove = configparser.RawConfigParser.BOOLEAN_STATES.get(
            self.remove, PermissionsDefaults.Remove
        )

        self.skip_when_absent = configparser.RawConfigParser.BOOLEAN_STATES.get(
            self.skip_when_absent, PermissionsDefaults.SkipWhenAbsent
        )

        self.bypass_karaoke_mode = configparser.RawConfigParser.BOOLEAN_STATES.get(
            self.bypass_karaoke_mode, PermissionsDefaults.BypassKaraokeMode
        )

    @staticmethod
    def _process_list(seq, *, split=' ', lower=True, strip=', ', coerce=str, rcoerce=list):
        lower = str.lower if lower else None
        _strip = (lambda x: x.strip(strip)) if strip else None
        coerce = coerce if callable(coerce) else None
        rcoerce = rcoerce if callable(rcoerce) else None

        for ch in strip:
            seq = seq.replace(ch, split)

        values = [i for i in seq.split(split) if i]
        for fn in (_strip, lower, coerce):
            if fn: values = map(fn, values)

        return rcoerce(values)

    def add_user(self, uid):
        self.user_list.add(uid)

    def remove_user(self, uid):
        if uid in self.user_list:
            self.user_list.remove(uid)


    def __repr__(self):
        return "<PermissionGroup: %s>" % self.name

    def __str__(self):
        return "<PermissionGroup: %s: %s>" % (self.name, self.__dict__)