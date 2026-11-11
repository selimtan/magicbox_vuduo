"""Enigma2 forms around the native C++ TKGS reader, planner and transaction."""
import json

from Components.ActionMap import ActionMap
from Components.ConfigList import ConfigListScreen
from Components.Label import Label
from Components.MenuList import MenuList
from Components.Sources.StaticText import StaticText
from Components.config import ConfigClock, ConfigInteger, ConfigSelection, ConfigYesNo, NoSave, getConfigListEntry
from Screens.Screen import Screen
from Screens.InfoBar import InfoBar
from Screens.InputBox import InputBox
from Screens.MessageBox import MessageBox
from Screens.TextBox import TextBox
from enigma import eDVBDB


class MagicBoxTKGS(Screen):
	skin = '''<screen name="MagicBoxTKGS" position="center,center" size="1100,570" title="TKGS">
		<widget name="menu" position="10,10" size="1080,390" font="Regular;24" itemHeight="48" />
		<widget name="status" position="10,410" size="1080,90" font="Regular;22" />
	</screen>'''

	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle('Türksat TKGS')
		self.client = InfoBar.instance.tkgs
		self['menu'] = MenuList([('Uydudan TKGS oku', self.read), ('Okunan listeyi önizle', self.preview),
			('Kanal listesini uygula', self.install), ('TKGS ayarları', self.options),
			('TKGS kayıt dosyası aç', self.capture), ('Önceki kanal listesine dön', self.restore)])
		self['status'] = Label('')
		for color, text in [('red', 'Geri'), ('green', 'Oku'), ('yellow', 'Önizle'), ('blue', 'Ayarlar')]:
			self['key_'+color] = StaticText(text)
		self['actions'] = ActionMap(['OkCancelActions', 'ColorActions'], {'ok': self.selected, 'cancel': self.back,
			'red': self.back, 'green': self.read, 'yellow': self.preview, 'blue': self.options}, -10)
		self.client.changed.get().append(self.changed)
		self.onClose.append(self.disconnect)
		self.onShown.append(self.refresh)
		self._preview = False
		self._previous = None

	def disconnect(self):
		self.client.changed.get().remove(self.changed)

	def refresh(self):
		self['status'].setText(self.client.getMessage())

	def changed(self, event):
		self.refresh()
		if not self.client.isBusy() and self._previous:
			self.session.nav.playService(self._previous)
			self._previous = None
		if event == 3 and self._preview:
			self._preview = False
			self.session.open(TextBox, self.client.getPreviewText(), title='TKGS önizleme')

	def selected(self):
		row = self['menu'].getCurrent()
		if row and not self.client.isBusy():
			row[1]()

	def read(self):
		if self.client.isBusy() or self.session.nav.getRecordings():
			return
		from Components.NimManager import nimmanager
		slots = nimmanager.getNimListForSat(420)
		if not slots:
			self['status'].setText('Önce Settings › Setup › Tuners & scanning bölümünden Türksat 42°E bağlantısını ayarlayın.')
			return
		for slot in slots:
			if self.client.start(slot):
				return
		self._previous = self.session.nav.getCurrentlyPlayingServiceReference()
		self.session.nav.stopService()
		for slot in slots:
			if self.client.start(slot):
				return
		if self._previous:
			self.session.nav.playService(self._previous)
		self._previous = None

	def preview(self):
		if not self.client.isBusy():
			eDVBDB.getInstance().saveServicelist()
			self._preview = True
			self.client.preview()

	def install(self):
		if not self.client.isBusy() and not self.session.nav.getRecordings():
			self.session.openWithCallback(self.confirmInstall, MessageBox, 'TKGS kanal listesi uygulansın mı? Mevcut liste yedeklenecek.')

	def confirmInstall(self, answer):
		if answer and not self.session.nav.getRecordings():
			eDVBDB.getInstance().saveServicelist()
			self.client.install()

	def options(self):
		if not self.client.isBusy():
			self.session.open(MagicBoxTKGSOptions, self.client)

	def capture(self):
		if not self.client.isBusy():
			self.session.openWithCallback(self.openCapture, InputBox, title='TKGS .ts veya bölüm kaydının tam dosya yolu', text='/media/usb/tkgs.ts')

	def openCapture(self, path):
		if path:
			self.client.importCapture(path)

	def restore(self):
		if not self.client.isBusy() and not self.session.nav.getRecordings():
			self.session.openWithCallback(lambda answer: self.client.restore() if answer else None, MessageBox, 'Önceki kanal listesi geri yüklensin mi?')

	def back(self):
		if self.client.isBusy():
			self.client.cancel()
		else:
			self.close()


class MagicBoxTKGSOptions(Screen, ConfigListScreen):
	skinName = 'Setup'

	def __init__(self, session, client):
		Screen.__init__(self, session)
		self.client = client
		self.setTitle('TKGS ayarları')
		values = json.loads(client.getOptions())
		self.fields = {
			'mode': NoSave(ConfigSelection(default=values['mode'], choices=[('flexible', 'Esnek sıralama'), ('auto', 'TKGS sıralaması')])),
			'order': NoSave(ConfigSelection(default=values['order'], choices=['HD', 'SD'])),
			'encrypted': NoSave(ConfigYesNo(default=values['encrypted'])),
			'auto': NoSave(ConfigYesNo(default=values['auto'])),
			'hour': NoSave(ConfigInteger(default=values['hour'], limits=(0, 23))),
			'minute': NoSave(ConfigInteger(default=values['minute'], limits=(0, 59))),
			'standby_only': NoSave(ConfigYesNo(default=values['standby_only'])),
			'timeout': NoSave(ConfigSelection(default=str(values['timeout']), choices=['30', '60', '90', '120'])),
			'beacon': NoSave(ConfigSelection(default=values['beacon'], choices=[('auto', 'Otomatik'), ('0', '12380 V 27500'), ('1', '12423 H 30000'), ('2', '12423 V 27500'), ('3', '12458 V 30000')]))}
		names = ['Çalışma biçimi', 'Kanal sıralaması', 'Şifreli kanalları dahil et', 'Otomatik güncelle', 'Saat', 'Dakika', 'Yalnız bekleme modunda', 'Okuma süresi (saniye)', 'TKGS frekansı']
		ConfigListScreen.__init__(self, [getConfigListEntry(name, value) for name, value in zip(names, self.fields.values())], session=session)
		self['key_red'] = StaticText('Geri')
		self['key_green'] = StaticText('Kaydet')
		self['actions'] = ActionMap(['SetupActions', 'ColorActions'], {'cancel': self.keyCancel, 'red': self.keyCancel, 'green': self.save}, -10)

	def save(self):
		values = {key: value.value for key, value in self.fields.items()}
		values['timeout'] = int(values['timeout'])
		self.client.saveOptions(json.dumps(values))
		self.close()
