from . import _, defaultlang
from os import remove
from re import match, sub, IGNORECASE
from requests import get, exceptions
from shutil import copy2
from six import ensure_binary
from twisted.internet.reactor import callInThread
from enigma import ePicLoad, eTimer, getDesktop
from Components.config import config, ConfigSubsection, ConfigSelection, ConfigYesNo, ConfigSelectionNumber
from Components.ActionMap import HelpableActionMap
from Components.AVSwitch import AVSwitch
from Components.MenuList import MenuList
from Components.Label import Label
from Components.ProgressBar import ProgressBar
from Components.Pixmap import Pixmap
from Components.ScrollLabel import ScrollLabel
from Screens.Screen import Screen
from Screens.Setup import Setup
from Screens.MessageBox import MessageBox
from Tools.Directories import fileExists
from .MovieCenter import getMovieNameWithoutExt, getMovieNameWithoutPhrases, getNoPosterPath
import tmdbsimple as tmdb

# Cover
config.EMC.movieinfo = ConfigSubsection()
config.EMC.movieinfo.language = ConfigSelection(default=defaultlang, choices=[('en', _('English')), ('de', _('German')), ('it', _('Italian')), ('es', _('Spanish')), ('fr', _('French')), ('pt', _('Portuguese')), ('cs', _('Czech'))])
config.EMC.movieinfo.ldruntime = ConfigSelection(default='1', choices=[('1', _('Yes')), ('0', _('No'))])
config.EMC.movieinfo.ldcountries = ConfigSelection(default='1', choices=[('1', _('Yes')), ('0', _('No'))])
config.EMC.movieinfo.ldreleasedate = ConfigSelection(default='1', choices=[('1', _('Yes')), ('0', _('No'))])
config.EMC.movieinfo.ldvote = ConfigSelection(default='1', choices=[('1', _('Yes')), ('0', _('No'))])
config.EMC.movieinfo.ldgenre = ConfigSelection(default='1', choices=[('1', _('Yes')), ('0', _('No'))])
config.EMC.movieinfo.coversave = ConfigYesNo(default=False)
config.EMC.movieinfo.coversize = ConfigSelection(default="w185", choices=["w92", "w185", "w500", "original"])
config.EMC.movieinfo.cover_delay = ConfigSelectionNumber(50, 60000, 50, default=500)

sz_w = getDesktop(0).size().width()


def getMovieList(moviename):
	lang = config.EMC.movieinfo.language.value
	movielist = []
	m = match(r'^(.*) \((19\d\d|20\d\d)\)$', moviename)
	year = None
	text = moviename
	if m:
		text, year = m.groups()
	search = tmdb.Search()
	json_data = search.multi(query=text, language=lang, year=year) if year else search.multi(query=text, language=lang)
	for result in json_data["results"]:
		media = result.get("media_type", "")
		id = result.get("id", "")
		title = result.get("title", result.get("name", ""))
		if media == "movie":
			movielist.append((f"{title} - {_('Movies')}", id, "movie"))
		else:
			movielist.append((f"{title} - {_('TV Shows')}", id, "tvshows"))
	return movielist, len(movielist)


