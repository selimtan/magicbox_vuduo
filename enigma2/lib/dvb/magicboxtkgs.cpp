/* Native tuner reader and background TKGS jobs. GPL-2.0-or-later. */
#include <lib/dvb/magicboxtkgs.h>
#include <lib/dvb/dvb.h>
#include <lib/dvb/db.h>
#include <lib/dvb/frontend.h>
#include <lib/base/message.h>
#include <lib/magicbox/tkgs.h>
#include <lib/magicbox/tkgsstore.h>
#include <json-c/json.h>
#include <linux/dvb/dmx.h>
#include <atomic>
#include <array>
#include <ctime>
#include <stdexcept>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <functional>
#include <mutex>
#include <thread>
#include <fcntl.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <unistd.h>

namespace {
using Clock=std::chrono::steady_clock;
std::string readFile(const std::string& path,size_t maximum=8*1024*1024) {
	std::ifstream stream(path,std::ios::binary);if(!stream)throw std::runtime_error("Dosya okunamadı.");stream.seekg(0,std::ios::end);std::streamoff size=stream.tellg();if(size<0 || static_cast<uint64_t>(size)>maximum)throw std::runtime_error("Dosya boyut sınırını aştı.");stream.seekg(0);std::string out(size,'\0');if(size && !stream.read(&out[0],size))throw std::runtime_error("Dosya eksik.");return out;
}
void writeFile(const std::string& path,const std::string& text) {
	std::filesystem::create_directories(std::filesystem::path(path).parent_path());std::string tmp=path+".new";std::ofstream file(tmp,std::ios::binary|std::ios::trunc);if(!file.write(text.data(),text.size()))throw std::runtime_error("TKGS ayarları kaydedilemedi.");file.close();if(rename(tmp.c_str(),path.c_str()))throw std::runtime_error("TKGS ayarları kaydedilemedi.");
}
json_object* field(json_object* root,const char* key) { json_object* out=nullptr;if(root)json_object_object_get_ex(root,key,&out);return out; }
std::string localDate(time_t now) { tm local{};localtime_r(&now,&local);char text[16]{};strftime(text,sizeof(text),"%Y-%m-%d",&local);return text; }
std::string checkedOptions(const std::string& text) {
	json_object* root=json_tokener_parse(text.c_str());if(!root)throw std::runtime_error("TKGS ayarları geçersiz.");
	const char* defaultText="{\"mode\":\"flexible\",\"order\":\"HD\",\"encrypted\":false,\"auto\":false,\"hour\":4,\"minute\":0,\"standby_only\":true,\"timeout\":60,\"beacon\":\"auto\"}";
	json_object* result=json_tokener_parse(defaultText);
	const char* keys[]={"mode","order","encrypted","auto","hour","minute","standby_only","timeout","beacon"};
	for(auto key:keys) {
		auto value=field(root,key),base=field(result,key);if(!value || json_object_get_type(value)!=json_object_get_type(base))continue;
		std::string name=key;bool valid=true;std::string s=json_object_get_string(value);int n=json_object_get_int(value);
		if(name=="mode")valid=s=="auto" || s=="flexible";
		else if(name=="order")valid=s=="HD" || s=="SD";
		else if(name=="hour")valid=n>=0 && n<=23;
		else if(name=="minute")valid=n>=0 && n<=59;
		else if(name=="timeout")valid=n==30 || n==60 || n==90 || n==120;
		else if(name=="beacon")valid=s=="auto" || s=="0" || s=="1" || s=="2" || s=="3";
		if(valid)json_object_object_add(result,key,json_object_get(value));
	}
	std::string out=json_object_to_json_string_ext(result,JSON_C_TO_STRING_PLAIN);json_object_put(root);json_object_put(result);return out;
}
}
struct eMagicBoxTKGS::State {
	eUsePtr<iDVBChannel> channel;
	ePtr<iDVBFrontend> frontend;
	ePtr<eTimer> timer=eTimer::create(eApp);
	eFixedMessagePump<int> pump{eApp,1};
	std::thread worker;
	std::atomic<bool> stop{false};
	std::mutex mutex;
	std::string message="TKGS verisi henüz okunmadı.",table,plan,options,autoDate;
	bool busy=false,background=false;
	int beacon=0,beaconEnd=4,timeout=60;
	Clock::time_point started,lastAuto{};
	~State() { stop=true;timer->stop();if(worker.joinable())worker.join(); }
};
eMagicBoxTKGS::eMagicBoxTKGS():m(new State) {
	CONNECT(m->timer->timeout,eMagicBoxTKGS::tick);CONNECT(m->pump.recv_msg,eMagicBoxTKGS::receive);
	m->options=checkedOptions("{}");
	try { m->options=checkedOptions(readFile("/etc/enigma2/magicbox-tkgs/options.json")); } catch(...) {}
	work(0);
}
eMagicBoxTKGS::~eMagicBoxTKGS() { delete m; }
bool eMagicBoxTKGS::isBusy() const { return m->busy; }
std::string eMagicBoxTKGS::getMessage() const { std::lock_guard<std::mutex> guard(m->mutex);return m->message; }
std::string eMagicBoxTKGS::getTable() const { std::lock_guard<std::mutex> guard(m->mutex);return m->table; }
std::string eMagicBoxTKGS::getPlan() const { std::lock_guard<std::mutex> guard(m->mutex);return m->plan; }
std::string eMagicBoxTKGS::getPreviewText() const {
	auto text=getPlan();auto root=json_tokener_parse(text.c_str());if(!root)return getMessage();auto catalog=field(root,"catalog"),channels=field(catalog,"channels");std::string out=std::to_string(json_object_array_length(channels))+" TV kanalı\n\n";
	for(size_t i=0;i<json_object_array_length(channels);++i) { auto channel=json_object_array_get_idx(channels,i);out+=std::to_string(json_object_get_int(field(channel,"lcn")))+"  "+json_object_get_string(field(channel,"name"))+"\n"; }json_object_put(root);return out;
}
std::string eMagicBoxTKGS::getOptions() const { return m->options; }
void eMagicBoxTKGS::saveOptions(const std::string& options) { if(m->busy)return;m->options=checkedOptions(options);work(5,m->options); }
bool eMagicBoxTKGS::start(int slot,bool background) {
	if(m->busy)return false;
	ePtr<eDVBResourceManager> resources;eDVBResourceManager::getInstance(resources);
	if(!resources || resources->allocateRawChannel(m->channel,slot)) { { std::lock_guard<std::mutex> guard(m->mutex);m->message="Boş Türksat tuneri bulunamadı."; }changed(4);return false; }
	m->channel->getFrontend(m->frontend);
	if(!m->frontend) { m->channel=nullptr;return false; }
	m->background=background;m->busy=true;m->stop=false;m->beacon=0;
	auto options=json_tokener_parse(m->options.c_str());std::string beacon=json_object_get_string(field(options,"beacon"));m->timeout=json_object_get_int(field(options,"timeout"));m->beaconEnd=4;if(beacon!="auto") { m->beacon=std::stoi(beacon);m->beaconEnd=m->beacon+1; }json_object_put(options);
	nextBeacon();return true;
}
void eMagicBoxTKGS::nextBeacon() {
	if(m->beacon>=m->beaconEnd || m->stop) { m->timer->stop();m->frontend=nullptr;m->channel=nullptr;m->busy=false;{ std::lock_guard<std::mutex> guard(m->mutex);m->message=m->stop?"TKGS okuması iptal edildi. Kanal listesi korundu.":"TKGS tablosu alınamadı. Uydu sinyalini kontrol edin; mevcut liste korundu."; }changed(4);return; }
	static const int beacons[][3]={{12380,1,27500},{12423,0,30000},{12423,1,27500},{12458,1,30000}};
	const auto& b=beacons[m->beacon++];eDVBFrontendParametersSatellite sat{};
	sat.frequency=b[0]*1000;sat.symbol_rate=b[2]*1000;sat.polarisation=b[1];sat.orbital_position=420;sat.inversion=2;sat.fec=eDVBFrontendParametersSatellite::FEC_3_4;sat.system=eDVBFrontendParametersSatellite::System_DVB_S;sat.modulation=eDVBFrontendParametersSatellite::Modulation_QPSK;sat.rolloff=eDVBFrontendParametersSatellite::RollOff_alpha_0_35;sat.pilot=eDVBFrontendParametersSatellite::Pilot_Off;sat.is_id=-1;sat.pls_mode=0;sat.pls_code=0;sat.t2mi_plp_id=-1;sat.t2mi_pid=4096;
	eDVBFrontendParameters parameters;parameters.setDVBS(sat);m->frontend->tune(parameters);m->started=Clock::now();m->timer->start(150);
	{ std::lock_guard<std::mutex> guard(m->mutex);m->message=std::to_string(b[0])+" "+(b[1]?"V":"H")+" · Uydu sinyali bekleniyor…"; }changed(0);
}
void eMagicBoxTKGS::tick() {
	int state=0;m->frontend->getState(state);
	if(m->stop) { m->beacon=4;nextBeacon(); }
	else if(state==iDVBFrontend::stateLock) {
		m->timer->stop();int demux=m->channel->reserveDemux();if(demux<0) { nextBeacon();return; }work(1,std::to_string(demux));
	} else if(Clock::now()-m->started>std::chrono::seconds(10))nextBeacon();
}
void eMagicBoxTKGS::cancel() { m->stop=true;if(m->timer->isActive()) { m->beacon=4;nextBeacon(); } }
void eMagicBoxTKGS::importCapture(const std::string& path) { if(!m->busy)work(2,path); }
void eMagicBoxTKGS::preview() { if(!m->busy)work(3); }
void eMagicBoxTKGS::install() { if(!m->busy)work(4); }
void eMagicBoxTKGS::restore() { if(!m->busy)work(6); }
void eMagicBoxTKGS::work(int operation,const std::string& argument) {
	if(m->worker.joinable())m->worker.join();
	m->busy=true;m->stop=false;std::string options=m->options;bool background=m->background;
	if(operation==1) { std::lock_guard<std::mutex> guard(m->mutex);m->message="TKGS tablosu okunuyor · PID 8181"; }
	m->worker=std::thread([this,operation,argument,options,background] {
		int event=0;std::string message,table,plan;
		try {
			if(operation==0) {
				if(MagicBox::TKGS::recover())event=2;
				try {
					auto root=json_tokener_parse(readFile("/etc/enigma2/magicbox-tkgs/last-auto.json").c_str());
					auto date=field(root,"date");
					if(date && json_object_get_type(date)==json_type_string) { std::lock_guard<std::mutex> guard(m->mutex);m->autoDate=json_object_get_string(date); }
					json_object_put(root);
				}catch(const std::exception&) {}
			}
			else if(operation==1) {
				int fd=open(("/dev/dvb/adapter0/demux"+argument).c_str(),O_RDWR|O_NONBLOCK|O_CLOEXEC);if(fd<0)throw std::runtime_error("TKGS demux açılamadı.");
				try {
					ioctl(fd,DMX_SET_BUFFER_SIZE,512*1024);dmx_sct_filter_params filter{};filter.pid=MagicBox::TKGS::PID;filter.filter.filter[0]=MagicBox::TKGS::TABLE_ID;filter.filter.mask[0]=0xff;filter.flags=DMX_IMMEDIATE_START;
					if(ioctl(fd,DMX_SET_FILTER,&filter)<0)throw std::runtime_error("TKGS bölüm filtresi açılamadı.");
					MagicBox::TKGS::Stream stream;MagicBox::TKGS::Sections collection;auto started=Clock::now(),changedAt=started;bool transport=false;
					while(!m->stop && Clock::now()-started<std::chrono::seconds(m->timeout)) {
						pollfd port{fd,POLLIN,0};int available=poll(&port,1,100);if(available<0 && errno!=EINTR)throw std::runtime_error("TKGS demux okunamadı.");
						if(available>0 && (port.revents&POLLIN)) {
							std::array<uint8_t,188*256> buffer{};ssize_t n=read(fd,buffer.data(),buffer.size());
							if(n>0)for(const auto& section:stream.feed({buffer.begin(),buffer.begin()+n})) { try { if(collection.add(section))changedAt=Clock::now(); }catch(const std::runtime_error&) {} }
						}
						if(collection.complete() && Clock::now()-changedAt>=std::chrono::seconds(3)) { table=MagicBox::TKGS::decode(collection.ordered());break; }
						if(!transport && Clock::now()-started>std::chrono::seconds(5)) {
							ioctl(fd,DMX_STOP);dmx_pes_filter_params pes{};pes.pid=MagicBox::TKGS::PID;pes.input=DMX_IN_FRONTEND;pes.output=DMX_OUT_TSDEMUX_TAP;pes.pes_type=DMX_PES_OTHER;pes.flags=DMX_IMMEDIATE_START;
							if(ioctl(fd,DMX_SET_PES_FILTER,&pes)<0)throw std::runtime_error("TKGS TS filtresi açılamadı.");
							stream=MagicBox::TKGS::Stream(true);transport=true;
						}
					}
					ioctl(fd,DMX_STOP);close(fd);
				} catch(...) { ioctl(fd,DMX_STOP);close(fd);throw; }
				if(table.empty())throw std::runtime_error(m->stop?"TKGS okuması iptal edildi; mevcut liste korundu.":"TKGS tablosu alınamadı; mevcut liste korundu.");
				event=1;message="TKGS tablosu okundu. Listeyi önizleyebilirsiniz.";
			} else if(operation==2) { std::ifstream input(argument,std::ios::binary);table=MagicBox::TKGS::capture(input,[this] { return bool(m->stop); });event=1;message="TKGS kaydı çözüldü; liste henüz uygulanmadı."; }
			else if(operation==3 || operation==4) {
				auto current=getTable();if(current.empty())throw std::runtime_error("Önce TKGS verisini okuyun veya kayıt dosyası açın.");
				std::string catalog="/etc/enigma2/magicbox-tkgs/channels.json";if(!std::filesystem::exists(catalog))catalog="/usr/share/enigma2/magicbox/channels.json";
				plan=MagicBox::TKGS::plan(current,readFile("/etc/enigma2/lamedb"),readFile(catalog),options);
				if(operation==4) {
					bool identical=false;
					if(background)try {
						auto installed=json_tokener_parse(readFile("/etc/enigma2/magicbox-tkgs/installed.json").c_str());
						auto incoming=json_tokener_parse(current.c_str());auto previous=field(installed,"sha256"),next=field(incoming,"sha256");
						identical=previous && next && std::string(json_object_get_string(previous))==json_object_get_string(next);
						json_object_put(installed);json_object_put(incoming);
					}catch(const std::exception&) {}
					if(!identical) { MagicBox::TKGS::commit(plan);event=2;message="TKGS kanal listesi yedeklenerek uygulandı."; }
					else message="TKGS listesi kontrol edildi; kanal listesi zaten güncel.";
					if(background) {
						try {
							auto date=localDate(time(nullptr));writeFile("/etc/enigma2/magicbox-tkgs/last-auto.json","{\"date\":\""+date+"\"}");
							std::lock_guard<std::mutex> guard(m->mutex);m->autoDate=date;
						}catch(const std::exception&) { message+=" Otomatik kontrol tarihi kaydedilemedi."; }
					}
				}else { event=3;message="TKGS listesi hazır; uygulamadan önce kontrol edebilirsiniz."; }
			} else if(operation==5) { writeFile("/etc/enigma2/magicbox-tkgs/options.json",options);message="TKGS ayarları kaydedildi."; }
			else if(operation==6) { MagicBox::TKGS::restore();event=2;message="TKGS öncesindeki kanal listesi geri yüklendi."; }
		} catch(const std::exception& e) { event=operation==1 && !m->stop && m->beacon<m->beaconEnd?8:4;message=e.what(); }
		{ std::lock_guard<std::mutex> guard(m->mutex);if(!message.empty())m->message=message;if(!table.empty())m->table=table;if(!plan.empty())m->plan=plan; }
		m->pump.send(event);
	});
}
void eMagicBoxTKGS::receive(const int& event) {
	if(event==8) { nextBeacon();return; }
	m->busy=false;m->frontend=nullptr;m->channel=nullptr;changed(event);
	if(event==1 && m->background && !m->stop) {
		eDVBDB::getInstance()->saveServicelist();
		work(4);
	}
}
void eMagicBoxTKGS::checkAutomatic(bool standby,bool recording,int slot) {
	if(m->busy || recording)return;
	auto options=json_tokener_parse(m->options.c_str());bool enabled=json_object_get_boolean(field(options,"auto"));bool standbyOnly=json_object_get_boolean(field(options,"standby_only"));int minute=json_object_get_int(field(options,"hour"))*60+json_object_get_int(field(options,"minute"));json_object_put(options);if(!enabled || (standbyOnly && !standby))return;
	time_t now=time(nullptr);tm local{};localtime_r(&now,&local);
	{ std::lock_guard<std::mutex> guard(m->mutex);if(m->autoDate==localDate(now))return; }
	if(local.tm_hour*60+local.tm_min<minute || (m->lastAuto!=Clock::time_point{} && Clock::now()-m->lastAuto<std::chrono::hours(1)))return;
	m->lastAuto=Clock::now();start(slot,true);
}
