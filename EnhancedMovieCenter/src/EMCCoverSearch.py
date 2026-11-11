# Copyright (C) 2011 by Coolman & Swiss-MAD
# Copyright (C) 2014 by einfall
# Copyright (C) 2023 by jbleyel & Mr.Servo
#
# In case of reuse of this source code please do not remove this copyright.
#
#	This program is free software: you can redistribute it and/or modify
#	it under the terms of the GNU General Public License as published by
#	the Free Software Foundation, either version 3 of the License, or
#	(at your option) any later version.
#
#	This program is distributed in the hope that it will be useful,
#	but WITHOUT ANY WARRANTY; without even the implied warranty of
#	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#	GNU General Public License for more details.
#
#	For more information on the GNU General Public License see:
#	<http://www.gnu.org/licenses/>.
#
from html import unescape
from os import sep, remove
from os.path import exists, realpath
from random import choice
from re import sub, findall, search, match, S, I, IGNORECASE
from requests import session, get, exceptions
from shutil import move
from six import ensure_str
from urllib.parse import quote
from urllib.request import urlopen, Request
from time import time, process_time
import tmdbsimple as tmdb
from twisted.internet import defer
from twisted.internet.reactor import callInThread
from twisted.internet.threads import deferToThread

from enigma import ePicLoad, gPixmapPtr, eListboxPythonMultiContent, gFont, getDesktop, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_VALIGN_CENTER

from Components.ActionMap import HelpableActionMap
from Components.config import config, ConfigSelection, ConfigYesNo, ConfigSelectionNumber, ConfigSubsection
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryText
from Components.Pixmap import Pixmap
from Components.AVSwitch import AVSwitch
from Screens.Screen import Screen
from Screens.Setup import Setup
from Screens.LocationBox import LocationBox
from Screens.MessageBox import MessageBox
from Tools.BoundFunction import boundFunction
from Tools.Directories import fileExists
from .DelayedFunction import DelayedFunction
from .MovieCenter import getMovieNameWithoutExt, getMovieNameWithoutPhrases, getNoPosterPath
from . import _

sz_w = getDesktop(0).size().width()

config.EMC.imdb = ConfigSubsection()
#search/automatic
config.EMC.imdb.language = ConfigSelection(default='en', choices=[('en', _('English')), ('de', _('German')), ('it', _('Italian')), ('es', _('Spanish')), ('fr', _('French')), ('pt', _('Portuguese')), ('cs', _('Czech'))])
config.EMC.imdb.search_filter = ConfigSelection(default='3', choices=[('0', _('overall')), ('2', _('two contiguous')), ('3', _('three contiguous'))])
config.EMC.imdb.savetotxtfile = ConfigYesNo(default=False)
#single/manually
config.EMC.imdb.singlesearch = ConfigSelection(default='3', choices=[('0', _('imdb.com')), ('1', _('thetvdb.com')), ('3', _('all')), ('4', _('themoviedb.org')), ('5', _('themoviedb.org + thetvdb.com'))])
config.EMC.imdb.singlesearch_filter = ConfigSelection(default='2', choices=[('0', _('overall')), ('1', _('every single one')), ('2', _('two contiguous')), ('3', _('three contiguous'))])
config.EMC.imdb.singlesearch_siteresults = ConfigSelection(default='3', choices=[('0', _('no limit')), '3', '5', '10', '25', '50', '100'])
config.EMC.imdb.singlesearch_tvdbcoverrange = ConfigSelection(default='1', choices=[('0', _('no limit')), ('1', _('standard cover')), '3', '5', '10', '25'])
config.EMC.imdb.singlesearch_foldercoverpath = ConfigSelection(default='0', choices=[('0', _('.../foldername/foldername.jpg')), ('1', _('.../foldername.jpg')), ('2', _('.../foldername/folder.jpg'))])
#common
config.EMC.imdb.preferred_coversize = ConfigSelection(default="w185", choices=["w92", "w154", "w185", "w300", "w320", "w342", "w500", "w780", "original"])
config.EMC.imdb.thetvdb_standardcover = ConfigSelectionNumber(default=1, stepwidth=1, min=1, max=30, wraparound=True)

agents = [
	'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36 Edg/110.0.1587.50'
	'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/110.0'
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 14_4_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Mobile/15E148 Safari/604.1',
    'Mozilla/4.0 (compatible; MSIE 9.0; Windows NT 6.1)',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.141 Safari/537.36 Edg/87.0.664.75',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.102 Safari/537.36 Edge/18.18363',
    ]


def urlExist(url):
	try:
		urlopen(Request(url))
		return True
	except:
		return False


def getSearchList(title, option):
	slist = []
	s = title.replace('.', ' ').replace('_', ' ').replace('-', ' ').replace('+', ' ').split()
	if option == '1':
		slist = s
	elif option == '2':
		for x in range(len(s) - 1):
			slist.append(s[x] + ' ' + s[x + 1])
	elif option == '3':
		for x in range(len(s) - 2):
			slist.append(s[x] + ' ' + s[x + 1] + ' ' + s[x + 2])
	if not slist:
		slist = [' '.join(s)]
	return slist


def GetPage(link, headers=None, timeout=(3.05, 6), success=None, fail=None):
	link = link.encode('ascii', 'xmlcharrefreplace').decode().replace(' ', '%20').replace('\n', '')
	print(f"GetPage {link}")
	try:
		response = get(link, headers=headers, timeout=timeout)
		response.raise_for_status()
		if success is not None:
			success(response.content)
		print("GetPage success")
		return response.content
	except exceptions.RequestException as error:
		print(f"GetPage error:{error}")
		if fail is not None:
			fail(error)


