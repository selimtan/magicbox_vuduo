"""Adapt native Enigma2 forms to the system's C++ Magic Box page frame.

The widgets, sources, callbacks, validators and unsaved-change dialogs stay owned
by their original Enigma2 screens. This is called by Screen.applySkin itself.
"""
from Components.ActionMap import ActionMap
from Components.GUIComponent import GUIComponent
from enigma import eMagicBoxFrame, getDesktop, gFont
from types import CodeType, MethodType


class Frame(GUIComponent):
	GUI_WIDGET = eMagicBoxFrame


def attributes(component, **values):
	current = dict(component.skinAttributes or [])
	current.update(values)
	component.skinAttributes = list(current.items())


def pair(value, fallback=(0, 0)):
	try:
		return tuple(int(float(x)) for x in str(value).split(','))
	except (ValueError, TypeError):
		return fallback


def in_scope(screen):
	if getattr(screen, '_magicbox_adapted', False) or screen.__class__.__name__ in ('MagicBoxHome', 'Standby', 'NumericalTextInputHelpDialog'):
		return False
	if screen.stand_alone or 'Summary' in screen.__class__.__name__:
		return False
	# Playback OSDs must remain transparent overlays above the decoded video.
	# Their file browsers and settings still use the surrounding native frame.
	if any(cls.__name__ in ('MoviePlayer', 'EMCMediaCenter', 'DVDPlayer', 'DVDOverlay', 'PVRState') for cls in type(screen).__mro__):
		return False
	size, main = screen.desktop.size(), getDesktop(0).size()
	if (size.width(), size.height()) != (main.width(), main.height()):
		return False
	if pair(dict(screen.skinAttributes).get('size')) == (0, 0):
		return False
	# Only dialogs opened beneath the home/menu belong to Settings. Global
	# overlays instantiated while home is current (e.g. Volume) stay overlays.
	parents = [p for p, _ in screen.session.dialog_stack]
	if screen.__class__.__name__ == 'MessageBox' and any(
		any(cls.__name__ in ('MoviePlayer', 'EMCMediaCenter', 'DVDPlayer') for cls in type(parent).__mro__)
		for parent in parents if parent):
		return False
	return any(p and (p.__class__.__name__ == 'MagicBoxHome' or getattr(p, '_magicbox_adapted', False)) for p in parents)


def resizes_message_box(callback):
	if isinstance(callback, str):
		return 'self.instance.resize' in callback and 'textsize' in callback
	return (isinstance(callback, CodeType) and callback.co_filename == 'skin applet'
		and {'instance', 'resize', 'textsize'}.issubset(callback.co_names))