def getMovieInfo(movieID, cat, getAll=True, onlyPoster=False):
	lang = config.EMC.movieinfo.language.value
	posterUrl = None
	MI = {}
	try:
		movie = tmdb.Movies(int(movieID)) if cat == "movie" else tmdb.TV(int(movieID))
		MI = movie.info(language=lang)
		print(f'[EMC] MovieInfo MI:\n{str(MI)}\n')
	except Exception as e:
		print(f'[EMC] MovieInfo getMovieInfo exception failure: {str(e)}')
		return None
	if not MI:
		return None
	posterUrl = MI["poster_path"]

	if posterUrl is not None:
		getTempCover(posterUrl)
	if onlyPoster:
		return

	blurb = MI["overview"]

	if cat == "movie":
		if config.EMC.movieinfo.ldruntime.value == '1':
			runtime = MI["runtime"]
			if runtime == 0:
				runtime = ""
			runtime = str(runtime)
		else:
			runtime = ""
		releasedate = MI["release_date"] if config.EMC.movieinfo.ldreleasedate.value == '1' else ""
		vote = str(MI["vote_average"]) if config.EMC.movieinfo.ldvote.value == '1' else ""

		if config.EMC.movieinfo.ldgenre.value == '1':
			genrelist = MI["genres"]
			genres = ""
			for i in genrelist:
				genres = i["name"] if genres == "" else f"{genres}, {i['name']}"
		else:
			genres = ""

		if config.EMC.movieinfo.ldcountries.value == '1':
			countrylist = MI["production_countries"]
			countries = ""
			for i in countrylist:
				countries = i["name"] if countries == "" else countries + ", " + i["name"]
		else:
			countries = ""

		txt = (_("Content:") + " " + blurb + "\n\n" + _("Runtime:") + " " + runtime + " " + _("Minutes") + "\n" + _("Genre:") + " " + genres + "\n" + _("Production Countries:") + " " + countries + "\n" + _("Release Date:") + " " + releasedate + "\n" + _("Vote:") + " " + vote + "\n")

		if getAll:
			return txt
		else:
			getTempTxt(txt)
			return blurb, runtime, genres, countries, releasedate, vote

	if cat == "tvshows":
		if config.EMC.movieinfo.ldruntime.value == '1':
			runtime = MI["episode_run_time"]
			if runtime and isinstance(runtime, list):
				runtime = runtime[0]
			if runtime == 0:
				runtime = _("unknown")
			runtime = str(runtime)
		else:
			runtime = ""
		releasedate = MI["first_air_date"] if config.EMC.movieinfo.ldreleasedate.value == '1' else ""
		vote = str(MI["vote_average"]) if config.EMC.movieinfo.ldvote.value == '1' else ""

		if config.EMC.movieinfo.ldgenre.value == '1':
			genrelist = MI["genres"]
			genres = ""
			for i in genrelist:
				genres = i["name"] if genres == "" else f"{genres}, {i['name']}"
		else:
			genres = ""

		if config.EMC.movieinfo.ldcountries.value == '1':
			countrylist = MI["origin_country"]
			countries = ""
			for i in countrylist:
				countries = i if countries == "" else f"{countries}, {i}"
		else:
			countries = ""

		txt = (_("Content:") + " " + blurb + "\n\n" + _("Runtime:") + " " + runtime + " " + _("Minutes") + "\n" + _("Genre:") + " " + genres + "\n" + _("Production Countries:") + " " + countries + "\n" + _("Release Date:") + " " + releasedate + "\n" + _("Vote:") + " " + vote + "\n")

		if getAll:
			return txt
		else:
			getTempTxt(txt)
			return blurb, runtime, genres, countries, releasedate, vote


def getTempTxt(txt):
	if txt is not None:
		try:
			txtpath = "/tmp/previewTxt.txt"
			open(txtpath, 'w').write(txt)
		except Exception as e:
			print(f'[EMC] MovieInfo getTempTxt exception failure: {str(e)}')


def getTempCover(posterUrl):
	if posterUrl is not None:
		try:
			if fileExists("/tmp/previewCover.jpg"):
				remove("/tmp/previewCover.jpg")
			coverpath = "/tmp/previewCover.jpg"
			url = f"https://image.tmdb.org/t/p/{config.EMC.movieinfo.coversize.value}{posterUrl}"
			callInThread(DownloadPage, url, coverpath, None, fail=dataError)
		except Exception as e:
			print(f'[EMC] MovieInfo getTempCover exception failure: {str(e)}')


def DownloadPage(link, file, success, fail=None):
	link = link.encode('ascii', 'xmlcharrefreplace').decode().replace(' ', '%20').replace('\n', '')
	try:
		response = get(ensure_binary(link), timeout=(3.05, 6))
		response.raise_for_status()
		with open(file, "wb") as f:
			f.write(response.content)
		if success is not None:
			success(file)
	except exceptions.RequestException as error:
		if fail is not None:
			fail(error)


def dataError(error):
	print(f"[EMC] MovieInfo ERROR: {error}")