class imdblist(MenuList):
	def __init__(self, list):
		MenuList.__init__(self, list, False, eListboxPythonMultiContent)
		self.l.setFont(0, gFont("Regular", 14))
		self.l.setFont(1, gFont("Regular", 16))
		self.l.setFont(2, gFont("Regular", 18))
		self.l.setFont(3, gFont("Regular", 20))
		self.l.setFont(4, gFont("Regular", 22))
		self.l.setFont(5, gFont("Regular", 24))
		self.l.setFont(6, gFont("Regular", 28))
		self.l.setFont(7, gFont("Regular", 54))
		self.l.setFont(8, gFont("Regular", 40))


class EMCImdbScan(Screen):
	if sz_w == 1920:
		skin = """
			<screen position="center,110" size="1800,930" title="EMC Cover search">
				<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img_fhd/red.png" position="10,5" size="300,70" alphatest="blend"/>
				<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img_fhd/green.png" position="310,5" size="300,70" alphatest="blend"/>
				<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img_fhd/yellow.png" position="610,5" size="300,70" alphatest="blend"/>
				<widget backgroundColor="#9f1313" font="Regular;30" halign="center" name="ButtonRedText" position="10,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="300,70" transparent="1" valign="center" zPosition="1" />
				<widget backgroundColor="#1f771f" font="Regular;30" halign="center" name="ButtonGreenText" position="310,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="300,70" transparent="1" valign="center" zPosition="1" />
				<widget backgroundColor="#a08500" font="Regular;30" halign="center" name="Manage Cover" position="610,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="300,70" transparent="1" valign="center" zPosition="1" />
				<widget font="Regular;34" halign="right" position="1650,25" render="Label" size="120,40" source="global.CurrentTime">
				    <convert type="ClockToText">Default</convert>
				</widget>
				<widget font="Regular;34" halign="right" position="1240,25" render="Label" size="400,40" source="global.CurrentTime" >
				    <convert type="ClockToText">Date</convert>
				</widget>
				<eLabel backgroundColor="#818181" position="10,80" size="1780,1" />
				<widget name="info" position="10,90" size="400,32" halign="center" font="Regular;28"/>
				<widget name="poster" position="10,130" size="400,600" alphatest="blend"/>
				<widget name="m_info" position="440,90" size="1350,40" font="Regular;34" halign="center" valign="center" foregroundColor="yellow"/>
				<widget name="menulist" position="440,140" size="1350,675" itemHeight="45" scrollbarMode="showOnDemand" enableWrapAround="1"/>
				<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img_fhd/menu.png" position="10,880" size="80,40" alphatest="blend"/>
				<widget name="Setup" position="110,882" size="380,40" font="Regular;30" valign="center" />
				<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img_fhd/ok.png" position="510,880" size="80,40" alphatest="blend"/>
				<widget name="Single search" position="610,882" size="280,40" font="Regular;30" valign="center" />
				<widget name="exist" position="10,740" size="400,35" font="Regular;30"/>
				<widget name="no_poster" position="10,780" size="400,35" font="Regular;30"/>
				<widget name="download" position="10,820" size="400,35" font="Regular;30"/>
				<widget name="done_msg" position="930,850" size="860,70" font="Regular;30" halign="right" foregroundColor="yellow" valign="bottom"/>
			</screen>"""
	else:
		skin = """
	    		<screen position="center,80" size="1200,610" title="EMC Cover search">
				<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img/red.png" position="10,5" size="200,40" alphatest="blend"/>
				<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img/green.png" position="210,5" size="200,40" alphatest="blend"/>
				<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img/yellow.png" position="410,5" size="200,40" alphatest="blend"/>
				<widget name="ButtonRedText" position="10,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" backgroundColor="#9f1313" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" />
				<widget name="ButtonGreenText" position="210,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" backgroundColor="#1f771f" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" />
				<widget name="Manage Cover" position="410,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" backgroundColor="#a08500" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" />
				<widget source="global.CurrentTime" render="Label" position="1130,12" size="60,25" font="Regular;22" halign="right">
					<convert type="ClockToText">Default</convert>
				</widget>
				<widget source="global.CurrentTime" render="Label" position="820,12" size="300,25" font="Regular;22" halign="right">
					<convert type="ClockToText">Format:%A %d. %B</convert>
				</widget>
				<eLabel position="10,50" size="1180,1" backgroundColor="#818181" />
				<widget name="info" position="20,55" size="220,55" halign="center" valign="center" font="Regular;22"/>
				<widget name="poster" position="20,120" size="220,330" alphatest="blend"/>
				<widget name="m_info" position="270,55" size="920,55" font="Regular;24" halign="center" valign="center" foregroundColor="yellow"/>
				<widget name="menulist" position="270,120" size="920,420" itemHeight="30" scrollbarMode="showOnDemand" enableWrapAround="1"/>
				<widget name="exist" position="10,470" size="220,25" font="Regular;20"/>
				<widget name="no_poster" position="10,500" size="220,25" font="Regular;20"/>
				<widget name="download" position="10,530" size="220,25" font="Regular;20"/>
				<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img/menu.png" position="20,570" size="60,30" alphatest="blend"/>
				<widget name="Setup" position="100,571" size="200,30" font="Regular;22" valign="center" />
				<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img/ok.png" position="320,570" size="60,30" alphatest="blend"/>
				<widget name="Single search" position="400,571" size="190,30" font="Regular;22" valign="center" />
				<widget name="done_msg" position="590,548" size="600,50" font="Regular;20" halign="right" foregroundColor="yellow" valign="bottom"/>
			</screen>"""

	def __init__(self, session, data, folder=False):
		Screen.__init__(self, session, data)
		self.m_list = data
		self.isFolder = folder
		self["actions"] = HelpableActionMap(self, "EMCimdb",
		{
			"EMCEXIT": self.exit,
			"EMCOK": self.ok,
			"EMCGreen": self.imdb,
			"EMCRed": self.red,
			"EMCYellow": self.verwaltung,
			"EMCRedLong": self.redLong,
			"EMCMenu": self.config,
		}, -1)

		self["ButtonGreen"] = Pixmap()
		self["ButtonGreenText"] = Label(_("Search"))
		self["ButtonRed"] = Pixmap()
		self["ButtonRedText"] = Label(_("Delete"))
		self["poster"] = Pixmap()
		self.menulist = []
		self["menulist"] = imdblist([])
		self["info"] = Label("")
		self["m_info"] = Label("")
		self["genre"] = Label("")
		self["download"] = Label("")
		self["exist"] = Label("")
		self["no_poster"] = Label("")
		self["done_msg"] = Label(_("Press green button to start search"))
		self["info"].setText("")
		self["Manage Cover"] = Label(_("Manage Cover"))
		self["Setup"] = Label(_("Setup"))
		self["Single search"] = Label(_("Single search"))
		self.no_image_poster = getNoPosterPath()
		self.check = False
		self["menulist"].onSelectionChanged.append(self.showInfo)
		self.running = False
		tmdb.API_KEY = bytes.fromhex("38373839636664336662616237646363663132363963336437643836376166666"[:-1]).decode('utf-8')

		self.picload = ePicLoad()
		self.file_format = r"(\.ts|\.avi|\.mkv|\.divx|\.f4v|\.flv|\.img|\.iso|\.m2ts|\.m4v|\.mov|\.mp4|\.mpeg|\.mpg|\.mts|\.vob|\.asf|\.wmv|.\stream|.\webm)"
		self.onLayoutFinish.append(self.layoutFinished)

		self.showSearchSiteName = "TMDb+TVDb"

	def layoutFinished(self):
		self.framebufferscale = AVSwitch().getFramebufferScale()
		self.lang = config.EMC.imdb.language.value
		self.listWidth = self["menulist"].instance.size().width()
		self.listHeight = self["menulist"].instance.size().height()
		self.itemHeight = self["menulist"].l.getItemSize().height()
		self.setTitle(_("EMC Cover search"))
		if self.isFolder:
			del self["actions"].actions['EMCGreen']
			del self["actions"].actions['EMCYellow']
			self["ButtonGreenText"].setText(" ")
			self["Manage Cover"].setText(" ")
			self["done_msg"].setText(" ")
			self.verwaltung()

	def verwaltung(self):
		self.menulist = []
		self.count_movies = len(self.m_list)
		self.vm_list = self.m_list[:]
		count_existing = 0
		count_na = 0

		#for each in sorted(self.vm_list):
		for each in self.vm_list:
			(title, path) = each
			if self.isFolder:
				if config.EMC.imdb.singlesearch_foldercoverpath.value == '1':
					path = path + '.jpg'
				elif config.EMC.imdb.singlesearch_foldercoverpath.value == '2':
					path = f"{path}{sep}folder.jpg"
				else:
					path = f"{path}{sep}{title}.jpg"
			title = getMovieNameWithoutExt(title)
			path = sub(self.file_format + "$", '.jpg', path, flags=IGNORECASE)
			if exists(path):
				count_existing += 1
				self.menulist.append(self.imdb_show(title, path, _("Exist"), "", title))
			else:
				count_na += 1
				self.menulist.append(self.imdb_show(title, path, _("N/A"), "", title))

		if self.menulist:
			self["menulist"].l.setList(self.menulist)
			self["menulist"].l.setItemHeight(self.itemHeight)
			self.check = True
			self.showInfo()
			self["done_msg"].setText((_("Total") + ": %s - " + _("Exist") + ": %s - " + _("N/A") + ": %s") % (self.count_movies, count_existing, count_na))

	def showInfo(self):
		check = self["menulist"].getCurrent()
		if check is None:
			return
		if self.check:
			m_title = self["menulist"].getCurrent()[0][0]
			m_poster_path = self["menulist"].getCurrent()[0][1]
			m_genre = self["menulist"].getCurrent()[0][3]
			if exists(m_poster_path):
				DelayedFunction(500, self.poster_resize(m_poster_path))
			else:
				DelayedFunction(500, self.poster_resize(self.no_image_poster))

			self["m_info"].setText(m_title)

	def no_cover(self):
		if exists(self.no_image_poster):
			DelayedFunction(500, self.poster_resize(self.no_image_poster))

	def imdb(self):
		if self.running:
			print("EMC iMDB: Search already Running.")

		elif not self.running:
			print("EMC iMDB: Search started...")
			self["done_msg"].show()
			self.no_cover()
			self.running = True
			self.counter_download = 0
			self.counter_exist = 0
			self.counter_no_poster = 0
			self.t_elapsed = 0
			self.menulist = []
			self.count_movies = len(self.m_list)
			self["exist"].setText(_("Exist: %s") % "0")
			self["no_poster"].setText(_("No Cover: %s") % "0")
			self["download"].setText(_("Download: %s") % "0")
			self["done_msg"].setText(_("Searching..."))
			self.s_supertime = time()
			self.cm_list = self.m_list[:]
			self.search_list = []
			self.exist_list = []
			self.check = False
			self["done_msg"].setText(_("Creating Search List.."))
			self.counting = 0
			self.count_total = len(self.cm_list)
			urls = []
			for each in self.cm_list:
				(title, path) = each
				title = getMovieNameWithoutExt(title)
				cover_path = sub(self.file_format + "$", '.jpg', path, flags=IGNORECASE)
				if exists(cover_path):
					self.counter_exist += 1
					self.counting += 1
					self.menulist.append(self.imdb_show(title, cover_path, _("Exist"), "", title))
					self["m_info"].setText(title)
					self["no_poster"].setText(_("No Cover: %s") % str(self.counter_no_poster))
					self["exist"].setText(_("Exist: %s") % str(self.counter_exist))
					self["download"].setText(_("Download: %s") % str(self.counter_download))
					self["menulist"].l.setList(self.menulist)
					self["menulist"].l.setItemHeight(self.itemHeight)
					self.check = True
					print(f"EMC iMDB: Cover vorhanden - {title}")
				else:
					s_title = getSearchList(title, None)[0]
					m_title = getSearchList(title, config.EMC.imdb.search_filter.value)[0]
					if search(r'[Ss][0-9]+[Ee][0-9]+', s_title) is not None:
						season = None
						episode = None
						seasonEpisode = findall(r'.*?[Ss]([0-9]+)[Ee]([0-9]+)', s_title, S | I)
						if seasonEpisode:
							(season, episode) = seasonEpisode[0]
						name2 = getMovieNameWithoutPhrases(s_title)
						name2 = sub(r'[Ss][0-9]+[Ee][0-9]+.*[a-zA-Z0-9_]+', '', name2, flags=S | I)
						url = f'https://thetvdb.com/api/GetSeries.php?seriesname={quote(str(name2))}&language={self.lang}'
						urls.append(("serie", title, url, cover_path, season, episode))
					else:
						url = f'https://api.themoviedb.org/3/search/movie?api_key=8789cfd3fbab7dccf1269c3d7d867aff&query={quote(str(m_title))}&language={self.lang}'
						urls.append(("movie", title, url, cover_path, None, None))
			if len(urls) != 0:
				ds = defer.DeferredSemaphore(tokens=3)
				downloads = [ds.run(self.download, url, title, type).addCallback(self.parseWebpage, type, title, url, cover_path, season, episode).addErrback(self.dataError) for type, title, url, cover_path, season, episode in urls]
				finished = defer.DeferredList(downloads).addErrback(self.dataError2)
			else:
				self["done_msg"].setText(_("No Movies found!"))
				self.running = False
				self.showInfo()

	def tmdbSaveInfo(self, movieID, cover_path):
		movie = tmdb.Movies(int(movieID))
		MI = movie.info(language=self.lang)
		self.writeTofile(unescape(MI["overview"]), cover_path)

	def tmdbSearch(self, text, year):
		search = tmdb.Search()
		json_data = search.multi(query=text, language=self.lang, year=year) if year else search.multi(query=text, language=self.lang)
		return json_data.get("results", None) if json_data else None

	def download(self, url, moviename, type):
		if type == "movie":
			m = match(r'^(.*) \((19\d\d|20\d\d)\)$', moviename)
			year = None
			text = moviename
			if m:
				text, year = m.groups()
			return deferToThread(self.tmdbSearch, text, year)
		else:
			headers = {"User-Agent": choice(agents), 'Accept': 'application/json'}
			return deferToThread(GetPage, url, headers=headers, success=None, fail=None)

	def parseWebpage(self, data, type, title, url, cover_path, season, episode):
		self.counting += 1
		self.start_time = process_time()
		if type == "movie":
			if data:
				if isinstance(data, list):
					data = data[0]
				poster_path = data["poster_path"].strip('/')
				purl = f"https://image.tmdb.org/t/p/{config.EMC.imdb.preferred_coversize.value}/{poster_path}"
				self.counter_download += 1
				self.end_time = process_time()
				elapsed = (self.end_time - self.start_time) * 1000
				self.menulist.append(self.imdb_show(title, cover_path, f'{elapsed:.1f}', "", title))
				if not fileExists(cover_path):
					callInThread(self.DownloadPage, purl, cover_path, success=None, fail=self.dataError)
				# get description
				if config.EMC.imdb.savetotxtfile.value:
					movieID = data["id"]
					if movieID:
						callInThread(self.tmdbSaveInfo, movieID, cover_path)
			else:
				self.counter_no_poster += 1
				self.menulist.append(self.imdb_show(title, cover_path, _("N/A"), "", title))

		elif type == "serie":
			data = ensure_str(data) if data else ""
			items = findall(r'<seriesid>(.*?)</seriesid>', data, S)
			if items:
				x = config.EMC.imdb.thetvdb_standardcover.value
				purl = f"https://artworks.thetvdb.com/banners/posters/{str(items[0])}-{x}.jpg"
				if x > 1 and not urlExist(purl):
					x = 1
					purl = f"https://artworks.thetvdb.com/banners/posters/{str(items[0])}-{x}.jpg"
				if not urlExist(purl):
					self.counter_no_poster += 1
					self.menulist.append(self.imdb_show(title, cover_path, _("N/A"), "", title))
				else:
					self.counter_download += 1
					self.end_time = process_time()
					elapsed = (self.end_time - self.start_time) * 1000
					self.menulist.append(self.imdb_show(title, cover_path, f'{elapsed:.1f}', "", title))
					if not fileExists(cover_path):
						callInThread(self.DownloadPage, purl, cover_path, success=None, fail=self.dataError)
					# get description
					if config.EMC.imdb.savetotxtfile.value and season and episode:
						iurl = f"https://www.thetvdb.com/api/2AAF0562E31BCEEC/series/{str(items[0])}/default/{str(int(season))}/{str(int(episode))}/{self.lang}.xml"
						callInThread(GetPage, iurl, boundFunction(self.getInfos, id, type, cover_path), self.dataError)
			else:
				self.counter_no_poster += 1
				self.menulist.append(self.imdb_show(title, cover_path, _("N/A"), "", title))

		self.count = ("%s: %s " + _("from") + " %s") % (self.showSearchSiteName, self.counting, self.count_total)
		self["info"].setText(self.count)
		self["no_poster"].setText(_("No Cover: %s") % str(self.counter_no_poster))
		self["exist"].setText(_("Exist: %s") % str(self.counter_exist))
		self["download"].setText(_("Download: %s") % str(self.counter_download))
		self["menulist"].l.setList(self.menulist)
		self["menulist"].l.setItemHeight(self.itemHeight)
		self.check = True

		if self.counting == self.count_total:
			self.e_supertime = time()
			total_time = self.e_supertime - self.s_supertime
			avg = (total_time / self.count_total)
			self.done = ("%s " + _("movies in") + " %.1f " + _("sec found. Avg. Speed:") + " %.1f " + _("sec.")) % (self.count_total, total_time, avg)
			self["done_msg"].setText(self.done)
			self.running = False
			self.showInfo()

	def getInfos(self, data, id, type, cover_path):
		data = ensure_str(data)
		if type == "movie":
			infos = findall(r'"genres":\[(.*?)\].*?"overview":"(.*?)"', data, S)
			if infos:
				(genres, desc) = infos[0]
				self.writeTofile(unescape(desc), cover_path)

		elif type == "serie":
			infos = findall(r'<Overview>(.*?)</Overview>', data, S)
			if infos:
				desc = infos[0]
				self.writeTofile(unescape(desc), cover_path)

	def writeTofile(self, text, cover_path):
		print(cover_path)
		if not fileExists(cover_path.replace('.jpg', '.txt')):
			wFile = open(cover_path.replace('.jpg', '.txt'), "w")
			wFile.write(text)
			wFile.close()

	def DownloadPage(self, link, file, success=None, fail=None):
		link = link.encode('ascii', 'xmlcharrefreplace').decode().replace(' ', '%20').replace('\n', '')
		try:
			response = get(link, timeout=(3.05, 6))
			response.raise_for_status()
			with open(file, "wb") as f:
				f.write(response.content)
			if success is not None:
				success(file)
		except exceptions.RequestException as error:
			if fail is not None:
				fail(error)

	def dataError(self, error):
		print(f"ERROR: {error}")

	def dataError2(self, error):
		self.counting = int(self.counting) + 1
		print(f"ERROR: {error}")

	def errorLoad(self, error, search_title):
		print(f"EMC keine daten zu {search_title} gefunden.")

	def exit(self):
		self.check = False
		if self.picload:
			del self.picload
		self.close()

	def red(self):
		if self.check:
			m_poster_path = self["menulist"].getCurrent()[0][1]
			if exists(m_poster_path):
				if m_poster_path == self.no_image_poster:
					print("EMC no_poster.jpg kann nicht geloescht werden.")
				else:
					try:
						remove(m_poster_path)
						self.verwaltung()
						self.no_cover()
						self["done_msg"].setText(_("%s removed.") % m_poster_path)
					except:
						self["done_msg"].setText(_("%s not removed. Write protect?") % m_poster_path)

	def redLong(self):
		pass

	def ok(self):
		if self.check and self.menulist:
			m_title = self["menulist"].getCurrent()[0][0]
			m_poster_path = self["menulist"].getCurrent()[0][1]
			data_list = [(m_title, m_poster_path)]
			self.session.openWithCallback(self.setupFinished2, getCover, data_list)

	### Cover resize ###
	def poster_resize(self, poster_path):
		if fileExists(poster_path):
			self["poster"].instance.setPixmap(gPixmapPtr())
			size = self["poster"].instance.size()
			self.picload.setPara((size.width(), size.height(), self.framebufferscale[0], self.framebufferscale[1], False, 1, "#00000000"))
			result = self.picload.startDecode(poster_path, 0, 0, False)
			if result == 0:
				ptr = self.picload.getData()
				if ptr is not None:
					self["poster"].instance.setPixmap(ptr)
					self["poster"].show()

	def config(self):
		self.session.openWithCallback(self.setupFinished, CoverSearchSetup)

	def setupFinished(self, result=False):
		print("EMC iMDB Config Saved.")
		if result:
			if self.isFolder:
				self.verwaltung()  # if foldercoverpath settings is changed
			self["done_msg"].show()
			self["done_msg"].setText(_("Settings have been Saved."))

	def setupFinished2(self, result):
		print("EMC iMDB single search done.")
		if result:
			self.verwaltung()
			self["done_msg"].show()
			self["done_msg"].setText(_("Cover is Saved."))

	def cleanFile(text):
		cutlist = ['x264', '720p', '1080p', '1080i', 'PAL', 'GERMAN', 'ENGLiSH', 'WS', 'DVDRiP', 'UNRATED', 'RETAIL', 'Web-DL', 'DL', 'LD', 'MiC', 'MD', 'DVDR', 'BDRiP', 'BLURAY', 'DTS', 'UNCUT', 'ANiME',
					'AC3MD', 'AC3', 'AC3D', 'TS', 'DVDSCR', 'COMPLETE', 'INTERNAL', 'DTSD', 'XViD', 'DIVX', 'DUBBED', 'LINE.DUBBED', 'DD51', 'DVDR9', 'DVDR5', 'h264', 'AVC',
					'WEBHDTVRiP', 'WEBHDRiP', 'WEBRiP', 'WEBHDTV', 'WebHD', 'HDTVRiP', 'HDRiP', 'HDTV', 'ITUNESHD', 'REPACK', 'SYNC']
		text = text.replace('.wmv', '').replace('.flv', '').replace('.ts', '').replace('.m2ts', '').replace('.mkv', '').replace('.avi', '').replace('.mpeg', '').replace('.mpg', '').replace('.iso', '')

		for word in cutlist:
			text = sub(r'(\_|\-|\.|\+)' + word + r'(\_|\-|\.|\+)', '+', text, flags=I)
		text = text.replace('.', ' ').replace('-', ' ').replace('_', ' ').replace('+', '')

	def imdb_show(self, title, pp, elapsed, genre, search_title):
		res = [(title, pp, elapsed, genre, search_title)]
		s1 = _("Exist") + "|" + _("N/A")
		if not match(r'.*?(' + s1 + ')', elapsed):
			elapsed = f"{elapsed} ms"
		screenWidth = getDesktop(0).size().width()
		if screenWidth >= 2560:
			f, gF = (2, 8)
		elif screenWidth >= 1920:
			f, gF = (1.5, 6)
		else:
			f, gF = (1, 4)
		h = self.itemHeight
		w = self.listWidth - 15 if self.count_movies * h > self.listHeight else self.listWidth  # place for scrollbar
		res.append(MultiContentEntryText(pos=(5, 0), size=(w, h), font=gF, text=search_title, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER))
		res.append(MultiContentEntryText(pos=(w - 150 * f, 0), size=(140 * f, h), font=gF, text=elapsed, flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER))
		return res


