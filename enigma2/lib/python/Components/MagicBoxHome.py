"""Enigma2 screen lifecycle adapter. All home rendering/input/data are C++."""
from Components.GUIComponent import GUIComponent
from enigma import eMagicBoxHome, eMagicBoxImages

_catalog = None


def imageCatalog():
	# Keep the native network worker alive when its modal screen closes.
	global _catalog
	if _catalog is None:
		_catalog = eMagicBoxImages()
	return _catalog


class MagicBoxHome(GUIComponent):
	GUI_WIDGET = eMagicBoxHome

	def __init__(self, callback):
		GUIComponent.__init__(self)
		self.callback = callback

	def postWidgetCreate(self, instance):
		instance.requested.get().append(self.callback)

	def preWidgetRemove(self, instance):
		instance.setActive(False)
		instance.requested.get().remove(self.callback)

	def execBegin(self):
		if self.instance:
			self.instance.setActive(True)

	def execEnd(self):
		if self.instance:
			self.instance.setActive(False)
