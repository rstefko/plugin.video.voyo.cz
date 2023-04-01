import uuid
import routing
import re
import requests
import json
import os
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import inputstreamhelper

addon = xbmcaddon.Addon()
profile = xbmc.translatePath(addon.getAddonInfo('profile'))
plugin = routing.Plugin()

baseUrl = 'https://apivoyo.cms.nova.cz/api/v1/'
session = requests.session()
token = ''
deviceHeaders = {
'X-DeviceType': 'mobile',
'X-DeviceOS': 'Android',
'X-DeviceOSVersion': '25',
'X-DeviceManufacturer': 'Android',
'X-DeviceModel': 'Kodi',
'X-DeviceName': 'Kodi',
}


def auth_session(username, password):
	global token
	login = json.dumps({ "username": username, "password": password })
	headers = deviceHeaders.copy()
	headers['Content-Type'] = "application/json; charset=UTF-8"
	resp = session.post(url=baseUrl + "auth-sessions", data=login, 
						headers=headers)
	if not resp.ok:
		raise PermissionError()

	token = resp.json()['credentials']['accessToken']

def login():
	global token
	token = None
	deviceId = addon.getSetting(id='deviceId')
	if not deviceId:
		deviceId = str(uuid.uuid4())
		addon.setSetting(id='deviceId', value=deviceId)

	x_device_id = { 'X-Device-Id': deviceId }
	deviceHeaders.update(x_device_id)

	addon.setSetting(id='accessToken', value=None)

	username = addon.getSetting('username')
	password = addon.getSetting('password')

	logged_in = False
	while not logged_in:
		if not username or not password:
			registration_notice = xbmcgui.Dialog()
			registration_notice.ok('VOYO účet', 'Pro přehrávání pořadů je potřeba účet s aktivním předplatným na voyo.nova.cz\n\nPokud účet ještě nemáte, zaregistrujte se na voyo.nova.cz, předplaťte účet na měsíc nebo rok a v dalším okně vyplňte přihlašovací údaje.')

			username_prompt = xbmcgui.Dialog()
			username = username_prompt.input('Uživatel (e-mail)')

			if not username:
				raise PermissionError()
			addon.setSetting(id='username', value=username)

			password_prompt = xbmcgui.Dialog()
			password = password_prompt.input('Heslo', option=xbmcgui.ALPHANUM_HIDE_INPUT)

			if not password:
				raise PermissionError()
			addon.setSetting(id='password', value=password)

		try:
			print(f'{username} {password}')
			auth_session(username, password)
			print(f'logged in')
			logged_in = True
			addon.setSetting(id='accessToken', value=token)
		except PermissionError:
			registration_notice.ok('VOYO účet', 'Neplatné přístupové údaje, zkuste zadat znovu')
			username = None
			password = None

def get_request(url, method='GET'):
	global token
	headers = deviceHeaders.copy()
	headers['Authorization'] = "Bearer " + token;
	return session.request(method=method, url=baseUrl + url, headers=headers)

def get(url, method='GET'):
	global token
	token = addon.getSetting('accessToken')
	deviceId = addon.getSetting('deviceId')
		
	if not token or not deviceId:
		login()

	resp = get_request(url, method)
	if resp.status_code == 401:
		login()
		resp = get_request(url, method)

	if not resp.ok:
		print(resp.content)
		if resp.status_code == 401:
			raise PermissionError()
		resp.raise_for_status()

	return resp.json()

def get_categories():
	categories = []
	jcategories = get('overview')['categories']
	for jcat in jcategories:
		jcatcat = jcat['category']
		if jcatcat:
			if jcatcat['name'] != 'Domů':
				categories.append(
					{ "id": jcatcat['id'],
					  "title": jcatcat['name'],
					  "type": jcatcat['type']
					} )
	return categories

