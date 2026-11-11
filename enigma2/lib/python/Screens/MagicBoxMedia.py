"""EMC playback with a small Magic Box OSD and native Media return points."""
from os.path import basename
from xml.etree.ElementTree import fromstring

from enigma import eTimer
from Components.Label import Label
# Load the converter with the home screen, before the first file is selected.
from Components.Converter.EMCServicePosition import EMCServicePosition
from Plugins.Extensions.EnhancedMovieCenter.EMCMediaCenter import EMCMediaCenter


class MagicBoxEMCPlayer(EMCMediaCenter):

	parsedSkin = fromstring('''<screen name="MagicBoxEMCPlayer" position="20,540" size="1240,160" resolution="1280,720" flags="wfNoBorder" backgroundColor="#07142f">
		<eLabel position="0,0" size="1240,2" backgroundColor="#36dcff" />
		<widget name="Cover" position="14,16" size="80,128" alphatest="blend" />
		<widget name="magicbox_title" position="110,12" size="1110,34" font="MagicBox;28" noWrap="1" foregroundColor="#edf6ff" />
		<widget source="Service" render="Progress" position="110,66" size="1110,10" foregroundColor="#ffdf54" backgroundColor="#19416b" borderWidth="0">
			<convert type="EMCServicePosition">Position</convert>
		</widget>
		<widget source="Service" render="Label" position="110,87" size="230,28" font="MagicBox;24" foregroundColor="#edf6ff">
			<convert type="EMCServicePosition">Position,ShowHours</convert>
		</widget>
		<widget source="Service" render="Label" position="990,87" size="230,28" font="MagicBox;24" halign="right" foregroundColor="#edf6ff">
			<convert type="EMCServicePosition">Remaining,Negate,ShowHours</convert>
		</widget>
		<widget name="audioLabel" position="110,125" size="200,24" font="MagicBox;20" foregroundColor="#abc9dc" />
		<widget name="subtitleLabel" position="320,125" size="200,24" font="MagicBox;20" foregroundColor="#abc9dc" />
		<widget name="chapterLabel" position="530,125" size="460,24" font="MagicBox;20" foregroundColor="#abc9dc" />
		<widget name="anglePix" position="0,0" size="1,1" />
		<widget name="angleLabel" position="1000,125" size="220,24" font="MagicBox;20" halign="right" foregroundColor="#abc9dc" />
	</screen>''')

	def __init__(self, session, playlist, **kwargs):
		EMCMediaCenter.__init__(self, session, playlist, **kwargs)
		self.skinName = 'MagicBoxEMCPlayer'
		self['magicbox_title'] = Label(playlist[0].getName() or basename(playlist[0].getPath()))
		# Media has no live preview. Tune the selected TV/IPTV channel only when
		# the user returns to one of those tabs, rather than blocking Media exit.
		self.lastservice = None
		self._media_start = eTimer()
		self._media_start.callback.append(self.beginMedia)
		self._media_started = False
		self.onClose.append(self._media_start.stop)

	def _EMCMediaCenter__onShow(self):
		if not self._media_started:
			self._media_start.start(80, True)

	def beginMedia(self):
		if self._media_started or self.session.current_dialog is not self:
			return
		self._media_started = True
		EMCMediaCenter._EMCMediaCenter__onShow(self)

	def showMovies(self):
		self.leavePlayer()

	def evEOF(self, *args, **kwargs):
		EMCMediaCenter.evEOF(self, *args, **kwargs)
		if self.service:
			self['magicbox_title'].setText(self.service.getName() or basename(self.service.getPath()))

	def up(self):
		self.leavePlayer()

	def down(self):
		self.leavePlayer()