class CoverSearchSetup(Setup):
	def __init__(self, session):
		Setup.__init__(self, session, "CoverSearchSetup", plugin="Extensions/EnhancedMovieCenter", PluginLanguageDomain="EnhancedMovieCenter")

	def keySave(self):
		self.saveAll()
		self.close(True)

	def closeRecursive(self):
		self.closeConfigList(())


class getCover(Screen):
	if sz_w == 1920:
		skin = """
		<screen position="center,110" size="1800,930" title="EMC Cover Selecter">
		<widget name="m_info" position="10,10" size="1780,40" font="Regular;35" halign="center" foregroundColor="yellow"/>
		<eLabel backgroundColor="#818181" position="10,60" size="1780,1" />
		<widget name="poster" position="10,80" size="400,600" alphatest="blend"/>
		<widget name="menulist" position="440,80" size="1350,810" itemHeight="45" scrollbarMode="showOnDemand" enableWrapAround="1"/>
		<widget name="info" position="10,700" size="400,140" font="Regular;30" halign="center" valign="center" foregroundColor="yellow"/>
		</screen>"""
	else:
		skin = """
   		<screen position="center,80" size="1200,610" title="EMC Cover Selecter">
		<widget name="m_info" position="10,5" size="1180,30" font="Regular;24" halign="center" valign="center" foregroundColor="yellow"/>
		<eLabel backgroundColor="#818181" position="10,40" size="1180,1" />
		<widget name="poster" position="20,50" size="220,330" alphatest="blend"/>
		<widget name="menulist" position="270,50" size="920,540" itemHeight="30" scrollbarMode="showOnDemand" enableWrapAround="1"/>
		<widget name="info" position="10,400" size="220,80" font="Regular;20" halign="center" valign="center" foregroundColor="yellow"/>
		</screen>"""

	def __init__(self, session, data):
		Screen.__init__(self, session, data)

		self["actions"] = HelpableActionMap(self, "EMCimdb",
		{
			"EMCEXIT": self.exit,
			"EMCOK": self.ok,
		}, -1)

		(title, o_path) = data.pop()
		self.m_title = title
		self["m_info"] = Label(f"{self.m_title}")
		self.o_path = o_path
		self.menulist = []
		self["menulist"] = imdblist([])
		self["poster"] = Pixmap()
		self["info"] = Label(_("Searching for %s") % self.m_title)
		self["menulist"].onSelectionChanged.append(self.showInfo)
		self.check = False
		self.path = "/tmp/tmp.jpg"
		self.cover_count = 0
		self.einzel_start_time = time()
		self.picload = ePicLoad()
		self.onLayoutFinish.append(self.layoutFinished)

	def layoutFinished(self):
		self.framebufferscale = AVSwitch().getFramebufferScale()
		self.lang = config.EMC.imdb.language.value
		self.listWidth = self["menulist"].instance.size().width()
		self.listHeight = self["menulist"].instance.size().height()
		self.itemHeight = self["menulist"].l.getItemSize().height()
		self.setTitle(_("EMC Cover Selecter"))

		if config.EMC.imdb.singlesearch.value == "0":
			self.searchimdb(self.m_title)
		elif config.EMC.imdb.singlesearch.value == "1":
			self.searchtvdb(self.m_title)
		elif config.EMC.imdb.singlesearch.value == "3":
			self.searchimdb(self.m_title)
			self.searchtmdb(self.m_title)
			self.searchtvdb(self.m_title)
		elif config.EMC.imdb.singlesearch.value == "4":
			self.searchtmdb(self.m_title)
		elif config.EMC.imdb.singlesearch.value == "5":
			self.searchtmdb(self.m_title)
			self.searchtvdb(self.m_title)

	@defer.inlineCallbacks
	def searchtmdb(self, title):
		print(f"EMC TMDB: Cover Select - {title}")
		templist = []
		coverlist = []
		coversize = config.EMC.imdb.preferred_coversize.value
		finish = False
		siteresults = int(config.EMC.imdb.singlesearch_siteresults.value)
		part = getSearchList(title, config.EMC.imdb.singlesearch_filter.value)
		for item in part:
			if finish:
				break
			url = f'https://api.themoviedb.org/3/search/movie?api_key=8789cfd3fbab7dccf1269c3d7d867aff&query={quote(str(item))}&language={self.lang}'
			headers = {"User-Agent": choice(agents)}
			data = yield deferToThread(GetPage, url, headers=headers, success=None, fail=boundFunction(self.errorLoad, title))