def list_category(id, page=1, sort='date-desc'):
	items = []
	jitems = get(f'content?category={id}&page={page}&sort={sort}')['items']
	for jitem in jitems:
		items.append(
			{
				"id": jitem['id'],
				"title": jitem['title'],
				"type": jitem['type'],
				"imageTemplate": jitem['image']
			})
	return items

def list_tvshow_seasons(id):
	seasons = []
	jseasons = get(f'tvshow/{id}')['seasons']
	for jseason in jseasons:
		seasons.append(
			{
				"id": jseason['id'],
				"showId": id,
				"title": jseason['name'],
				"type": 'season'
			})
	return seasons

def list_season_episodes(showId, seasonId):
	episodes = []
	jepisodes = get(f'tvshow/{showId}?season={seasonId}')['sections'][0]['content']
	for jepisode in jepisodes:
		episodes.append(
			{
				"id": jepisode['id'],
				"type": jepisode['type'],
				"imageTemplate": jepisode['image'],
				"title": jepisode['title'],
				"length": jepisode['stream']['length']
			})
	return episodes

def list_live_channels(id):
	items = []
	jitems = get(f'overview?category={id}')['liveTvs']
	for jitem in jitems:
		items.append(
			{
				"id": jitem['id'],
				"title": jitem['name'],
				"type": 'livetv',
				"imageTemplate": jitem['logo'],
				"currentShow": jitem['currentlyPlaying']['title']
			})
	return items

def get_content_info(id):
	resp = get(f'content/{id}/plays?acceptVideo=hls%2cdash%2cdrm-widevine', method='POST')
	content = resp['content']
	result = {
		"id": id,
		"type": content['type'],
		"imageTemplate": content['image'],
		"title": content['title'],
		"showTitle": content['parentShowTitle'],
		"description": content['description'],
		"videoUrl": resp['url'],
		"videoType": resp['videoType'],
	}
	if resp['drm']:
		drm = {
			"drm": resp['drm']['keySystem'] ,
			"licenseKey": resp['drm']['licenseRequestHeaders'][0]['value'],
			"licenseUrl": resp['drm']['licenseUrl']
		}
		result.update(drm)

	return result

def get_thumb_url(url):
	return url.replace('{WIDTH}', '100').replace('{HEIGHT}', '100')

def get_poster_url(url):
	return url.replace('{WIDTH}', '900').replace('{HEIGHT}', '1200')

def get_media_type(typ):
	if typ == 'livechannel':
		return 'video'
	else:
		return typ

@plugin.route('/play_video/<id>')
def play_video(id):
	print(f'play_video {id}')
	print(f'plugin.handle {plugin.handle}')
	content = get_content_info(id)
	if content['videoType'] == 'hls':
		protocol = 'hls'
	else:
		protocol = 'mpd'
	list_item = xbmcgui.ListItem()
	list_item.setInfo('video', {
						'mediatype': get_media_type(content['type']),
						'title': content['title'],
						'tvshowtitle': content['showTitle'],
						'plot': content['description']
	})
	drm = content['drm'] if 'drm' in content else None
	helper = inputstreamhelper.Helper(protocol, drm=drm)
	if helper.check_inputstream():
		print(content['videoUrl'])
		list_item.setPath(content['videoUrl'])
		list_item.setContentLookup(False)
		if protocol == 'mpd':
			list_item.setMimeType('application/xml+dash')
		list_item.setProperty('inputstream', 'inputstream.adaptive')
		list_item.setProperty('inputstream.adaptive.manifest_type', protocol)
		if 'drm' in content:
			list_item.setProperty('inputstream.adaptive.license_type', content['drm'])
			list_item.setProperty('inputstream.adaptive.license_key',
				content['licenseUrl'] + '|X-AxDRM-Message=' + content['licenseKey'] + '|R{SSM}|')
	xbmcplugin.setResolvedUrl(plugin.handle, True, list_item)