class MovieInfoTMDb(Screen):
	if sz_w == 1920:
		skin = """
		<screen name="MovieInfoTMDb" position="center,170" size="1200,820" title="Movie Information TMDb">
		<widget name="movie_name" position="10,5" size="1180,80" font="Regular;35" halign="center" valign="center" foregroundColor="yellow"/>
		<eLabel backgroundColor="#818181" position="10,90" size="1180,1" />
		<widget name="previewlist" enableWrapAround="1" position="340,100" size="850,630" itemHeight="45" scrollbarMode="showOnDemand" />
		<widget name="previewcover" position="20,100" size="300,451" alphatest="blend"/>
		<widget name="contenttxt" position="340,100" size="850,460" font="Regular;30" />
		<widget name="runtime" position="20,590" size="160,35" font="Regular;28" foregroundColor="#000066FF" />
		<widget name="runtimetxt" position="190,590" size="330,35" font="Regular;28" />
		<widget name="genre" position="20,640" size="160,35" font="Regular;28" foregroundColor="#000066FF" />
		<widget name="genretxt" position="190,640" size="330,35" font="Regular;28" />
		<widget name="country" position="550,590" size="290,35" font="Regular;28" foregroundColor="#000066FF" />
		<widget name="countrytxt" position="850,590" size="340,35" font="Regular;28" />
		<widget name="release" position="550,640" size="290,35" font="Regular;28" foregroundColor="#000066FF" />
		<widget name="releasetxt" position="850,640" size="340,35" font="Regular;28" />
		<widget name="rating" position="20,690" size="160,35" font="Regular;28" foregroundColor="#000066FF" />
		<widget name="ratingtxt" position="190,690" size="330,35" font="Regular;28" />
		<widget name="starsbg" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img_fhd/starsbar_empty.png" position="550,690" size="300,30" alphatest="blend"/>
		<widget name="stars" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img_fhd/starsbar_filled.png" position="550,690" size="300,30" transparent="1" zPosition="1"/>
		<eLabel backgroundColor="#818181" position="10,740" size="1180,1" />
		<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img_fhd/menu.png" position="10,770" size="80,40" alphatest="blend"/>
		<widget name="setup" position="110,772" size="380,40" font="Regular;30" valign="center" />
		<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img_fhd/ok.png" position="510,770" size="80,40" zPosition="1" alphatest="blend"/>
		<widget name="key_green" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img_fhd/key_green.png" position="510,770" size="80,40" zPosition="2" alphatest="blend"/>
		<widget name="save" position="620,772" size="290,40" font="Regular;30" valign="center" />
		</screen>"""
	else:
		skin = """
		<screen name="MovieInfoTMDb" position="center,80" size="1200,610" title="Movie Information TMDb">
		<widget name="movie_name" position="10,5" size="1180,55" font="Regular;24" valign="center" halign="center" foregroundColor="yellow"/>
		<eLabel backgroundColor="#818181" position="10,70" size="1180,1" />
		<widget name="previewcover" position="20,80" size="220,330" alphatest="blend"/>
		<widget enableWrapAround="1" name="previewlist" position="270,80" size="920,330" itemHeight="30" scrollbarMode="showOnDemand" />
		<widget name="contenttxt" position="270,80" size="920,330" font="Regular;21" />
		<widget name="runtime" position="20,450" size="120,25" font="Regular;20" foregroundColor="#000066FF" />
		<widget name="runtimetxt" position="160,450" size="360,25" font="Regular;20" />
		<widget name="genre" position="20,480" size="120,25" font="Regular;20" foregroundColor="#000066FF" />
		<widget name="genretxt" position="160,480" size="360,25" font="Regular;20" />
		<widget name="country" position="600,450" size="200,25" font="Regular;20" foregroundColor="#000066FF" />
		<widget name="countrytxt" position="820,450" size="360,25" font="Regular;20" />
		<widget name="release" position="600,480" size="200,25" font="Regular;20" foregroundColor="#000066FF" />
		<widget name="releasetxt" position="820,480" size="360,25" font="Regular;20" />
		<widget name="rating" position="20,510" size="120,25" font="Regular;20" foregroundColor="#000066FF" />
		<widget name="ratingtxt" position="160,510" size="360,25" font="Regular;20" />
		<widget name="starsbg" position="595,510" size="250,25" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img/starsbar_empty.png" alphatest="blend"/>
		<widget name="stars" position="595,510" size="250,25" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img/starsbar_filled.png" transparent="1" zPosition="1"/>
		<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img/menu.png" position="20,570" size="60,30" alphatest="blend"/>
		<widget name="setup" position="100,571" size="200,30" font="Regular;22" valign="center" />
		<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img/ok.png" position="320,570" size="60,30" zPosition="1" alphatest="blend"/>
		<widget name="key_green" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img/key_green.png" position="320,570" size="60,30" zPosition="2" alphatest="blend"/>
		<widget name="save" position="400,571" size="200,30" font="Regular;22" valign="center" />
		</screen>"""

