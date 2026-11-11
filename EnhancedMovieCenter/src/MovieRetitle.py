from os import rename
from os.path import basename, dirname, exists, isfile, join, splitext
from glob import glob

# for localized messages
from . import _

from Screens.Screen import Screen
from Components.config import config, ConfigText, getConfigListEntry, ConfigPassword
from Components.ActionMap import ActionMap
from .configlistext import ConfigListScreenExt
from Components.Sources.StaticText import StaticText
from Components.Label import Label
from Components.Pixmap import Pixmap

from enigma import eServiceReference, iServiceInformation, ePoint

# Plugin internal
from .ServiceSupport import ServiceCenter


class MovieRetitle(Screen, ConfigListScreenExt):
	def __init__(self, session, services):
		Screen.__init__(self, session)

		self.skinName = ["MovieRetitle", "Setup"]
		self.list = []
		ConfigListScreenExt.__init__(self, self.list, session)

		self["Path"] = Label(_("Location:"))  # + ' ' + dirname(splitext(path)[0]))
		self["HelpWindow"] = Pixmap()
		self.onLayoutFinish.append(self.setCustomTitle)

		self["key_green"] = StaticText(_("Save"))
		self["key_red"] = StaticText(_("Cancel"))
		self["actions"] = ActionMap(["SetupActions"],
		{
			"ok": self.keyGo,
			"save": self.keyGo,
			"cancel": self.keyCancel,
		}, -2)

		self["VirtualKB"] = ActionMap(["VirtualKeyboardActions"],
		{
			"showVirtualKeyboard": self.KeyText,
		}, -2)
		self["VirtualKB"].setEnabled(False)
		self["HelpWindow"] = Pixmap()
		self["footnote"] = StaticText()
		self["description"] = StaticText()

		self.serviceHandler = ServiceCenter.getInstance()

		if isinstance(services, list):
			self.services = services
		else:
			self.services = [services]

		self.buildSetup(self.services.pop())

	def buildSetup(self, service):
		self.service = service
		self.is_dir = service.flags & eServiceReference.mustDescent
		info = self.serviceHandler.info(service)
		path = service.getPath()
		self["Path"] = Label(_("Location:") + ' ' + dirname(splitext(path)[0]))
		if self.is_dir:
			self.original_file = service.getName()
		else:
			self.original_file = basename(splitext(path)[0])
		if config.EMC.movie_show_format.value:
			ext = splitext(service.getPath())[1]
			self.original_name = info.getName(service)[:-(len(ext) + 2)]
		else:
			self.original_name = info.getName(service)
		self.original_desc = info.getInfoString(service, iServiceInformation.sDescription)
		self.input_file = ConfigText(default=self.original_file, fixed_size=False, visible_width=82)
		self.input_title = ConfigText(default=self.original_name, fixed_size=False, visible_width=82)
		self.input_descr = ConfigText(default=self.original_desc, fixed_size=False, visible_width=82)
		self.createSetup()

	def createSetup(self):
		self.list = []
		if self.is_dir:
			self.list.append(getConfigListEntry(_("Foldername:"), self.input_file))
		else:
			self.list.append(getConfigListEntry(_("Filename:"), self.input_file))
			self.list.append(getConfigListEntry(_("Movietitle:"), self.input_title))
			self.list.append(getConfigListEntry(_("Description:"), self.input_descr))
		self["config"].setList(self.list)

	def handleInputHelpers(self):
		if self["config"].getCurrent() is not None:
			if isinstance(self["config"].getCurrent()[1], ConfigText) or isinstance(self["config"].getCurrent()[1], ConfigPassword):
				self["VirtualKB"].setEnabled(True)
				if "HelpWindow" in self:
					if self["config"].getCurrent()[1].help_window.instance is not None:
						try:
							helpwindowpos = self["HelpWindow"].getPosition()
							self["config"].getCurrent()[1].help_window.instance.move(ePoint(helpwindowpos[0], helpwindowpos[1]))
						except:
							pass
			else:
				self["VirtualKB"].setEnabled(False)
		else:
			self["VirtualKB"].setEnabled(False)

	def setCustomTitle(self):
		if self.is_dir:
			self.setTitle(_("Change Foldername"))
		else:
			self.setTitle(_("Change File/Moviename and/or Description"))

	def keyGo(self):
		if self.is_dir:
			if self.input_file.getText() != self.original_file:
				self.renameDirectory(self.service, self.input_file.getText())
				self.original_file = self.input_file.getText()
		else:
			if self.input_title.getText() != self.original_name or self.input_descr.getText() != self.original_desc:
				self.setTitleDescr(self.service, self.input_title.getText(), self.input_descr.getText())
				self.original_name = self.input_title.getText()
				self.original_desc = self.input_descr.getText()
			if self.input_file.getText() != self.original_file:
				self.renameFile(self.service, self.input_file.getText())
				self.original_file = self.input_file.getText()
		if self.services:
			service = self.services.pop()
			self.buildSetup(service)
		else:
			self.close()

	def keyCancel(self):
		self.close()

	def setTitleDescr(self, service, title, descr):
		#TODO Use MetaSupport class
		if service.getPath().lower().endswith(".ts"):
			meta_file = service.getPath() + ".meta"
		else:
			meta_file = service.getPath() + ".ts.meta"

		# Create new meta for ts files
		if not exists(meta_file):
			if isfile(service.getPath()):
				_title = basename(splitext(service.getPath())[0])
			else:
				_title = service.getName()
			_sid = ""
			_descr = ""
			_time = ""
			_tags = ""
			metafile = open(meta_file, "w")
			metafile.write(f"{_sid}\n{_title}\n{_descr}\n{_time}\n{_tags}")
			metafile.close()

		if exists(meta_file):
			metafile = open(meta_file, "r")
			sid = metafile.readline()
			oldtitle = metafile.readline().rstrip()
			olddescr = metafile.readline().rstrip()
			rest = metafile.read()
			metafile.close()
			if not title and title != "":
				title = oldtitle
			if not descr and descr != "":
				descr = olddescr
			metafile = open(meta_file, "w")
			metafile.write(f"{sid}{title}\n{descr}\n{rest}")
			metafile.close()

	def renameDirectory(self, service, new_name):
		try:
			dir = dirname(self.service.getPath()[0:-1])
			rename(self.service.getPath(), join(dir, self.input_file.getText() + "/"))
			self.original_file = self.input_file.getText()
		except Exception as e:
			print(e)

	def renameFile(self, service, new_name):
		try:
			path = dirname(service.getPath())
			file_name = basename(splitext(service.getPath())[0])
			src = join(path, file_name)
			if isinstance(new_name, bytes):
				new_name = new_name.decode()
			dst = join(path, new_name)
			for f in glob(join(path, src + "*")):
				rename(f, f.replace(src, dst))
		except Exception as e:
			print(e)