#			data = yield str(GetPage(url, headers=headers, success=None, fail=boundFunction(self.errorLoad, title)))
			if data:
				data = ensure_str(data)
				bild = findall(r'original_title":"(.*?)".*?"poster_path":"(.*?)"', data, S)
				if bild:
					for each in bild:
						m_cover = each[1]
						m_title = each[0]
						if m_cover in coverlist:
							continue
						coverlist.append(m_cover)
						self.cover_count += 1
						tmdb_url = f"https://image.tmdb.org/t/p/{coversize}/{str(m_cover).strip('/')}"
						templist.append(self.showCoverlist(m_title, tmdb_url, self.o_path, "tmdb: "))
						if siteresults and len(coverlist) >= siteresults:
							finish = True
							break
		templist.sort()
		self.menulist.extend(templist)
		if not templist:
			#self["info"].setText(_("Nothing found for %s") % title)
			print(f"EMC TMDB: keine infos gefunden - {title}")
		self.search_done()

	@defer.inlineCallbacks
	def searchtvdb(self, title):
		print(f"EMC TVDB: Cover Select - {title}")
		templist = []
		coverlist = []
		standardcover = config.EMC.imdb.thetvdb_standardcover.value
		finish = False
		coverrange = int(config.EMC.imdb.singlesearch_tvdbcoverrange.value)
		siteresults = int(config.EMC.imdb.singlesearch_siteresults.value)
		part = getSearchList(title, config.EMC.imdb.singlesearch_filter.value)
		for item in part:
			if finish:
				break
			url = f"https://www.thetvdb.com/api/GetSeries.php?seriesname={quote(str(item))}&language={self.lang}"
			headers = {"User-Agent": choice(agents)}
			data = yield deferToThread(GetPage, url, headers=headers, success=None, fail=boundFunction(self.errorLoad, title))
