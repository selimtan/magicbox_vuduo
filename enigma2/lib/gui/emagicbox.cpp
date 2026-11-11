/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <lib/gui/emagicbox.h>
#include <lib/gui/emagicboxframe.h>
#include <lib/gui/emagicboxdrawing.h>
#include <lib/magicbox/model.h>
#include <lib/base/message.h>
#include <lib/actions/action.h>
#include <lib/gdi/epng.h>
#include <lib/gdi/gfont.h>
#include <lib/gui/ewidgetdesktop.h>
#include <json-c/json.h>
#include <array>
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <cstdlib>
#include <deque>
#include <fcntl.h>
#include <mutex>
#include <sys/inotify.h>
#include <sys/stat.h>
#include <unistd.h>

using namespace MagicBox;
namespace {
struct View { std::shared_ptr<Page> page; int index = 0; bool loaded = false; };
using Clock = std::chrono::steady_clock;
constexpr int TVPreviewDelayMs = 2000;
constexpr int IPTVPreviewDelayMs = 500;
constexpr int FullscreenInfoMs = 3000;
}
struct eMagicBoxHome::State {
	Model model;
	eFixedMessagePump<int> pump{eApp, 1};
	ePtr<eTimer> previewTimer = eTimer::create(eApp);
	ePtr<eTimer> iconTimer = eTimer::create(eApp);
	ePtr<eTimer> infoTimer = eTimer::create(eApp);
	ePtr<eSocketNotifier> metricsNotifier;
	int metricsFd = -1;
	std::map<std::string,ePtr<gPixmap>> icons;
	std::deque<std::string> iconOrder;
	int iconNext=0,iconWidth=0;
	ePtr<gPixmap> background;
	ePtr<gFont> font, small, title, star;
	std::array<View, 5> views;
	std::array<std::vector<View>, 5> histories;
	std::mutex mutex;
	std::deque<std::shared_ptr<Page>> completed;
	std::map<std::string,bool> favoriteOverlay;
	std::map<std::string,unsigned> favoritePending;
	std::string waiting, message;
	int tab = 0, backgroundWidth = 0;
	bool active = false, fullscreen = false, playbackReady = false;
	bool infoVisible = false;
	std::string playbackMessage="Yayın bekleniyor. Anten ve tuner ayarlarını kontrol edin.";
	Clock::time_point input{};
	std::deque<double> latencies;
	unsigned paintCount = 0, backgroundLoads = 0, actionCount = 0, invalidations = 0;
	unsigned previewRequests = 0, previewCancels = 0;
	~State() { metricsNotifier=0;if(metricsFd>=0)::close(metricsFd);model.shutdown(); }
	View& view() { return views[tab]; }
	const Row* current() const { const auto& v = views[tab]; return v.page && v.index >= 0 && v.index < static_cast<int>(v.page->rows.size()) ? &v.page->rows[v.index] : nullptr; }
	int previewDelayMs() const { const auto row = current(); return tab == 1 || (row && row->group == "live") ? IPTVPreviewDelayMs : TVPreviewDelayMs; }
	void deliver(std::shared_ptr<Page> result) { { std::lock_guard<std::mutex> guard(mutex); completed.push_back(std::move(result)); } pump.send(1); }
	void cancelPreview(eMagicBoxHome* owner) { previewTimer->stop(); ++previewCancels; owner->requested(10); }
};
eMagicBoxHome::eMagicBoxHome(eWidget *parent): eWidget(parent), m(new State) {
	CONNECT(m->pump.recv_msg, eMagicBoxHome::receive);
	CONNECT(m->previewTimer->timeout, eMagicBoxHome::preview);
	CONNECT(m->iconTimer->timeout, eMagicBoxHome::loadIcon);
	m->infoTimer->timeout.connect([this]() {
		m->infoVisible = false;
		if (m->fullscreen) invalidate(eRect(38*size().width()/1280,604*size().height()/720,1204*size().width()/1280,92*size().height()/720));
	});
	// Optional diagnostics are requested through a fixed /tmp file. No polling,
	// Python execution hook, network listener or persistent flash writes.
	m->metricsFd=inotify_init1(IN_NONBLOCK|IN_CLOEXEC);
	if(m->metricsFd>=0) {
		if(inotify_add_watch(m->metricsFd,"/tmp",IN_CLOSE_WRITE)<0) { ::close(m->metricsFd);m->metricsFd=-1; }
		else { m->metricsNotifier=eSocketNotifier::create(eApp,m->metricsFd,eSocketNotifier::Read);CONNECT(m->metricsNotifier->activated,eMagicBoxHome::reportMetrics); }
	}
	ePtr<eActionMap> actions; eActionMap::getInstance(actions);
	actions->bindAction("MagicBoxHomeActions", -50, 0, this);
	actions->bindAction("MagicBoxReleaseActions", -50, 1, this);
	setTransparent(0);
	open("tv");
}
eMagicBoxHome::~eMagicBoxHome() {
	ePtr<eActionMap> actions; eActionMap::getInstance(actions); actions->unbindAction(this, 0);
	actions->unbindAction(this, 1);
	m->previewTimer->stop();
	m->iconTimer->stop();
	m->infoTimer->stop();
	// Model joins before its completion pump can be destroyed.
	delete m;
}
void eMagicBoxHome::setActive(bool active) { m->active = active; if (!active) { m->input={};m->cancelPreview(this);m->iconTimer->stop(); } else if (!m->fullscreen) { m->previewTimer->start(m->previewDelayMs(), true);prepareIcons(); } }
int eMagicBoxHome::getTab() const { return m->tab; }
int eMagicBoxHome::getSelection() const { return m->views[m->tab].index; }
std::string eMagicBoxHome::getService() const { auto row = m->current(); return row ? m->model.service(*row) : ""; }
std::string eMagicBoxHome::getName() const { auto row = m->current(); return row ? row->name : "Magic Box"; }
std::string eMagicBoxHome::getMessage() const { return m->message; }
void eMagicBoxHome::reloadAccount() { m->views[1] = {}; m->views[3] = {}; m->histories[1].clear(); m->histories[3].clear(); if (m->tab == 1) open("iptv"); }
void eMagicBoxHome::cancelAccount() { m->model.cancel(); }
void eMagicBoxHome::reloadTV() { m->model.invalidate("tv");m->views[0] = {}; if (m->tab == 0) open("tv",true); }
void eMagicBoxHome::saveAccount(const std::string& url, const std::string& user, const std::string& password) {
	m->message = "Hesap kontrol ediliyor…"; redraw();
	m->model.saveAccount({url, user, password, "ts"}, [this](std::shared_ptr<Page> p) { m->deliver(std::move(p)); });
}
void eMagicBoxHome::setTab(int tab) {
	if (tab < 0 || tab > 4 || tab == m->tab) return;
	m->model.cancel(); m->waiting.clear(); m->cancelPreview(this);
	if (m->fullscreen) { m->fullscreen = false; requested(5); }
	m->tab = tab; m->message.clear();
	if (!m->views[tab].loaded) {
		if (tab == 4) requested(2);
		else open(m->views[tab].page && !m->views[tab].page->key.empty() ? m->views[tab].page->key : tab == 0 ? "tv" : tab == 1 ? "iptv" : tab == 2 ? "media" : "favorites");
	}
	requested(8);redraw(true); if (tab != 4 && tab != 2) m->previewTimer->start(m->previewDelayMs(), true);
}
void eMagicBoxHome::setFullscreen(bool fullscreen) {
	m->fullscreen = fullscreen; m->previewTimer->stop(); m->infoTimer->stop();
	m->infoVisible = fullscreen;
	if (fullscreen && m->playbackReady) m->infoTimer->start(FullscreenInfoMs, true);
	redraw(true);
}
void eMagicBoxHome::setPlaybackState(bool available,const std::string& message) {
	if(m->playbackReady==available && m->playbackMessage==message)return;
	m->playbackReady=available;m->playbackMessage=message;
	if (m->fullscreen) {
		m->infoVisible = true; m->infoTimer->stop();
		if (available) m->infoTimer->start(FullscreenInfoMs, true);
	}
	invalidate(m->fullscreen?gRegion::invalidRegion():gRegion(eRect(603*size().width()/1280,193*size().height()/720,640*size().width()/1280,362*size().height()/720)));
}
void eMagicBoxHome::setSettings(const std::string& rows) {
	auto page = std::make_shared<Page>(); page->key = "settings"; page->title = "Settings";
	json_object* root = json_tokener_parse(rows.c_str());
	if (root && json_object_get_type(root) == json_type_array) {
		for (size_t i = 0; i < json_object_array_length(root); ++i) {
			auto entry = json_object_array_get_idx(root, i);
			if (entry && json_object_get_type(entry) == json_type_string) { Row r; r.name = json_object_get_string(entry); r.kind = "setting"; page->rows.push_back(std::move(r)); }
		}
	}
	if (root) json_object_put(root);
	m->views[4].page = page;
	m->views[4].loaded = true;
	if (m->views[4].index >= static_cast<int>(page->rows.size())) m->views[4].index = 0;
	if (m->tab == 4) redraw(true);
}
void eMagicBoxHome::open(const std::string& key, bool force) {
	m->cancelPreview(this); m->message.clear();
	if (!force) if (auto page = m->model.cached(key)) {
		m->waiting.clear(); m->view() = {page, 0, true}; requested(8);redraw(true); m->previewTimer->start(m->previewDelayMs(), true); return;
	}
	m->waiting = key;
	if (!force) { auto loading = std::make_shared<Page>(); loading->title = key == "tv" ? "TV" : key == "favorites" ? "Favorites" : key.rfind("media",0)==0 ? "Medya" : "IPTV"; loading->key = key; m->view() = {loading, 0}; }
	m->message = "Liste hazırlanıyor…"; requested(8);redraw(true);
	m->model.request(key, [this](std::shared_ptr<Page> page) { m->deliver(std::move(page)); }, force);
}
void eMagicBoxHome::receive(const int&) {
	std::deque<std::shared_ptr<Page>> queue;
	{ std::lock_guard<std::mutex> guard(m->mutex); queue.swap(m->completed); }
	for (auto& page : queue) {
		if (page->key == "account-change") {
			m->message = page->error;
			if (page->error.empty()) { requested(6); } else requested(7);
		} else if (page->key == "favorite-change") {
			m->message = page->error;
			if(!page->rows.empty()) {
				auto key=page->rows[0].key;auto pending=m->favoritePending.find(key);
				if(pending!=m->favoritePending.end() && --pending->second==0) { m->favoritePending.erase(pending);m->favoriteOverlay.erase(key); }
			}
			m->views[3] = {};
			if (m->tab == 3) open("favorites"); else redraw();
		} else if (page->key == m->waiting) {
			int index = m->view().index;
			m->view() = {page, std::min(index, std::max(0, static_cast<int>(page->rows.size()) - 1)), true};
			m->waiting.clear(); m->message = page->error; requested(8);redraw(true);
			if (m->active) m->previewTimer->start(m->previewDelayMs(), true);
		}
	}
}
void eMagicBoxHome::preview() { auto row=m->current(); if (m->active && !m->fullscreen && m->tab != 4 && row && row->playable() && (row->group=="tv" || row->group=="live")) { ++m->previewRequests; requested(0); } }
void eMagicBoxHome::navigate(int amount) {
	if (m->fullscreen && (amount == -8 || amount == 8)) {
		auto row = m->current();
		if (row && row->playable() && row->group == "live") {
			auto& view = m->view();
			const int count = view.page->rows.size();
			const int step = amount == 8 ? 1 : -1; // Right advances, left goes back in both modes.
			for (int offset = 1; offset < count; ++offset) {
				const int next = (view.index + step * offset + count) % count;
				const auto& candidate = view.page->rows[next];
				if (candidate.playable() && candidate.group == "live") {
					view.index = next;
					selected(); // Use OK's immediate playback, PIN and timeshift checks.
					redraw(true);
					return;
				}
			}
			return;
		}
	}
	if (m->fullscreen) { m->cancelPreview(this);m->fullscreen = false; requested(5);requested(8);redraw(true);m->previewTimer->start(m->previewDelayMs(),true); return; }
	m->cancelPreview(this);
	auto& view = m->view(); if (!view.page || view.page->rows.empty()) return;
	int old = view.index, count = view.page->rows.size();
	if (amount == -8 || amount == 8) {
		const int page = std::max(0, std::min((count - 1) / 8, old / 8 + amount / 8));
		view.index = std::min(page * 8 + old % 8, count - 1);
	} else view.index = (view.index + amount + count * 8) % count;
	redraw(old / 8 != view.index / 8, old);
	requested(8);
	invalidate(eRect(603*size().width()/1280,193*size().height()/720,640*size().width()/1280,362*size().height()/720));
	m->previewTimer->start(m->previewDelayMs(), true);
}
void eMagicBoxHome::selected() {
	auto row = m->current(); if (!row) return;
	m->previewTimer->stop();
	if (!row->playable()) m->cancelPreview(this);
	if (row->kind == "media-file") { requested(9); return; }
	if (row->playable()) { requested(1); return; }
	if (row->kind == "login") { requested(3); return; }
	if (row->kind == "setting") { requested(4); return; }
	Row selected = *row; m->histories[m->tab].push_back(m->view());
	if (selected.kind == "media-folder") open("media:" + selected.reference);
	else if (selected.kind == "season") { auto page = std::make_shared<Page>(); page->title = selected.name; page->rows = selected.children; page->key = "season:" + selected.id; m->view() = {page, 0, true}; requested(8);redraw(true); }
	else if (selected.kind == "group") open("categories:" + selected.group);
	else if (selected.kind == "category") open("streams:" + selected.group + ":" + selected.id);
	else if (selected.kind == "series") open("series:series:" + selected.id);
}
void eMagicBoxHome::redraw(bool full, int previous) {
	++m->invalidations;
	if (full) { invalidate(); prepareIcons(); return; }
	const auto scale = [this](int x, int y, int w, int h) { return eRect(x * size().width() / 1280, y * size().height() / 720, w * size().width() / 1280, h * size().height() / 720); };
	if (previous >= 0) { invalidate(scale(38, 194 + previous % 8 * 52, 533, 51)); invalidate(scale(38, 194 + m->view().index % 8 * 52, 533, 51)); }
	else invalidate(scale(38, 194, 533, 416));
	invalidate(scale(600, 568, 648, 85)); invalidate(scale(38, 618, 533, 35));
}
void eMagicBoxHome::prepareIcons() {
	m->iconTimer->stop();m->iconNext=0;
	if(m->iconWidth!=size().width()) { m->icons.clear();m->iconOrder.clear();m->iconWidth=size().width(); }
	if(m->active && !m->fullscreen && m->tab!=4)m->iconTimer->start(0,true);
}
void eMagicBoxHome::loadIcon() {
	if(!m->active || m->fullscreen || !m->view().page || size().width()<=0)return;
	int start=m->view().index/8*8;
	while(m->iconNext<8 && start+m->iconNext<static_cast<int>(m->view().page->rows.size())) {
		int row=m->iconNext++;auto name=m->view().page->rows[start+row].picon;
		if(name.size()<5 || name.size()>80 || name.substr(name.size()-4)!=".png" || name.substr(0,name.size()-4).find_first_not_of("0123456789abcdefABCDEF")!=std::string::npos)continue;
		if(m->icons.count(name)) { m->iconOrder.erase(std::remove(m->iconOrder.begin(),m->iconOrder.end(),name),m->iconOrder.end());m->iconOrder.push_back(name);continue; }
		ePtr<gPixmap> image;std::string path="/usr/share/enigma2/magicbox/assets/picons/"+name;loadPNG(image,path.c_str(),0,0);
		if(image) {
			eSize target(66*size().width()/1280,42*size().height()/720);
			if(image->size()!=target) {
				ePtr<gPixmap> scaled=MagicBoxDrawing::smoothPixmap(image,target);
				image=scaled;
			}
			if(image) getDesktop(0)->makeCompatiblePixmap(*image);
		}
		m->icons[name]=image;m->iconOrder.push_back(name);
		while(m->iconOrder.size()>32) { m->icons.erase(m->iconOrder.front());m->iconOrder.pop_front(); }
		invalidate(eRect(50*size().width()/1280,(198+row*52)*size().height()/720,66*size().width()/1280,42*size().height()/720));
		m->iconTimer->start(0,true);return;
	}
}
void eMagicBoxHome::paint(gPainter& p, const gRegion& region) {
	++m->paintCount;
	int w = size().width(), h = size().height(); if (!w || !h) return;
	auto rect = [w, h](int x, int y, int a, int b) { return eRect(x * w / 1280, y * h / 720, a * w / 1280, b * h / 720); };
	if (!m->font || m->backgroundWidth != w) {
		m->font = new gFont("MagicBox", 23 * h / 720); m->small = new gFont("MagicBox", 18 * h / 720); m->title = new gFont("MagicBox", 29 * h / 720);
		m->star = new gFont("DejaVuSans", 27 * h / 720);
		m->background = magicBoxBackground(w);
		m->backgroundWidth = w; ++m->backgroundLoads;
	}
	auto fill = [&](int x, int y, int a, int b, unsigned color) { auto box=rect(x,y,a,b);if((region&box).empty())return;p.setForegroundColor(gRGB(color));p.fill(box); };
	auto text = [&](int x, int y, int a, int b, const std::string& value, unsigned color, int font = 0, int align = 0) {
		if ((region & rect(x, y, a, b)).empty()) return;
		p.setForegroundColor(gRGB(color)); p.setFont(font == 1 ? m->small : font == 2 ? m->title : font == 3 ? m->star : m->font);
		// Ellipsis reserves another glyph and can cut a single UTF-8 symbol
		// midway through its bytes. Fixed-size icons must render intact.
		p.renderText(rect(x, y, a, b), value, (align ? gPainter::RT_HALIGN_CENTER : gPainter::RT_HALIGN_LEFT) | gPainter::RT_VALIGN_CENTER | (font == 3 ? 0 : gPainter::RT_ELLIPSIS) | gPainter::RT_BLEND);
	};
	p.clip(region);
	if (m->fullscreen) {
		// Keep the decoder plane visible while the next stream connects.
		fill(0, 0, 1280, 720, 0xff000000);
		if (m->infoVisible) {
			fill(38, 604, 1204, 2, 0x36dfff);
			fill(38, 606, 1204, 88, 0x20102645);
			fill(38, 606, 5, 88, 0xffdc41);
			text(56, 614, 70, 39, std::to_string(m->view().index + 1), 0xffdc41, 2, 1);
			text(142, 611, 1074, 44, getName(), 0xedf6ff, 2);
			auto row = m->current();
			const std::string source = row && row->group == "tv" ? "TV" : "IPTV";
			text(56, 655, 70, 26, source, 0x8fc9e7, 1, 1);
			text(142, 655, 1074, 27, m->playbackReady ? (row ? row->detail : "") : m->playbackMessage, 0xabc9dc, 1);
		}
		p.clippop();finishPaint();return;
	}
	if (m->background) p.blit(m->background, ePoint(0, 0)); else fill(0, 0, 1280, 720, 0x000718);
	fill(30, 125, 1220, 46, 0x06132f);
	const char* tabs[] = {"TV", "IPTV", "MEDYA", "FAVORITES", "SETTINGS"};
	const int positions[] = {30, 220, 410, 600, 820}, widths[] = {190, 190, 190, 220, 220};
	MagicBoxDrawing::selectedTab(p, positions[m->tab], widths[m->tab], w, h);
	for (int i = 0; i < 5; ++i) text(positions[i], 126, widths[i], 44, tabs[i], i == m->tab ? 0xedf6ff : 0xabc9dc, 0, 1);
	text(1010, 50, 230, 36, "MAGIC BOX OS", 0x3ee8ff, 1, 1);
	const auto& view = m->view(); auto page = view.page;
	int start = view.index / 8 * 8;
	for (int i = 0; i < 8; ++i) {
		int y = 194 + i * 52; bool selected = start + i == view.index;
		fill(39, y, 531, 50, selected ? 0x36dfff : 0x17375a); fill(41, y + 2, 527, 46, selected ? 0x103e69 : 0x07142f);
		if (!page || start + i >= static_cast<int>(page->rows.size())) continue;
		const auto& row = page->rows[start + i];
		fill(39, y, 5, 50, selected ? 0xffdc41 : 0x17375a); fill(50, y + 6, 66, 38, 0x132a46);
		text(50, y + 5, 66, 40, row.kind=="media-file" ? "EMC" : row.playable() ? (row.group == "tv" ? "TV" : row.group == "live" ? "LIVE" : "VOD") : "▸", 0x8fc9e7, row.playable() || row.kind=="media-file" ? 1 : 3, 1);
		auto icon=m->icons.find(row.picon);if(!(region&rect(50,y+4,66,42)).empty() && icon!=m->icons.end() && icon->second)p.blit(icon->second,ePoint(50*w/1280,(y+4)*h/720),eRect(),gPainter::BT_ALPHABLEND);
		text(135, y + 3, 44, 44, std::to_string(start + i + 1), selected ? 0xffdc41 : 0xa1bfd3);
		text(184, y + 3, 340, 44, row.name, 0xedf6ff);
		bool favorite=m->favoriteOverlay.count(row.key)?m->favoriteOverlay.at(row.key):m->model.favorite(row);
		if (favorite) text(528, y + 3, 31, 44, "★", 0xffdc41, 3, 1);
	}
	fill(600, 190, 646, 368, 0x36dfff); fill(603, 193, 640, 362, 0xff000000);
	auto row = m->current();
	if (!row || !row->playable() || !m->playbackReady) {
		fill(603, 193, 640, 362, 0x050d22);
		text(628, 290, 590, 60, row && (row->playable() || row->group=="media")?row->name:page ? page->title : "Magic Box", 0xedf6ff, 2, 1);
		if (!row || !row->playable()) text(628, 356, 590, 68, m->message.empty() ? row && row->kind=="media-file" ? "OK ile EMC oynatıcıda aç" : "OK ile aç" : m->message, 0xabc9dc, 1, 1);
	}
	text(608, 568, 638, 43, row ? row->name : page ? page->title : "Magic Box", 0xedf6ff, 2);
	text(609, 613, 635, 29, m->message.empty() ? (row ? row->detail : "") : m->message, 0xa8cde5, 1);
	fill(40, 618, 260, 32, 0x081d3c);
	text(40, 618, 260, 32, page && !page->rows.empty() ? std::to_string(view.index + 1) + " / " + std::to_string(page->rows.size()) : "0 / 0", 0xedf6ff, 1, 1);
	fill(0, 663, 1280, 2, 0x32dcff); fill(0, 665, 1280, 55, 0x06162e);
	text(38, 677, 200, 31, "OK  Aç / Tam ekran", 0xedf6ff, 1); text(268, 677, 140, 31, "●  Geri", 0xe33852, 1);
	text(430, 677, 210, 31, "●  Yenile", 0x38d978, 1); if(m->tab!=2)text(650, 677, 200, 31, "★  Favori", 0xffdc41, 1); text(900, 677, 340, 31, "◀ ▶ Sayfa    ‹ › Sekme", 0xabc9dc, 1);
	p.clippop();
	finishPaint();
}
void eMagicBoxHome::finishPaint() {
	if (m->input != Clock::time_point{}) {
		double elapsed = std::chrono::duration<double, std::milli>(Clock::now() - m->input).count();
		m->latencies.push_back(elapsed); if (m->latencies.size() > 256) m->latencies.pop_front(); m->input = {};
	}
}
std::string eMagicBoxHome::getMetrics() const {
	json_object* root = json_object_new_object();
	json_object_object_add(root, "paint_count", json_object_new_int64(m->paintCount));
	json_object_object_add(root, "background_loads", json_object_new_int64(m->backgroundLoads));
	json_object_object_add(root, "action_count", json_object_new_int64(m->actionCount));
	json_object_object_add(root, "preview_delay_ms", json_object_new_int(m->previewDelayMs()));
	json_object_object_add(root, "preview_requests", json_object_new_int64(m->previewRequests));
	json_object_object_add(root, "preview_cancels", json_object_new_int64(m->previewCancels));
	json_object_object_add(root, "tab", json_object_new_int(m->tab));
	json_object_object_add(root, "selection", json_object_new_int(m->view().index));
	json_object_object_add(root, "fullscreen", json_object_new_boolean(m->fullscreen));
	json_object_object_add(root, "playback_ready", json_object_new_boolean(m->playbackReady));
	json_object_object_add(root, "fullscreen_info_visible", json_object_new_boolean(m->fullscreen && m->infoVisible));
	json_object_object_add(root, "fullscreen_info_timeout_ms", json_object_new_int(FullscreenInfoMs));
	json_object_object_add(root, "loading", json_object_new_boolean(!m->waiting.empty()));
	auto values = json_object_new_array(); for (auto value : m->latencies) json_object_array_add(values, json_object_new_double(value));
	json_object_object_add(root, "input_to_paint_ms", values);
	std::string result = json_object_to_json_string_ext(root, JSON_C_TO_STRING_PLAIN); json_object_put(root); return result;
}
void eMagicBoxHome::reportMetrics(int) {
	alignas(inotify_event) char events[4096];bool requested=false;
	ssize_t count=::read(m->metricsFd,events,sizeof(events));
	if(count<=0)return;
	for(size_t at=0;at+sizeof(inotify_event)<=static_cast<size_t>(count);) {
		auto event=reinterpret_cast<const inotify_event*>(events+at);
		if(event->len>static_cast<size_t>(count)-at-sizeof(inotify_event))break;
		if((event->mask&IN_CLOSE_WRITE) && event->len && !std::strcmp(event->name,"magicbox-native-metrics.request"))requested=true;
		at+=sizeof(inotify_event)+event->len;
	}
	if(!requested)return;
	int input=::open("/tmp/magicbox-native-metrics.request",O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW);
	if(input<0)return;
	struct stat status{};char request[33]{};
	bool valid=fstat(input,&status)==0 && S_ISREG(status.st_mode) && status.st_size==32 && ::read(input,request,32)==32;
	::close(input);
	if(!valid || !std::all_of(request,request+32,[](char value) { return (value>='0'&&value<='9') || (value>='a'&&value<='f'); }))return;
	auto report=json_tokener_parse(getMetrics().c_str());if(!report)return;
	json_object_object_add(report,"request_id",json_object_new_string(request));
	json_object_object_add(report,"scope",json_object_new_string("Home input dispatch to paint command submission; excludes transport and framebuffer presentation"));
	std::string data=json_object_to_json_string_ext(report,JSON_C_TO_STRING_PLAIN);data+='\n';json_object_put(report);
	char temporary[]="/tmp/magicbox-native-metrics.XXXXXX";
	int output=mkostemp(temporary,O_CLOEXEC);if(output<0)return;
	size_t written=0;
	while(written<data.size()) { ssize_t amount=::write(output,data.data()+written,data.size()-written);if(amount<0 && errno==EINTR)continue;if(amount<=0)break;written+=amount; }
	bool complete=::close(output)==0 && written==data.size();
	if(!complete || ::rename(temporary,"/tmp/magicbox-native-metrics.json")<0)::unlink(temporary);
	::unlink("/tmp/magicbox-native-metrics.request");
}
int eMagicBoxHome::event(int ev, void* data, void* data2) {
	if (ev == evtPaint) { paint(*static_cast<gPainter*>(data2), *static_cast<gRegion*>(data)); return 0; }
	if (ev == evtAction) {
		// eWidget's default is -1, which eActionMap treats as handled.
		// A hidden/inactive home must let modal dialogs receive their keys.
		if (!m->active || !isVisible() || isLowered()) return 0;
		// A press already handled by home must not trigger a legacy InfoBar
		// action on release/long/repeat (e.g. yellow opening AudioSelection).
		if (reinterpret_cast<long>(data) == 1) return 1;
		++m->actionCount;
		const auto invalidationsBefore=m->invalidations;
		const bool paintAlreadyPending=m->input!=Clock::time_point{};
		if(m->input==Clock::time_point{})m->input = Clock::now();
		switch (reinterpret_cast<long>(data2)) {
		case moveUp: navigate(-1); break;
		case moveDown: navigate(1); break;
		case pageUp: navigate(-8); break;
		case pageDown: navigate(8); break;
		case previousTab: setTab((m->tab + 4) % 5); break;
		case nextTab: setTab((m->tab + 1) % 5); break;
		case settings: if (m->tab != 4) setTab(4); else requested(2); break;
		case select: selected(); break;
		case back:
			if (m->fullscreen) { m->cancelPreview(this);m->fullscreen = false; requested(5);requested(8);redraw(true);m->previewTimer->start(m->previewDelayMs(),true); }
			else if (!m->histories[m->tab].empty()) { auto& history = m->histories[m->tab]; m->model.cancel(); m->waiting.clear();m->cancelPreview(this); m->view() = history.back(); history.pop_back(); requested(8);redraw(true);m->previewTimer->start(m->previewDelayMs(),true); }
			else if (m->tab) setTab(0);
			break;
		case favorite:
			if (auto row = m->current()) if(row->playable() && !row->key.empty()) {
				bool current=m->favoriteOverlay.count(row->key)?m->favoriteOverlay.at(row->key):m->model.favorite(*row);
				m->favoriteOverlay[row->key]=!current;++m->favoritePending[row->key];redraw();
				m->model.toggle(*row, [this](std::shared_ptr<Page> p) { m->deliver(std::move(p)); });
			}
			break;
		case refresh:
			if (m->view().page && m->tab != 4) {
				if(m->view().page->key.rfind("season:",0)==0 && !m->histories[m->tab].empty()) {
					auto parent=m->histories[m->tab].back();m->histories[m->tab].pop_back();
					open(parent.page->key,true);
				} else open(m->view().page->key, true);
			}
			break;
		default: return 0;
		}
		// A no-op key must not become a multi-second sample at the next repaint.
		// Modal screens are excluded when execEnd calls setActive(false).
		if(!paintAlreadyPending && m->invalidations==invalidationsBefore)m->input={};
		return 1;
	}
	return eWidget::event(ev, data, data2);
}
