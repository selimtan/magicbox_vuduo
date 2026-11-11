from Components.GUIComponent import GUIComponent
from Components.Label import Label
from Components.Pixmap import Pixmap
from Screens.Screen import Screen
from enigma import eCanvas, eRect, gRGB


class SegmentedVolumeBar(GUIComponent):
	"""Small native canvas; a volume key repaints only the changed ticks."""
	GUI_WIDGET = eCanvas
	SEGMENTS = 50
	GREEN = gRGB(0x0030ff18)
	SHADOW = gRGB(0x00000000)
	CLEAR = gRGB(0xff000000)

	def __init__(self):
		GUIComponent.__init__(self)
		self.value = 0
		self._painted = None

	def applySkin(self, desktop, parent):
		result = GUIComponent.applySkin(self, desktop, parent)
		self.instance.setSize(self.instance.size())
		self._painted = None
		self._paint()
		return result

	def setValue(self, value):
		self.value = max(0, min(100, int(value)))
		if self.instance is not None:
			self._paint()

	def _rect(self, x, y, width, height, color):
		# Work in the skin's 600 x 40 design coordinates, including at 1080p.
		size = self.instance.size()
		x0, y0 = x * size.width() // 600, y * size.height() // 40
		x1 = (x + width) * size.width() // 600
		y1 = (y + height) * size.height() // 40
		self.instance.fillRect(eRect(x0, y0, x1 - x0, y1 - y0), color)

	def _paint(self):
		count = (self.value * self.SEGMENTS + 99) // 100
		if count == self._painted:
			return
		if self._painted is None:
			self.instance.clear(self.CLEAR)
			start, end = 0, self.SEGMENTS
		else:
			start, end = sorted((count, self._painted))
		for index in range(start, end):
			x = 50 + index * 11
			self._rect(x, 4, 8, 32, self.CLEAR)
			# Short green ruler marks remain beyond the current level.
			y, height = (4, 28) if index < count else (21, 11)
			self._rect(x + 1, y + 2, 6, height, self.SHADOW)
			self._rect(x, y, 6, height, self.GREEN)
		self._painted = count


class Volume(Screen):
	skin = '''<screen name="MagicBoxVolume" position="center,e-50" size="600,40" resolution="1280,720" zPosition="20" flags="wfNoBorder" backgroundColor="transparent">
		<widget name="Volume" position="0,0" size="600,40" alphatest="blend" transparent="1" />
		<widget name="Speaker" position="0,0" size="34,40" zPosition="1" pixmap="/usr/share/enigma2/magicbox/assets/volume-speaker.svg" alphatest="blend" transparent="1" />
	</screen>'''

	def __init__(self, session):
		Screen.__init__(self, session)
		self.skinName = "MagicBoxVolume"
		self.volumeBar = SegmentedVolumeBar()
		self["Volume"] = self.volumeBar
		self["Speaker"] = Pixmap()
		self["VolumeText"] = Label("")

	def show(self):
		# Enigma2's immediate compositor clips lower windows before painting.
		# Match the native footer in menus; leave decoded full-screen video clear.
		current = self.session.current_dialog
		color = 0xff000000
		if current and current.__class__.__name__ == 'MagicBoxHome':
			if not current._fullscreen:
				color = 0x0006162e
			elif not current._video_ready:
				color = 0x00050d22
		elif getattr(current, '_magicbox_adapted', False):
			color = 0x0006162e
		self.instance.setBackgroundColor(gRGB(color))
		Screen.show(self)

	def setValue(self, vol):
		self.volumeBar.setValue(vol)
		self["VolumeText"].text = str(vol)