#			data = yield GetPage(url, headers=headers, success=None, fail=boundFunction(self.errorLoad, title))
			if data:
				data = ensure_str(data)
				id = findall(r'<seriesid>(.*?)</seriesid>.*?<SeriesName>(.*?)</SeriesName>', data, S)
				if id:
					for each in id:
						if finish:
							break
						m_cover = each[0]
						m_title = each[1]
						if not m_cover or m_cover in coverlist or '403:' in m_title:
							continue
						coverlist.append(m_cover)
						if coverrange == 1:
							x = standardcover
							tvdb_url = f"https://artworks.thetvdb.com/banners/posters/{str(m_cover)}-{x}.jpg"
							if x > 1 and not urlExist(tvdb_url):
								x = 1
								tvdb_url = f"https://artworks.thetvdb.com/banners/posters/{str(m_cover)}-{x}.jpg"
							if urlExist(tvdb_url):
								self.cover_count += 1
								templist.append(self.showCoverlist(m_title, tvdb_url, self.o_path, f"tvdb: cover-{x} : "))
						else:
							x = 0
							while True:
								x += 1
								tvdb_url = f"https://artworks.thetvdb.com/banners/posters/{str(m_cover)}-{x}.jpg"
								if x > 1 and (coverrange and x > coverrange or not urlExist(tvdb_url)):
									break
								self.cover_count += 1
								templist.append(self.showCoverlist(m_title, tvdb_url, self.o_path, f"tvdb: cover-{x} : "))
						if siteresults and len(coverlist) >= siteresults:
							finish = True
							break
		self.menulist.extend(templist)
		if not templist:
			#self["info"].setText(_("Nothing found for %s") % title)
			print(f"EMC TVDB: keine infos gefunden - {title}")
		self.search_done()

	@defer.inlineCallbacks
	def searchimdb(self, title):
		print(f"EMC IMDB: Cover Select - {title}")
		templist = []
		coverlist = []
		coversize = config.EMC.imdb.preferred_coversize.value.replace('w', 'SX')
		finish = False
		siteresults = int(config.EMC.imdb.singlesearch_siteresults.value)
		part = getSearchList(title, config.EMC.imdb.singlesearch_filter.value)
		for item in part:
			if finish:
				break
			url = f'https://m.imdb.com/find?q={quote(str(item))}'
			headers = {"User-Agent": choice(agents)}
			data = yield deferToThread(GetPage, url, headers=headers, success=None, fail=boundFunction(self.errorLoad, title))