def prepare(screen):
	if not in_scope(screen):
		return
	screen._magicbox_adapted = True
	width, height = getDesktop(0).size().width(), getDesktop(0).size().height()
	px, py = lambda x: round(x * width / 1280), lambda y: round(y * height / 720)
	def geometry(component, x, y, w, h):
		attributes(component, position='%d,%d' % (px(x), py(y)), size='%d,%d' % (max(1, px(w)), max(1, py(h))))
	names = {id(value): name for name, value in screen.items()}
	native = [(name, value) for name, value in screen.items() if isinstance(value, GUIComponent) and value.skinAttributes]
	for value in screen.renderer:
		source, seen = getattr(value, 'source', None), set()
		while source and id(source) not in seen and id(source) not in names:
			seen.add(id(source))
			source = getattr(source, 'source', None)
		native.append((names.get(id(source), '_renderer'), value))
	screen.skinAttributes = [('position', '0,0'), ('size', '%d,%d' % (width, height)), ('resolution', '%d,%d' % (width, height)), ('flags', 'wfNoBorder'), ('backgroundColor', '#000718')]
	# Retain functional calibration images/static text, discard old window chrome.
	retained = []
	for i, widget in enumerate(screen.additionalWidgets):
		values = dict(widget.skinAttributes or [])
		image = values.get('pixmap', '').lower()
		if values.get('text', '').strip() or any(s in image for s in ('calib', 'overscan', 'pattern', 'test')):
			retained.append(widget)
			native.append(('_static%d' % i, widget))
	screen.additionalWidgets = retained
	frame = screen['_magicbox_frame'] = Frame()
	geometry(frame, 0, 0, 1280, 720)
	attributes(frame, zPosition='-20')
	hidden = {'Title', 'ScreenPath', 'title', 'Image', 'key_red', 'key_green', 'key_yellow', 'key_blue', 'key_previous', 'key_next', 'red', 'green', 'yellow', 'blue', 'VKeyIcon', 'HelpWindow', 'menuimage', 'ErrorPixmap', 'QuestionPixmap', 'InfoPixmap', 'WarningPixmap'}
	useful = []
	for key, component in native:
		values = dict(component.skinAttributes or [])
		if key in hidden or component.__class__.__name__ in ('VideoWindow', 'Pig'):
			geometry(component, -3000, -3000, 1, 1)
			continue
		position, size = pair(values.get('position')), pair(values.get('size'), (1, 1))
		useful.append((key, component, position, size))
		attributes(component, zPosition='3')
		if component.__class__.__name__ not in ('Pixmap', 'MultiPixmap', 'Progress', 'Slider'):
			attributes(component, foregroundColor='#edf6ff', backgroundColor='#07142f')
		if 'font' in values:
			attributes(component, font='MagicBox;%d' % py(23))
		if component.__class__.__name__.endswith('List') or component.__class__.__name__ == 'Listbox':
			component.skinAttributes = [(k, v) for k, v in component.skinAttributes if k not in ('selectionPixmap', 'backgroundPixmap')]
			attributes(component, backgroundColorSelected='#104778', foregroundColorSelected='#ffdf54', scrollbarMode='showOnDemand')
	boxes = [(p, s) for _, _, p, s in useful if p[0] >= 0 and p[1] >= 0 and s[0] > 1 and s[1] > 1]
	if boxes:
		left, top = min(p[0] for p, _ in boxes), min(p[1] for p, _ in boxes)
		w = max(p[0] + s[0] for p, s in boxes) - left
		h = max(p[1] + s[1] for p, s in boxes) - top
		for key, component, p, s in useful:
			geometry(component, 57+(p[0]-left)*1164/max(1,w), 227+(p[1]-top)*368/max(1,h), s[0]*1164/max(1,w), s[1]*368/max(1,h))
			if component.__class__.__name__ == 'ConfigList':
				attributes(component, itemHeight=str(py(39)))
			if getattr(screen, 'menuID', None):
				converter = getattr(component, 'source', None)
				if converter and hasattr(converter, 'template'):
					from Components.MultiContent import MultiContentEntryText
					from enigma import RT_VALIGN_CENTER
					converter.template = {'fonts': [gFont('MagicBox', py(24))], 'itemHeight': py(49), 'template': [MultiContentEntryText(pos=(px(18), 0), size=(px(1120), py(49)), font=0, flags=RT_VALIGN_CENTER, text=0)]}
					converter.active_style = None
					converter.changed((converter.CHANGED_DEFAULT,))
	if screen.__class__.__name__ == 'ChoiceBox':
		screen.onLayoutFinish = [f for f in screen.onLayoutFinish if getattr(f, '__name__', '') != 'autoResize']
	if screen.__class__.__name__ == 'MessageBox':
		# The stock skin's sizing applet would shrink the complete native frame
		# to a small window after layout. Give its functional widgets real room.
		screen.onLayoutFinish = [f for f in screen.onLayoutFinish if not resizes_message_box(f)]
		if 'text' in screen:
			geometry(screen['text'], 65, 240, 1150, 240)
		if 'list' in screen:
			geometry(screen['list'], 75, 497, 1130, 100)
	if screen.__class__.__name__ == 'VirtualKeyBoard':
		for key, box in {'prompt': (65,230,1150,30), 'text': (65,270,1150,42), 'locale': (65,578,1040,27), 'mode': (1135,578,85,27)}.items():
			if key in screen:
				geometry(screen[key], *box)
		keyboard_width = screen.width * 14
		attributes(screen['list'], position='%d,%d' % ((width-keyboard_width)//2, py(323)), size='%d,%d' % (keyboard_width, py(250)))
	def refresh(_screen):
		if not frame.instance:
			return
		frame.instance.setText('Settings  ›  ' + screen.getTitle())
		keys = []
		for color in ('red', 'green', 'yellow', 'blue'):
			value = screen.get('key_' + color) or screen.get(color)
			keys.append(str(value.getText() if hasattr(value, 'getText') else getattr(value, 'text', '') or ''))
		frame.instance.setKeys(*keys)
	# Screen.onLayoutFinish accepts bound methods or Python source strings.
	refresh = MethodType(refresh, screen)
	screen.onLayoutFinish.append(refresh)
	screen.onShown.append(refresh)
	screen.onContentChanged.append(refresh)
