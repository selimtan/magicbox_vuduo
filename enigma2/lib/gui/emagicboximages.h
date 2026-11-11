#ifndef ENIGMA_GUI_EMAGICBOXIMAGES_H
#define ENIGMA_GUI_EMAGICBOXIMAGES_H
#include <lib/python/connections.h>
#include <string>
class eMagicBoxImages: public sigc::trackable
{
public:
	eMagicBoxImages();
	~eMagicBoxImages();
	void load();
	std::string getData() const;
	std::string getError() const;
	std::string getNotes() const;
	PSignal1<void,int> completed;
private:
	struct State;
	State *m;
	void receive(const int &event);
};
#endif