#			data = yield GetPage(url, headers=headers, success=None, fail=boundFunction(self.errorLoad, title))
			if data:
				data = ensure_str(data)
				bild = findall(r"<div class=\"ipc-media.*?<img.*?src=\"https://m.media-amazon.com/images(.*?)(?:V1|.png).*?<a class=\"ipc-metadata-list-summary-item__t\".*?>(.*?)</a>", data, S)
				if bild:
					for each in bild:
						m_cover = each[0]
						m_title = each[1].strip()
						if "/S/sash/" in m_cover:
							continue
						elif m_cover in coverlist:
							continue
						coverlist.append(m_cover)
						self.cover_count += 1
						imdb_url = f"https://m.media-amazon.com/images{str(m_cover)}V1_{coversize}.jpg"
						templist.append(self.showCoverlist(m_title, imdb_url, self.o_path, "imdb: "))
						if siteresults and len(coverlist) >= siteresults:
							finish = True
							break
		templist.sort()
		self.menulist.extend(templist)
		if not templist:
			#self["info"].setText(_("Nothing found for %s") % title)
			print(f"EMC TMDB: keine infos gefunden - {title}")
		self.search_done()

	def errorLoad(self, error, title):
		print(f"EMC keine daten zu {title} gefunden.")
		print(error)

	def search_done(self):
		self["menulist"].l.setList(self.menulist)
		self["menulist"].l.setItemHeight(self.itemHeight)
		self.check = True
		self.showInfo()
		self["info"].setText((_("found") + " %s " + _("covers in") + " %.1f " + _("sec")) % (self.cover_count, (time() - self.einzel_start_time)))

	def showInfo(self):
		if self.check and self.menulist:
			m_title = self["menulist"].getCurrent()[0][0]
			m_url = self["menulist"].getCurrent()[0][1]
			if m_url:
				#m_url = findall(r'(.*?)\.', m_url)
				#extra_imdb_convert = "._V1_SX320.jpg"
				#m_url = "https://ia.media-imdb.com/images/%s%s" % (m_url[0], extra_imdb_convert)
				print(f"EMC iMDB: Download Poster - {m_url}")
				try:
					req = session()
					headers = {"User-Agent": choice(agents)}
					r = req.get(m_url, headers=headers)
					f = open(self.path, 'wb')
					for chunk in r.iter_content(chunk_size=512 * 1024):
						if chunk:
							f.write(chunk)
					f.close()
					if exists(self.path):
						self.poster_resize(self.path, m_title)
					else:
						print(f"EMC iMDB: No url found for - {m_title}")
				except:
					pass
			else:
				print(f"EMC iMDB: No url found for - {m_title}")

	def poster_resize(self, poster_path, m_title):
		self.m_title = m_title
		self["poster"].instance.setPixmap(gPixmapPtr())
		self["poster"].hide()
		size = self["poster"].instance.size()
		if self.picload:
			self.picload.setPara((size.width(), size.height(), self.framebufferscale[0], self.framebufferscale[1], False, 1, "#00000000"))
			result = self.picload.startDecode(poster_path, 0, 0, False)
			if result == 0:
				ptr = self.picload.getData()
				if ptr is not None:
					print(f"EMC iMDB: Load Poster - {self.m_title}")
					self["poster"].instance.setPixmap(ptr)
					self["poster"].show()

	def exit(self):
		if self.picload:
			del self.picload
		self.check = False
		self.close(False)

	def ok(self, choose=False):
		movie_homepath = realpath(config.EMC.movie_homepath.value)
		if choose:
			self.chooseDirectory(movie_homepath)
		if self.check and self.menulist:
			try:
				move(self.path, self.o_path)
				print(f"EMC iMDB: mv poster to real path - {self.path} {self.o_path}")
				self.check = False
				self.close(True)
			except Exception as e:
				print(f'[EMCCoverSearch] save Cover execute get failed: {str(e)}')
				try:
					self.session.openWithCallback(self.saveCoverHomepath, MessageBox, _("Can not save " + self.o_path + " !\n Save Cover now in " + movie_homepath + " ?"), MessageBox.TYPE_YESNO, 10)
				except Exception as e:
					print(f'[EMCCoverSearch] save Cover in homepath execute get failed: {str(e)}')

	def saveCoverHomepath(self, result):
		if result:
			movie_homepath = realpath(config.EMC.movie_homepath.value)
			try:
				move(self.path, movie_homepath + "/" + self.o_path.replace(self.o_path[:-len(self.o_path) + self.o_path.rfind('/') + 1], ''))
				self.check = False
				self.close(True)
			except Exception as e:
				print(f'[EMCCoverSearch] saveCoverHomepath execute get failed: {str(e)}')
				try:
					self.session.openWithCallback(self.chooseCallback, MessageBox, _("Can not save Cover in " + movie_homepath + " !\n\n Now you can select another folder to save the Cover."), MessageBox.TYPE_YESNO, 10)
				except Exception as e:
					print(f'[EMCCoverSearch] save Cover get failed: {str(e)}')
		else:
			self.check = False
			self.close(False)

	def chooseCallback(self, result):
		if result:
			self.check = False
			self.ok(True)
		else:
			self.check = False
			self.close(False)

	def chooseDirectory(self, choosePath):
		if choosePath is not None:
			self.session.openWithCallback(
					self.moveCoverTo,
					LocationBox,
						windowTitle=_("Move Cover to:"),
						text=_("Choose directory"),
						currDir=str(choosePath) + "/",
						bookmarks=config.movielist.videodirs,
						autoAdd=False,
						editDir=True,
						inhibitDirs=["/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/proc", "/run", "/sbin", "/sys", "/usr", "/var"],
						minFree=100)

	def moveCoverTo(self, targetPath):
		if targetPath is not None:
			try:
				move(self.path, targetPath + "/" + self.o_path.replace(self.o_path[:-len(self.o_path) + self.o_path.rfind('/') + 1], ''))
				self.check = False
				self.close(True)
			except Exception as e:
				print(f'[EMCCoverSearch] moveCoverTo execute get failed: {str(e)}')
				self.chooseDirectory(targetPath)
		else:
			self.check = False
			self.close(False)

	def showCoverlist(self, title, url, path, art):
		res = [(title, url, path)]
		title = art + title
		gF = 6 if getDesktop(0).size().width() == 1920 else 4
		h = self.itemHeight
		w = self.listWidth - 15 if self.cover_count * h > self.listHeight else self.listWidth  # place for scrollbar
		res.append(MultiContentEntryText(pos=(0, 0), size=(w, h), font=gF, text=title, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER))
		return res