@plugin.route('/tvshow/<id>/season/<season>')
def season(id, season):	
	episodes = list_season_episodes(id, season)
	for item in episodes:
		title = item['title']
		item_id = item['id']
		list_item = xbmcgui.ListItem(title)
		list_item.setArt({'icon': 'DefaultTVShows.png'})
		list_item.setArt({'poster': get_poster_url(item['imageTemplate'])})
		list_item.setInfo('video', {'mediatype': get_media_type(item['type']), 'title': title})
		list_item.setProperty('IsPlayable', 'true')
		dir_item = (plugin.url_for(play_video, item_id), list_item, False)
		xbmcplugin.addDirectoryItems(plugin.handle, [dir_item], len(episodes))
	xbmcplugin.endOfDirectory(plugin.handle)

@plugin.route('/tvshow/<id>')
def tvshow(id):
	seasons = list_tvshow_seasons(id)
	for item in seasons:
		title = item['title']
		item_id = item['id']
		list_item = xbmcgui.ListItem(title)
		dir_item = (plugin.url_for(season, id, item_id), list_item, True)
		xbmcplugin.addDirectoryItems(plugin.handle, [dir_item], len(seasons))
	xbmcplugin.endOfDirectory(plugin.handle)

@plugin.route('/category/<id>/<page>')
def category(id, page):
	page = int(page)
	items = list_category(id, page)
	for item in items:
		item_id = item['id']
		title = item['title']
		typ = item['type']
		list_item = xbmcgui.ListItem(title)
		list_item.setArt({'thumb': get_thumb_url(item['imageTemplate'])})
		list_item.setArt({'poster': get_poster_url(item['imageTemplate'])})
		dir_item = None
		print(typ)
		if typ == 'movie':
			list_item.setArt({'icon': 'DefaultTVShows.png'})
			list_item.setInfo('video', {'mediatype': get_media_type(item['type']), 'title': title})
			list_item.setProperty('IsPlayable', 'true')
			dir_item = (plugin.url_for(play_video, item_id), list_item, False)
		elif typ == 'tvshow':
			dir_item = (plugin.url_for(tvshow, item_id), list_item, True)
		if dir_item:
			xbmcplugin.addDirectoryItems(plugin.handle, [dir_item], len(items))

	next_page_item = xbmcgui.ListItem('Další...')
	next_page_dir_item = (plugin.url_for(category, id, page + 1), next_page_item, True)
	xbmcplugin.addDirectoryItems(plugin.handle, [next_page_dir_item], 1)
	xbmcplugin.endOfDirectory(plugin.handle)

@plugin.route('/live_channels/<id>')
def live_channels(id):
	channels = list_live_channels(id)
	for item in channels:
		item_id = item['id']
		title = item['title']
		list_item = xbmcgui.ListItem(title)
		list_item.setArt({'thumb': get_thumb_url(item['imageTemplate'])})
		list_item.setArt({'poster': get_poster_url(item['imageTemplate'])})
		list_item.setInfo('video', {'mediatype': get_media_type(item['type']), 'title': title})
		list_item.setProperty('IsPlayable', 'true')
		dir_item = (plugin.url_for(play_video, item_id), list_item, False)
		xbmcplugin.addDirectoryItems(plugin.handle, [dir_item], len(channels))
	xbmcplugin.endOfDirectory(plugin.handle)

@plugin.route('/')
def root():
	try:
		os.mkdir(profile)
	except OSError:
		pass

	try:
		categories = get_categories()
		for cat in categories:
			id = cat['id']
			title = cat['title']
			list_item = xbmcgui.ListItem(title)
			if cat['type'] == 'live':
				dir_item = (plugin.url_for(live_channels, id), list_item, True)
			else:
				dir_item = (plugin.url_for(category, id, 1), list_item, True)
			xbmcplugin.addDirectoryItems(plugin.handle, [dir_item], len(categories))
		xbmcplugin.endOfDirectory(plugin.handle)
	except PermissionError:
		print('error')

def run():
	plugin.run()
