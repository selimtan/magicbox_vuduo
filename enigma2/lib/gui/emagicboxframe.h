#ifndef ENIGMA_GUI_EMAGICBOXFRAME_H
#define ENIGMA_GUI_EMAGICBOXFRAME_H
#include <lib/gui/ewidget.h>

// Shared decoded wallpaper: home and every Settings page use the same surface.
gPixmap *magicBoxBackground(int width);

class eMagicBoxUpdates
{
public:
	static std::string validateSources();
};

class eMagicBoxFrame: public eWidget
{
public:
	eMagicBoxFrame(eWidget *parent);
	void setText(const std::string &text);
	void setKeys(const std::string &red, const std::string &green, const std::string &yellow, const std::string &blue);
protected:
	int event(int event, void *data = 0, void *data2 = 0);
private:
	std::string m_text;
	std::string m_keys[4];
};
#endif
