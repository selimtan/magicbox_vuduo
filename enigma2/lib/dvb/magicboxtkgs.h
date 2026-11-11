#ifndef ENIGMA_DVB_MAGICBOXTKGS_H
#define ENIGMA_DVB_MAGICBOXTKGS_H
#include <lib/python/connections.h>
#include <string>

class eMagicBoxTKGS: public sigc::trackable
{
public:
	eMagicBoxTKGS();
	~eMagicBoxTKGS();
	bool start(int frontendSlot, bool background = false);
	void cancel();
	bool isBusy() const;
	std::string getMessage() const;
	std::string getTable() const;
	std::string getPlan() const;
	std::string getPreviewText() const;
	std::string getOptions() const;
	void saveOptions(const std::string &options);
	void importCapture(const std::string &path);
	void preview();
	void install();
	void restore();
	void checkAutomatic(bool standby, bool recording, int frontendSlot);
	PSignal1<void,int> changed;
private:
	struct State;
	State *m;
	void tick();
	void receive(const int &event);
	void nextBeacon();
	void work(int operation, const std::string &argument = "");
};
#endif
