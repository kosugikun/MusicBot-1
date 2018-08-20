import aiohttp
import asyncio
import base64
import logging
import time

from .exceptions import SpotifyError

log = logging.getLogger(__name__)

class Spotify:
    OAUTH_TOKEN_URL = 'https://accounts.spotify.com/api/token'
    API_BASE = 'https://api.spotify.com/v1/'

    def __init__(self, client_id, client_secret, aiosession=None, loop=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.aiosession = aiosession if aiosession else aiohttp.ClientSession()
        self.loop = loop if loop else asyncio.get_event_loop()

        self.token = None

        self.loop.run_until_complete(self.get_token())  # validate token

    def _make_token_auth(self, client_id, client_secret):
        auth_header = base64.b64encode((client_id + ':' + client_secret).encode('ascii'))
        return {'Authorization': 'Basic %s' % auth_header.decode('ascii')}

    async def get_track(self, uri):
        """URIからトラックの情報を取得する"""
        return await self.make_spotify_req(self.API_BASE + 'tracks/{0}'.format(uri))

    async def get_album(self, uri):
        """そのURIからアルバムの情報を取得する"""
        return await self.make_spotify_req(self.API_BASE + 'albums/{0}'.format(uri))

    async def get_playlist(self, user, uri, offset=0):
        """そのURIからプレイリストの情報を取得する"""
        return await self.make_spotify_req(self.API_BASE + 'users/{0}/playlists/{1}{2}'.format(user, uri, "/tracks?offset={}".format(offset) if offset > 0 else ""))

    async def make_spotify_req(self, url):
        """正しいAuthヘッダーを使用してSpotify reqを作成するためのプロキシメソッド"""
        token = await self.get_token()
        return await self.make_get(url, headers={'Authorization': 'Bearer {0}'.format(token)})

    async def make_get(self, url, headers=None):
        """GETリクエストを作成し、結果を返します。"""
        async with self.aiosession.get(url, headers=headers) as r:
            if r.status != 200:
                raise SpotifyError('{0}へのGET要求の発行に関する問題:[{1.status}] {2}'.format(url, r, await r.json()))
            return await r.json()

    async def make_post(self, url, payload, headers=None):
        """POSTリクエストを作成し、結果を返します。"""
        async with self.aiosession.post(url, data=payload, headers=headers) as r:
            if r.status != 200:
                raise SpotifyError('POST要求を{0}に発行する問題: [{1.status}] {2}'.format(url, r, await r.json()))
            return await r.json()

    async def get_token(self):
        """トークンを取得するか、期限切れの場合は新しいトークンを作成します。"""
        if self.token and not await self.check_token(self.token):
            return self.token['access_token']

        token = await self.request_token()
        if token is None:
            raise SpotifyError('Spotifyからのトークンを要求し、1つを取得しなかった')
        token['expires_at'] = int(time.time()) + token['expires_in']
        self.token = token
        log.debug('新しいアクセストークンを作成しました: {0}'.format(token))
        return self.token['access_token']

    async def check_token(self, token):
        """トークンが有効かどうかをチェックします。"""
        now = int(time.time())
        return token['expires_at'] - now < 60

    async def request_token(self):
        """Spotifyからトークンを取得して返します"""
        payload = {'grant_type': 'client_credentials'}
        headers = self._make_token_auth(self.client_id, self.client_secret)
        r = await self.make_post(self.OAUTH_TOKEN_URL, payload=payload, headers=headers)
        return r