# page 0 = details
# page 1 = list
	def __init__(self, session, moviename, spath=None):
		Screen.__init__(self, session)
		#self.session = session
		self.moviename = getMovieNameWithoutExt(moviename)
		moviename = getMovieNameWithoutPhrases(self.moviename)
		self.movielist = None
		self.spath = spath
		self["previewcover"] = Pixmap()
		self.picload = ePicLoad()
		self.picload.PictureData.get().append(self.showPreviewCoverCB)
		self.previewTimer = eTimer()
		self.previewTimer.callback.append(self.showPreviewCover)
		self.selectionTimer = eTimer()
		self.selectionTimer.callback.append(self.updateSelection)
		self["previewlist"] = MenuList([])
		self.page = 0
		self.id = None
		self.cat = None
		self["contenttxt"] = ScrollLabel()
		self["runtime"] = Label("")
		self["runtimetxt"] = Label("")
		self["genre"] = Label("")
		self["genretxt"] = Label("")
		self["country"] = Label("")
		self["countrytxt"] = Label("")
		self["release"] = Label("")
		self["releasetxt"] = Label("")
		self["rating"] = Label("")
		self["ratingtxt"] = Label("")
		self["stars"] = ProgressBar()
		self["starsbg"] = Pixmap()
		self["stars"].hide()
		self["starsbg"].hide()
		self["setup"] = Label(_("Setup"))
		self["key_menu"] = Pixmap()
		self["save"] = Label(_("Save"))
		self["key_green"] = Pixmap()
		self.ratingstars = -1
		tmdb.API_KEY = bytes.fromhex("38373839636664336662616237646363663132363963336437643836376166666"[:-1]).decode('utf-8')
		self.movielist = getMovieList(moviename)
		if self.movielist is not None:
			self["previewlist"] = MenuList(self.movielist[0])
			if self.movielist[1] > 1:
				self.page = 1
				self["movie_name"] = Label(_("Search results for:") + "   " + moviename)
			else:
				self.page = 0
				sel = self["previewlist"].l.getCurrentSelection()
				if sel is not None:
					preview = getMovieInfo(sel[1], sel[2])
					if preview is not None:
						self.id = sel[1]
						self.cat = sel[2]
				self["previewlist"].hide()
				self["movie_name"] = Label(_("Movie Information Preview for:") + "   " + moviename)
		else:
			self["movie_name"] = Label(_("Search results for:") + "   " + moviename)
			self["contenttxt"].setText(_("Nothing was found !"))

		self.file_format = r"(\.ts|\.avi|\.mkv|\.divx|\.f4v|\.flv|\.img|\.iso|\.m2ts|\.m4v|\.mov|\.mp4|\.mpeg|\.mpg|\.mts|\.vob|\.asf|\.wmv|.\stream|.\webm)"
		# for file-operations
		self.txtsaved = False
		self.jpgsaved = False
		self.mpath = None
		self.onLayoutFinish.append(self.layoutFinished)
		self["actions"] = HelpableActionMap(self, "EMCMovieInfo",
		{
			"EMCEXIT": self.exit,
			"EMCUp": self.pageUp,
			"EMCDown": self.pageDown,
			"EMCOK": self.ok,
			"EMCGreen": self.save,
			"EMCMenu": self.setup,
			#"EMCINFO":	self.info,
			#"EMCRed":	self.red,
		}, -1)
		self["previewlist"].onSelectionChanged.append(self.selectionChanged)

	def selectionChanged(self):
		if self.page == 1:
			self.selectionTimer.start(int(config.EMC.movieinfo.cover_delay.value), True)

	def updateSelection(self):
		if self.page == 1:
			sel = self["previewlist"].l.getCurrentSelection()
			if sel is not None:
				getMovieInfo(sel[1], sel[2], False, True)
				self.previewTimer.start(int(config.EMC.movieinfo.cover_delay.value), True)

	def layoutFinished(self):
		self.setTitle(_("Movie Information TMDb"))
		self.switchPage()

	def switchPage(self, id=None, cat=None):
		if self.page == 1:
			self["previewlist"].show()
			self.selectionChanged()
			self["runtime"].hide()
			self["genre"].hide()
			self["country"].hide()
			self["release"].hide()
			self["rating"].hide()
			self["contenttxt"].hide()
			self["runtimetxt"].hide()
			self["genretxt"].hide()
			self["countrytxt"].hide()
			self["releasetxt"].hide()
			self["ratingtxt"].hide()
			self["stars"].hide()
			self["starsbg"].hide()
			self["save"].hide()
			self["key_green"].hide()
		else:
			self["runtime"].setText(_("Runtime:"))
			self["genre"].setText(_("Genre:"))
			self["country"].setText(_("Production Countries:"))
			self["release"].setText(_("Release Date:"))
			self["rating"].setText(_("Vote:"))
			if id is None:
				if self.id is not None:
					id = self.id
			if cat is None:
				if self.cat is not None:
					cat = self.cat
			if id is not None or cat is not None:
				content, runtime, genres, countries, release, vote = getMovieInfo(id, cat, False)
				self["runtime"].show()
				self["genre"].show()
				self["country"].show()
				self["release"].show()
				self["rating"].show()
				self["contenttxt"].show()
				self["runtimetxt"].show()
				self["genretxt"].show()
				self["countrytxt"].show()
				self["releasetxt"].show()
				self["ratingtxt"].show()
				self["contenttxt"].setText(content)
				if runtime != "":
					self["runtimetxt"].setText(f"{runtime} {_('Minutes')}")
				else:
					self["runtimetxt"].setText(runtime)
				self["genretxt"].setText(genres)
				self["countrytxt"].setText(countries)
				self["releasetxt"].setText(release)
				self["starsbg"].show()
				if vote:
					self["ratingtxt"].setText(vote.replace('\n', '') + " / 10")
					self.ratingstars = int(10 * round(float(vote.replace(',', '.')), 1))
					if self.ratingstars > 0:
						self["stars"].show()
						self["stars"].setValue(self.ratingstars)
					else:
						self["stars"].hide()
				else:
					self["ratingtxt"].setText(" 0 / 10")
					self["stars"].hide()
				self["save"].show()
				self["key_green"].show()
				self.previewTimer.start(int(config.EMC.movieinfo.cover_delay.value), True)

	def showMsg(self, askNo=False):
		txtpath = f"{self.mpath}.txt"
		coverpath = f"{self.mpath}.jpg"
		msg = ""
		if self.txtsaved and self.jpgsaved:
			msg = (_('Movie Information and Cover downloaded successfully!'))
		elif self.txtsaved and not self.jpgsaved:
			if config.EMC.movieinfo.coversave.value:
				msg = (_('Movie Information downloaded successfully!')) if askNo else (_('Movie Information downloaded successfully!\n\nCan not write Movie Cover File\n\n%s') % coverpath)
			else:
				msg = (_('Movie Information downloaded successfully!'))
		elif self.jpgsaved and not self.txtsaved:
			msg = (_('Movie Cover downloaded successfully!\n\nCan not write Movie Information File\n\n%s') % txtpath)
		elif not self.jpgsaved and not self.txtsaved:
			msg = (_('Can not write Movie Information and Cover File\n\n%(info)s\n%(file)s') % {'info': txtpath, 'file': coverpath})
		elif not self.txtsaved and not config.EMC.movieinfo.coversave.value:
			msg = (_('Can not write Movie Information File\n\n%s') % txtpath)
		self.session.open(MessageBox, msg, MessageBox.TYPE_INFO, 5)

	def save(self):
		if self.page == 0 and self.spath is not None:
			self.txtsaved = False
			self.mpath = sub(self.file_format + "$", '.jpg', self.spath, flags=IGNORECASE)
			try:
				txtpath = f"{self.mpath}.txt"
				if fileExists("/tmp/previewTxt.txt"):
					copy2("/tmp/previewTxt.txt", txtpath)
					self.txtsaved = True
			except Exception as e:
				print(f'[EMC] MovieInfo saveTxt exception failure: {str(e)}')

			if config.EMC.movieinfo.coversave.value:
				self.getPoster()
			else:
				self.showMsg()

	def getPoster(self):
		coverpath = f"{self.mpath}.jpg"
		if fileExists(coverpath):
			self.session.openWithCallback(self.posterCallback, MessageBox, _("Cover %s exists!\n\nDo you want to replace the existing cover?") % coverpath, MessageBox.TYPE_YESNO)
		else:
			self.savePoster()

	def posterCallback(self, result):
		if result:
			coverpath = f"{self.mpath}.jpg"
			try:
				if fileExists(coverpath):
					remove(coverpath)
			except Exception as e:
				print(f'[EMC] MovieInfo posterCallback exception failure: {str(e)}')
			self.savePoster()
		else:
			self.showMsg(True)

	def savePoster(self):
		self.jpgsaved = False
		try:
			coverpath = f"{self.mpath}.jpg"
			if fileExists("/tmp/previewCover.jpg"):
				copy2("/tmp/previewCover.jpg", coverpath)
				self.jpgsaved = True
		except Exception as e:
			print(f'[EMC] MovieInfo savePoster exception failure: {str(e)}')

		self.showMsg()

	def ok(self):
		if self.page != 0:
			sel = self["previewlist"].l.getCurrentSelection()
			if sel is not None:
				self["previewlist"].hide()
				self.page = 0
				self["movie_name"].setText(_("Movie Information Preview for:") + "   " + self.moviename)
				self.switchPage(sel[1], sel[2])

	def pageUp(self):
		if self.page == 0:
			self["contenttxt"].pageUp()
		if self.page == 1:
			if self.selectionTimer.isActive():
				self.selectionTimer.stop()
			self["previewlist"].up()

	def pageDown(self):
		if self.page == 0:
			self["contenttxt"].pageDown()
		if self.page == 1:
			if self.selectionTimer.isActive():
				self.selectionTimer.stop()
			self["previewlist"].down()

	def showPreviewCoverCB(self, picInfo=None):
		ptr = self.picload.getData()
		if ptr is not None:
			self["previewcover"].instance.setPixmap(ptr)
			if self.page == 0:
				self["previewcover"].show()
		else:
			self["previewcover"].hide()

	def showPreviewCover(self):
		previewpath = "/tmp/previewCover.jpg" if fileExists("/tmp/previewCover.jpg") else getNoPosterPath()  # "/usr/lib/enigma2/python/Plugins/Extensions/EnhancedMovieCenter/img/no_poster.png"
		sc = AVSwitch().getFramebufferScale()
		self.picload.setPara((self["previewcover"].instance.size().width(), self["previewcover"].instance.size().height(), sc[0], sc[1], False, 1, "#00000000"))
		self.picload.startDecode(previewpath)

	def exit(self):
		if self.movielist is not None:
			if self.page == 0 and self.movielist[1] > 1:
				self.page = 1
				self["movie_name"].setText(_("Search results for:") + "   " + self.moviename)
				self.switchPage()
			else:
				if fileExists("/tmp/previewCover.jpg"):
					remove("/tmp/previewCover.jpg")
				if fileExists("/tmp/previewTxt.txt"):
					remove("/tmp/previewTxt.txt")
				if self.selectionTimer.isActive():
					self.selectionTimer.stop()
				if self.previewTimer.isActive():
					self.previewTimer.stop()
				self.close()
		else:
			self.close()

	def setup(self):
		self.session.open(MovieInfoSetup)


class MovieInfoSetup(Setup):
	def __init__(self, session):
		Setup.__init__(self, session, "MovieInfoSetup", plugin="Extensions/EnhancedMovieCenter", PluginLanguageDomain="EnhancedMovieCenter")
