"""The system home screen. Python bridges existing Enigma2 session/config APIs.

Magic Box has no plugin descriptor, session-start hook or delayed launch.
Navigation, pages, caches, accounts and favorites live in eMagicBoxHome/C++.
"""
import json
from functools import partial

from enigma import addFont, ePoint, eSize, eServiceReference, eServiceCenter, eMagicBoxTKGS, eDVBDB, eTimer, getDesktop, iPlayableService, iServiceInformation
from Components.ServiceEventTracker import ServiceEventTracker
from Components.MagicBoxHome import MagicBoxHome as HomeWidget
from Components.VideoWindow import VideoWindow
from Screens.InfoBar import InfoBar
from Screens.Menu import Menu, mdom


class MagicBoxHome(InfoBar):
	# Tuning failures belong in the native video pane; ZapError hides InfoBar.
	SHOW_SERVICE_ERROR_POPUP = False
	SHOW_BUFFERING_INDICATOR = False
	skin = '''<screen name="MagicBoxHome" position="0,0" size="1280,720" resolution="1280,720" flags="wfNoBorder" backgroundColor="#ff000000">
		<widget name="home" position="0,0" size="1280,720" zPosition="1" />
		<widget name="magicbox_video" position="603,193" size="640,362" zPosition="0" backgroundColor="#ff000000" />
	</screen>'''

	def __init__(self, session):
		addFont('/usr/share/enigma2/magicbox/assets/RobotoCondensed.ttf', 'MagicBox', 100, False)
		addFont('/usr/share/fonts/DejaVuSans.ttf', 'DejaVuSans', 100, False)
		InfoBar.__init__(self, session)
		self.skinName = 'MagicBoxHome'
		self['home'] = HomeWidget(self.requested)
		size = getDesktop(0).size()
		self['magicbox_video'] = VideoWindow(decoder=0, fb_width=size.width(), fb_height=size.height())
		self._settings = None
		self._fullscreen = False
		self._zap_hold_previous = None
		self.onClose.append(partial(self.setZapHold, False))
		self._playing = None
		self._video_ready = False
		self._account = None
		self._preview_generation = 0
		self._preview_pending = None
		self._preview_owned = None
		self._connecting_reference = None
		self._preview_start = eTimer()
		self._preview_start.callback.append(self.startPreview)
		self.onClose.append(self._preview_start.stop)
		self.tkgs = eMagicBoxTKGS()
		self.tkgs.changed.get().append(self.tkgsChanged)
		self._tkgs_auto = eTimer()
		self._tkgs_auto.callback.append(self.tkgsAutomatic)
		self._tkgs_auto.start(60000)
		self.onClose.append(self._tkgs_auto.stop)
		self.onLayoutFinish.append(self.ready)
		self.onExecBegin.append(self.resumed)
		self.onShow.append(self.resumed)
		self._video_events = ServiceEventTracker(screen=self, eventmap={
			iPlayableService.evUpdatedInfo: self.videoChanged,
			iPlayableService.evGstreamerPlayStarted: self.videoChanged,
			iPlayableService.evVideoSizeChanged: self.videoChanged,
			iPlayableService.evTuneFailed: self.videoFailed,
			iPlayableService.evEOF: self.videoFailed})

	def startHideTimer(self):
		# This object is the permanent home, so InfoBar's auto-hide is inappropriate.
		if hasattr(self, 'hideTimer'):
			self.hideTimer.stop()

	def showMovies(self):
		# Video opens the native Media tab; EMC owns playback after selection.
		self['home'].instance.setTab(2)

	def doTimerHide(self):
		self.hideTimer.stop()

	def ready(self):
		self.hideTimer.stop()
		# Prepare native Settings data and root screen modules before accepting
		# navigation, so the first visit has the same cost as later visits.
		self.prepareSettings()
		from importlib import import_module
		for screen in mdom.getroot().findall('item/screen'):
			module = screen.get('module')
			if module:
				import_module('Screens.' + module)
		# Information is a frequently used nested page. Import its module at
		# startup; its changing system information is still collected on open.
		import_module('Screens.About')
		try:
			import_module('Screens.MagicBoxMedia')
			# Construct the media pipeline once without starting a service. This
			# keeps its lazy initialization out of the first file-open transition.
			warm = eServiceCenter.getInstance().play(eServiceReference(eServiceReference.idServiceMP3, 0, '/dev/null'))
			del warm
		except ImportError:
			pass # An incomplete development installation still boots its home.
		self.resumed()
		self.videoChanged()

	def resumed(self):
		home = self['home'].instance
		if home is not None:
			home.setActive(self.session.current_dialog is self)
			home.invalidate()
		self.hideTimer.stop()

	def requested(self, action):
		home = self['home'].instance
		if action in (0, 1):
			if action == 1:
				self._preview_generation += 1
				self._preview_pending = None
				self._preview_start.stop()
				self._preview_owned = None
			reference = home.getService()
			if reference:
				from Components.ParentalControl import parentalControl
				ref = eServiceReference(reference)
				if action == 0 and ref.toCompareString() != self._playing and self.timeshiftEnabled():
					self['magicbox_video'].hide()
					home.setPlaybackState(False, 'Zaman kaydırma etkin. Kanalı açmak için OK tuşuna basın.')
					return
				if action == 0 and parentalControl.isProtected(ref):
					self['magicbox_video'].hide()
					home.setPlaybackState(False, 'Bu kanal PIN ile korunuyor. Açmak için OK tuşuna basın.')
					return
				play = partial(self.playReference, fullscreen=(action == 1), preview=(action == 0), generation=self._preview_generation if action == 0 else None)
				if not parentalControl.isServicePlayable(ref, play, session=self.session):
					return
				play(ref)
			else:
				self['magicbox_video'].hide()
				home.setPlaybackState(False, 'Bu kanalın DVB kaydı henüz yok. TKGS listesini veya tuner ayarlarını kontrol edin.')
				if action == 1:
					self.fullscreen(True)
		elif action == 2:
			self.prepareSettings()
		elif action == 3:
			from Screens.MagicBoxAccount import MagicBoxAccount
			self._account = self.session.open(MagicBoxAccount, home)
		elif action == 4:
			self.prepareSettings()
			if self._settings:
				self._settings.choose(home.getSelection())
				self.session.execDialog(self._settings)
				self._settings.callback = self.settingsClosed
		elif action == 5:
			self.fullscreen(False)
		elif action == 6:
			self._account = None
			home.reloadAccount()
		elif action == 7:
			from Screens.MessageBox import MessageBox
			self.session.open(MessageBox, home.getMessage(), type=MessageBox.TYPE_ERROR)
			if self._account:
				self._account['key_green'].setText('Bağlan')
		elif action == 8:
			self.refreshVideoVisibility()
		elif action == 9:
			self.playMedia(home.getService())
		elif action == 10:
			self.cancelPreview()

	def playMedia(self, path):
		import os
		from Screens.MessageBox import MessageBox
		try:
			if not os.path.isabs(path) or not os.path.isfile(path):
				raise ValueError('Medya dosyası bulunamadı.')
			from Plugins.Extensions.EnhancedMovieCenter.MovieCenter import getPlayerService
			from Screens.MagicBoxMedia import MagicBoxEMCPlayer
			from Plugins.Extensions.EnhancedMovieCenter.RecordingsControl import getRecording
			extension = os.path.splitext(path)[1].lower()
			playlist = []
			if extension in ('.m3u', '.e2pls'):
				with open(path, 'r', encoding='utf-8-sig', errors='replace') as source:
					for line in source.read(512*1024).splitlines()[:1000]:
						line = line.strip()
						if not line or line.startswith('#'):
							continue
						if extension == '.e2pls':
							entry = eServiceReference(line)
						else:
							item = line if '://' in line else os.path.normpath(os.path.join(os.path.dirname(path), line))
							entry = getPlayerService(item, os.path.basename(item), os.path.splitext(item)[1].lower())
						if entry.valid():
							playlist.append(entry)
			else:
				playlist.append(getPlayerService(path, self['home'].instance.getName(), extension))
			if not playlist:
				raise ValueError('Oynatma listesi boş.')
			for index, reference in enumerate(playlist):
				path = reference.getPath()
				# Keep the recording backend for a growing recording. Finished local
				# TS files use the same asynchronous engine as EMC's other videos.
				if reference.type == eServiceReference.idDVB and os.path.isfile(path) and not getRecording(path):
					stream = eServiceReference(eServiceReference.idServiceMP3, 0, path)
					stream.setName(reference.getName())
					playlist[index] = stream
			self.checkTimeshiftRunning(partial(self.playMediaChecked, MagicBoxEMCPlayer, playlist))
		except (ImportError, OSError, ValueError):
			self.session.open(MessageBox, 'Medya açılamadı. EMC kurulumunu ve dosyayı kontrol edin.', type=MessageBox.TYPE_ERROR)

	def playMediaChecked(self, player, playlist, allowed):
		if not allowed:
			return
		self['magicbox_video'].hide()
		self.session.openWithCallback(self.mediaClosed, player, playlist, lastservice=self.session.nav.getCurrentlyPlayingServiceReference())

	def mediaClosed(self, *result):
		# EMC's reopen flag returns here, never into its separate file browser.
		self.resumed()
		self.refreshVideoVisibility()

	def cancelPreview(self):
		self._preview_generation += 1
		self._preview_pending = None
		self._preview_start.stop()
		current = self.session.nav.getCurrentlyPlayingServiceReference()
		current = current.toCompareString() if current else None
		cancel = current and current in (self._preview_owned, self._connecting_reference)
		self._preview_owned = None
		self._connecting_reference = None
		self['magicbox_video'].hide()
		if cancel and not self.timeshiftEnabled():
			self.session.nav.stopService()
			self._playing = None
			self._video_ready = False
		home = self['home'].instance
		if home:
			home.setPlaybackState(False, '')

	def startPreview(self):
		pending, self._preview_pending = self._preview_pending, None
		if pending is None:
			return
		ref, generation = pending
		home = self['home'].instance
		selected = eServiceReference(home.getService()).toCompareString() if home and home.getService() else None
		if (generation != self._preview_generation or self.session.current_dialog is not self or self._fullscreen
			or selected != ref.toCompareString()):
			return
		if ref.toCompareString() != self._playing and self.timeshiftEnabled():
			return
		self.playCheckedReference(ref, False, True, preview=True, generation=generation)

	def playReference(self, ref, fullscreen=False, preview=False, generation=None):
		if generation is not None and generation != self._preview_generation:
			return
		if preview:
			self._preview_pending = (ref, self._preview_generation)
			self._preview_start.start(0, True)
			return
		if ref.toCompareString() != self._playing:
			self.checkTimeshiftRunning(partial(self.playCheckedReference, ref, fullscreen, generation=generation))
		else:
			self.playCheckedReference(ref, fullscreen, True)

	def playCheckedReference(self, ref, fullscreen, allowed, preview=False, generation=None):
		if not allowed or generation is not None and generation != self._preview_generation:
			return
		if fullscreen:
			self.fullscreen(True)
		if ref.toCompareString() != self._playing:
			self._preview_owned = ref.toCompareString() if preview else None
			self._connecting_reference = ref.toCompareString()
			self._video_ready = False
			self['home'].instance.setPlaybackState(False, 'Yayına bağlanılıyor…')
			if not self._fullscreen:
				self['magicbox_video'].hide()
			self.session.nav.playService(ref)
			self._playing = ref.toCompareString()
		self.refreshVideoVisibility()

	def refreshVideoVisibility(self):
		home = self['home'].instance
		reference = eServiceReference(home.getService()).toCompareString() if home and home.getTab() not in (2, 4) and home.getService() else ''
		visible = bool(self._fullscreen or self._video_ready and home.getTab() not in (2, 4) and reference and reference == self._playing)
		if reference and reference == self._playing:
			home.setPlaybackState(self._video_ready, '' if self._video_ready else 'Yayına bağlanılıyor…')
		self['magicbox_video'].show() if visible else self['magicbox_video'].hide()

	def videoChanged(self):
		if not self['home'].instance:
			return
		service = self.session.nav.getCurrentService()
		reference = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		self._playing = reference.toCompareString() if reference else None
		info = service and service.info()
		ready = bool(info and info.getInfo(iServiceInformation.sVideoWidth) > 0)
		self._video_ready = ready
		if ready:
			self._connecting_reference = None
		self['home'].instance.setPlaybackState(ready, '' if ready else 'Yayın bekleniyor. Anten veya ağ bağlantısını kontrol edin.')
		self.refreshVideoVisibility()

	def videoFailed(self):
		self._video_ready = False
		if self['home'].instance:
			self['home'].instance.setPlaybackState(False, 'Yayın açılamadı. Anten veya ağ bağlantısını kontrol edin.')
		self['magicbox_video'].show() if self._fullscreen else self['magicbox_video'].hide()

	def setZapHold(self, enabled):
		# This is a temporary hardware mode, never a saved receiver preference.
		if enabled:
			if self._zap_hold_previous is not None:
				return
			from Components.SystemInfo import BoxInfo
			path = BoxInfo.getItem('ZapMode')
			if not isinstance(path, str):
				return
			try:
				with open(path) as stream:
					previous = stream.read().strip()
				with open(path + '_choices') as stream:
					choices = stream.read().split()
				if 'hold' not in choices:
					return
				with open(path, 'w') as stream:
					stream.write('hold')
				self._zap_hold_previous = (path, previous)
			except OSError:
				pass
		elif self._zap_hold_previous is not None:
			path, previous = self._zap_hold_previous
			self._zap_hold_previous = None
			try:
				with open(path, 'w') as stream:
					stream.write(previous)
			except OSError:
				pass

	def fullscreen(self, enabled):
		reference = eServiceReference(self['home'].instance.getService())
		self.setZapHold(enabled and reference.type == eServiceReference.idServiceMP3 and reference.getPath().lower().startswith(('http://', 'https://')))
		self._fullscreen = enabled
		self['home'].instance.setFullscreen(enabled)
		video = self['magicbox_video'].instance
		size = getDesktop(0).size()
		video.move(ePoint(0, 0) if enabled else ePoint(603 * size.width() // 1280, 193 * size.height() // 720))
		video.resize(size if enabled else eSize(640 * size.width() // 1280, 362 * size.height() // 720))
		if enabled:
			self['magicbox_video'].show()

	def prepareSettings(self):
		if self._settings is None:
			self._settings = self.session.instantiateDialog(MagicBoxRootAction, mdom.getroot())
			self._settings.hide()
		self._settings.createMenuList()
		self['home'].instance.setSettings(json.dumps([row[0] for row in self._settings.list], ensure_ascii=False))

	def settingsClosed(self, *result):
		self.prepareSettings()

	def tkgsChanged(self, event):
		if event == 2:
			database = eDVBDB.getInstance()
			database.reloadServicelist()
			database.reloadBouquets()
			if self['home'].instance:
				self['home'].instance.reloadTV()

	def tkgsAutomatic(self):
		from Components.NimManager import nimmanager
		from Screens.Standby import inStandby
		slots = nimmanager.getNimListForSat(420)
		if slots:
			self.tkgs.checkAutomatic(bool(inStandby), bool(self.session.nav.getRecordings()), slots[0])


class MagicBoxRootAction(Menu):
	"""Native Menu authorization/callbacks with its selected item opened directly."""
	MENU_IMAGES = False
	# C++ renders Settings. Keep its Python Menu data/authorization owner invisible.
	skin = '<screen name="MagicBoxRootAction" position="0,0" size="0,0" flags="wfNoBorder" />'

	def __init__(self, session, parent):
		Menu.__init__(self, session, parent)
		self.skinName = 'MagicBoxRootAction'
		self.index = 0
		self['menu'].master = self
		self._pin_checks = list(self.onFirstExecBegin)
		self._pending = False
		self._needs_pin = False
		self.onShown.append(self.openSelected)

	@property
	def current(self):
		return self.list[self.index] if 0 <= self.index < len(self.list) else None

	def choose(self, index):
		# Reuse the prepared root without reusing a previous PIN authorization.
		from Screens.ParentalControlSetup import ProtectedScreen
		self.onFirstExecBegin = [f for f in self.onFirstExecBegin if f not in self._pin_checks]
		before = len(self.onFirstExecBegin)
		ProtectedScreen.__init__(self)
		self._pin_checks = self.onFirstExecBegin[before:]
		from Components.config import config
		self._needs_pin = self.isProtected() and bool(config.ParentalControl.servicepin[0].value)
		self['menu'].setIndex(index)
		self._pending = True

	def openSelected(self):
		if self._pending and not self._needs_pin:
			self._pending = False
			self.okbuttonClick()

	def pinEntered(self, result):
		Menu.pinEntered(self, result)
		if result and self._pending:
			self._pending = False
			self.callLater(self.okbuttonClick)

	def menuClosed(self, *result):
		self.close()
