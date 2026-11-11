"""Only the existing Enigma2 configuration/keyboard interface needs Python."""
from Components.ActionMap import ActionMap
from Components.ConfigList import ConfigListScreen
from Components.config import ConfigText, ConfigPassword, NoSave, getConfigListEntry
from Components.Sources.StaticText import StaticText
from Screens.Screen import Screen


class MagicBoxAccount(Screen, ConfigListScreen):
	skinName = 'Setup'

	def __init__(self, session, native=None):
		Screen.__init__(self, session)
		if native is None:
			from Screens.InfoBar import InfoBar
			native = InfoBar.instance['home'].instance
		self.native = native
		self.native.requested.get().append(self.completed)
		self.onClose.append(self.disconnect)
		self.setTitle('IPTV hesabı')
		self.url = NoSave(ConfigText(default='', fixed_size=False))
		self.username = NoSave(ConfigText(default='', fixed_size=False))
		self.password = NoSave(ConfigPassword(default='', fixed_size=False))
		ConfigListScreen.__init__(self, [getConfigListEntry('Sunucu URL', self.url),
			getConfigListEntry('Kullanıcı adı', self.username), getConfigListEntry('Parola', self.password)], session=session)
		self['key_red'] = StaticText('Geri')
		self['key_green'] = StaticText('Bağlan')
		self['actions'] = ActionMap(['ColorActions', 'SetupActions'], {'red': self.keyCancel, 'cancel': self.keyCancel, 'green': self.connect}, -10)

	def connect(self):
		self.native.saveAccount(self.url.value, self.username.value, self.password.value)
		self['key_green'].setText('Kontrol ediliyor…')

	def completed(self, action):
		if action == 6:
			self.close()
		elif action == 7:
			self['key_green'].setText('Bağlan')

	def disconnect(self):
		self.native.requested.get().remove(self.completed)

	def keyCancel(self):
		self.native.cancelAccount()
		ConfigListScreen.keyCancel(self)
