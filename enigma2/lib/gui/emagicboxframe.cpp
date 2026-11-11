#include <lib/gui/emagicboxframe.h>
#include <lib/gui/emagicboxdrawing.h>
#include <lib/gdi/epng.h>
#include <lib/gdi/gfont.h>
#include <lib/gui/ewidgetdesktop.h>
#include <filesystem>
#include <fstream>
#include <set>
#include <sstream>
#include <vector>
#include <array>

namespace MagicBoxDrawing {
gPixmap *smoothPixmap(gPixmap *source, const eSize &target) {
	if (!source || target.width() <= 0 || target.height() <= 0) return nullptr;
	const auto surface = source->surface;
	if (!surface || surface->x <= 0 || surface->y <= 0) return nullptr;
	std::vector<uint8_t> expanded;
	const uint8_t *pixels = static_cast<const uint8_t*>(surface->data);
	int stride = surface->stride;
	if (surface->bpp == 8) {
		stride = surface->x * 4;
		expanded.resize(stride * surface->y);
		for (int y = 0; y < surface->y; ++y) for (int x = 0; x < surface->x; ++x) {
			const int index = pixels[y * surface->stride + x];
			const gRGB color = surface->clut.data && index < surface->clut.colors
				? surface->clut.data[index] : gRGB(index, index, index);
			uint8_t *pixel = expanded.data() + y * stride + x * 4;
			pixel[0] = color.b; pixel[1] = color.g; pixel[2] = color.r; pixel[3] = 255 - color.a;
		}
		pixels = expanded.data();
	} else if (surface->bpp != 32) return nullptr;
	auto result = new gPixmap(target, 32, gPixmap::accelNever);
	resizeArea(pixels, surface->x, surface->y, stride,
		static_cast<uint8_t*>(result->surface->data), target.width(), target.height(), result->surface->stride);
	return result;
}

void selectedTab(gPainter &painter, int x, int logicalWidth, int canvasWidth, int canvasHeight) {
	// Rasterize each width once, directly at the output size. No scaled blits.
	static std::array<ePtr<gPixmap>, 2> tabs;
	static int cachedWidth = 0, cachedHeight = 0;
	if (canvasWidth != cachedWidth || canvasHeight != cachedHeight) {
		for (auto &tab : tabs) tab = nullptr;
		cachedWidth = canvasWidth; cachedHeight = canvasHeight;
	}
	const int index = logicalWidth == 220 ? 1 : 0;
	if (!tabs[index]) {
		const std::string path = "/usr/share/enigma2/magicbox/assets/tab-selected-" + std::to_string(logicalWidth) + ".svg";
		loadSVG(tabs[index], path.c_str(), 0, (logicalWidth + 7) * canvasWidth / 1280, 44 * canvasHeight / 720);
		if (tabs[index]) getDesktop(0)->makeCompatiblePixmap(*tabs[index]);
	}
	if (tabs[index]) painter.blit(tabs[index], ePoint(x * canvasWidth / 1280, 126 * canvasHeight / 720), eRect(), gPainter::BT_ALPHABLEND);
}
}

std::string eMagicBoxUpdates::validateSources() {
	const std::set<std::string> expected = {
		"https://45.87.174.241:8448/feeds/magicbox-2/vuduo/all",
		"https://45.87.174.241:8448/feeds/magicbox-2/vuduo/mips32el",
		"https://45.87.174.241:8448/feeds/magicbox-2/vuduo/vuduo"
	};
	std::set<std::string> actual;
	try {
		std::vector<std::string> files{"/etc/opkg.conf"};
		for (const auto& entry : std::filesystem::directory_iterator("/etc/opkg")) if (entry.path().extension()==".conf") files.push_back(entry.path());
		for (const auto& file : files) {
			std::ifstream stream(file); std::string line;
			while (std::getline(stream,line)) {
				std::istringstream input(line); std::string type,name,url;
				input>>type; if(type!="src" && type!="src/gz")continue;
				input>>name>>url;
				if(!expected.count(url) || !actual.insert(url).second)return "Güncelleme deposu Magic Box OS yapılandırmasıyla eşleşmiyor.";
			}
		}
	} catch(const std::exception&) { return "Magic Box güncelleme yapılandırması okunamadı."; }
	return actual==expected ? "" : "Magic Box güncelleme depoları eksik.";
}

gPixmap *magicBoxBackground(int width) {
	static ePtr<gPixmap> background;
	static int loaded = 0;
	if (!background || loaded != width) {
		loadImage(background, width >= 1920 ? "/usr/share/enigma2/magicbox/assets/background-1920x1080.jpg" : "/usr/share/enigma2/magicbox/assets/background.jpg", 0, 0, 0);
		if (background) getDesktop(0)->makeCompatiblePixmap(*background);
		loaded = width;
	}
	return background;
}
eMagicBoxFrame::eMagicBoxFrame(eWidget *parent): eWidget(parent) { setTransparent(0); }
void eMagicBoxFrame::setText(const std::string& text) { if (m_text != text) { m_text = text; invalidate(); } }
void eMagicBoxFrame::setKeys(const std::string& red, const std::string& green, const std::string& yellow, const std::string& blue) {
	const std::string keys[] = {red, green, yellow, blue}; bool changed = false;
	for (int i = 0; i < 4; ++i) if (m_keys[i] != keys[i]) { m_keys[i] = keys[i]; changed = true; }
	if (changed) invalidate();
}
int eMagicBoxFrame::event(int ev, void* data, void* data2) {
	if (ev != evtPaint) return eWidget::event(ev, data, data2);
	auto& p = *static_cast<gPainter*>(data2); int w = size().width(), h = size().height();
	auto box = [w, h](int x, int y, int a, int b) { return eRect(x*w/1280, y*h/720, a*w/1280, b*h/720); };
	auto fill = [&](int x, int y, int a, int b, unsigned color) { p.setForegroundColor(gRGB(color)); p.fill(box(x,y,a,b)); };
	ePtr<gFont> font = new gFont("MagicBox", 24*h/720), small = new gFont("MagicBox",18*h/720);
	auto text = [&](int x, int y, int a, int b, const std::string& value, unsigned color, bool tiny = false) { p.setForegroundColor(gRGB(color)); p.setFont(tiny ? small : font); p.renderText(box(x,y,a,b), value, gPainter::RT_VALIGN_CENTER | gPainter::RT_ELLIPSIS | gPainter::RT_BLEND); };
	if (auto background = magicBoxBackground(w)) p.blit(background, ePoint(0,0)); else fill(0,0,1280,720,0x000718);
	fill(30,125,1220,46,0x06132f);
	MagicBoxDrawing::selectedTab(p,820,220,w,h);
	text(100,126,120,44,"TV",0xabc9dc); text(280,126,130,44,"IPTV",0xabc9dc); text(455,126,145,44,"MEDYA",0xabc9dc); text(635,126,185,44,"FAVORITES",0xabc9dc); text(860,126,180,44,"SETTINGS",0xedf6ff);
	text(40,178,1200,31,m_text,0xb9d9ed); fill(38,214,1208,432,0x2bc9ed); fill(40,216,1204,428,0x07142f);
	fill(0,663,1280,2,0x32dcff); fill(0,665,1280,55,0x06162e);
	text(39,675,1100,31,"OK  Seç     EXIT  Geri     MENU  Settings",0xabc9dc,true);
	const unsigned colors[] = {0xec4057,0x47db7e,0xffd641,0x3eb4ff};
	for (int i=0;i<4;++i) text(42+i*295,611,280,29,m_keys[i].empty() ? "" : "●  "+m_keys[i],colors[i],true);
	return 0;
}
