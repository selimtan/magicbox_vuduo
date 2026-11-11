/* Magic Box is a built-in Enigma2 widget, not a PluginDescriptor. */
#ifndef ENIGMA_GUI_EMAGICBOX_H
#define ENIGMA_GUI_EMAGICBOX_H
#include <lib/gui/ewidget.h>
#include <lib/python/connections.h>

class eMagicBoxHome: public eWidget, public sigc::trackable
{
public:
	eMagicBoxHome(eWidget *parent);
	~eMagicBoxHome();
	void setActive(bool active);
	void setTab(int tab);
	int getTab() const;
	void setFullscreen(bool fullscreen);
	void setPlaybackState(bool available, const std::string &message);
	void reloadAccount();
	void cancelAccount();
	void reloadTV();
	void setSettings(const std::string &rows);
	std::string getService() const;
	std::string getName() const;
	int getSelection() const;
	std::string getMetrics() const;
	void saveAccount(const std::string &url, const std::string &username, const std::string &password);
	// 0 preview, 1 full screen, 2 Settings root, 3 account form, 4 Settings item,
	// 5 full screen -> home, 6 account saved, 7 sanitized account error,
	// 8 page changed (update native video window visibility), 9 EMC file playback,
	// 10 cancel automatic preview immediately after selection/navigation changes.
	PSignal1<void, int> requested;
	std::string getMessage() const;
	enum MagicBoxHomeActions {
		moveUp, moveDown, pageUp, pageDown, previousTab, nextTab,
		select, back, settings, favorite, refresh
	};
protected:
	int event(int event, void *data = 0, void *data2 = 0);
private:
	struct State;
	State *m;
	void receive(const int &);
	void preview();
	void prepareIcons();
	void loadIcon();
	void paint(gPainter &painter, const gRegion &region);
	void finishPaint();
	void reportMetrics(int what);
	void navigate(int amount);
	void open(const std::string &key, bool force = false);
	void selected();
	void redraw(bool full = false, int previous = -1);
};
#endif
