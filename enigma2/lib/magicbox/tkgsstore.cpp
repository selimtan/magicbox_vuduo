/* Native TKGS catalog planning and recoverable writes. GPL-2.0-or-later. */
#include "tkgsstore.h"
#include <json-c/json.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>
#include <tuple>
#include <vector>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>

namespace MagicBox { namespace TKGS {
namespace {
namespace fs=std::filesystem;
using Json=std::unique_ptr<json_object,decltype(&json_object_put)>;
void require(bool ok,const char* message) { if(!ok)throw std::runtime_error(message); }
Json parse(const std::string& text) { Json out(json_tokener_parse(text.c_str()),json_object_put);require(bool(out),"JSON verisi geçersiz");return out; }
json_object* field(json_object* o,const char* key) { json_object* v=nullptr;if(o)json_object_object_get_ex(o,key,&v);return v; }
std::string str(json_object* o,const char* key,const std::string& fallback="") { auto v=field(o,key);return v?json_object_get_string(v):fallback; }
int num(json_object* o,const char* key,int fallback=0) { auto v=field(o,key);return v?json_object_get_int(v):fallback; }
void put(json_object* o,const char* key,int value) { json_object_object_add(o,key,json_object_new_int(value)); }
void put(json_object* o,const char* key,const std::string& value) { json_object_object_add(o,key,json_object_new_string(value.c_str())); }
std::string encode(json_object* o) { return json_object_to_json_string_ext(o,JSON_C_TO_STRING_PLAIN); }
std::vector<json_object*> rows(json_object* o) { std::vector<json_object*> out;require(o && json_object_get_type(o)==json_type_array,"Liste geçersiz");for(size_t i=0;i<json_object_array_length(o);++i)out.push_back(json_object_array_get_idx(o,i));return out; }
std::vector<std::string> split(const std::string& text,char separator='\n') { std::vector<std::string> out;std::istringstream input(text);std::string line;while(std::getline(input,line,separator))out.push_back(line);return out; }
std::string clean(std::string text) { for(char& c:text)if(c=='\r' || c=='\n' || c=='\0')c=' ';return text; }
std::string hex(int value,int width=0) { std::ostringstream out;out<<std::hex<<std::setfill('0')<<std::setw(width)<<value;return out.str(); }
std::string read(const fs::path& path) { std::ifstream file(path,std::ios::binary);require(bool(file),"Dosya okunamadı");std::string text{std::istreambuf_iterator<char>(file),{}};require(text.size()<16*1024*1024,"Dosya boyut sınırını aştı");return text; }
void syncDir(const fs::path& path) { int fd=open(path.c_str(),O_RDONLY|O_DIRECTORY);if(fd>=0) { fsync(fd);close(fd); } }
void atomic(const fs::path& path,const std::string& text) {
	fs::create_directories(path.parent_path());std::string temporary=path.string()+".new.XXXXXX";std::vector<char> name(temporary.begin(),temporary.end());name.push_back(0);int fd=mkstemp(name.data());require(fd>=0,"TKGS dosyası oluşturulamadı");bool ok=fchmod(fd,0600)==0;size_t done=0;
	while(ok && done<text.size()) { auto n=write(fd,text.data()+done,text.size()-done);if(n<0 && errno==EINTR)continue;if(n<=0) { ok=false;break; }done+=n; }
	if(ok)ok=fsync(fd)==0;
	if(close(fd))ok=false;
	if(!ok || rename(name.data(),path.c_str())) { unlink(name.data());throw std::runtime_error("TKGS dosyası kaydedilemedi"); }syncDir(path.parent_path());
}
using MuxKey=std::tuple<int,int,int>;
using ServiceKey=std::tuple<int,int,int,int>;
struct Database { std::map<MuxKey,std::string> muxes;std::map<ServiceKey,std::array<std::string,3>> services; };
Database database(const std::string& text) {
	Database out;auto lines=split(text);require(!lines.empty() && lines[0]=="eDVB services /4/","Bu istemci lamedb sürüm 4 gerektiriyor");size_t index=1;require(index<lines.size() && lines[index++]=="transponders","Transponder tablosu eksik");
	while(index<lines.size() && lines[index]!="end") {
		auto key=split(lines[index++],':');require(key.size()==3,"Transponder kimliği geçersiz");std::string value;
		while(index<lines.size() && lines[index]!="/") { if(!value.empty())value+='\n';value+=lines[index++]; }require(index<lines.size(),"Transponder kaydı eksik");++index;
		out.muxes[{std::stoi(key[0],nullptr,16),std::stoi(key[1],nullptr,16),std::stoi(key[2],nullptr,16)}]=value;
	}
	require(index+1<lines.size() && lines[++index]=="services","Servis tablosu eksik");++index;
	while(index<lines.size() && lines[index]!="end") {
		require(index+2<lines.size(),"Servis veritabanı kayıtları eksik");auto key=split(lines[index],':');require(key.size()>=4,"Servis kimliği geçersiz");out.services[{std::stoi(key[0],nullptr,16),std::stoi(key[1],nullptr,16),std::stoi(key[2],nullptr,16),std::stoi(key[3],nullptr,16)}]={lines[index],lines[index+1],lines[index+2]};index+=3;
	}
	require(index<lines.size() && lines[index]=="end","Servis tablosu sonu eksik");return out;
}
std::string serialize(const Database& db) {
	std::string out="eDVB services /4/\ntransponders\n";
	for(const auto& pair:db.muxes)out+=hex(std::get<0>(pair.first),8)+":"+hex(std::get<1>(pair.first),4)+":"+hex(std::get<2>(pair.first),4)+"\n"+pair.second+"\n/\n";
	out+="end\nservices\n";for(const auto& pair:db.services)for(const auto& line:pair.second)out+=line+'\n';return out+"end\n";
}
std::vector<int> muxFields(const std::string& value) { auto start=value.find("s ");if(start==std::string::npos)return {};auto parts=split(value.substr(start+2),':');std::vector<int> out;for(const auto& part:parts)out.push_back(std::stoi(part));return out; }
const std::array<std::string,5> FILES={"lamedb","userbouquet.magicbox.tv","bouquets.tv","magicbox-tkgs/channels.json","magicbox-tkgs/installed.json"};
void restoreSnapshot(const fs::path& root,const fs::path& backup) {
	auto state=parse(read(backup/"files.json"));
	for(const auto& name:FILES) { if(json_object_get_boolean(field(state.get(),name.c_str())))atomic(root/name,read(backup/name));else fs::remove(root/name); }
	syncDir(root);
}
bool backupName(const std::string& name) { return !name.empty() && name.find_first_not_of("0123456789-")==std::string::npos; }
std::vector<fs::path> backups(const fs::path& base) {
	std::vector<fs::path> out;
	if(fs::exists(base))for(const auto& entry:fs::directory_iterator(base))if(!entry.is_symlink() && entry.is_directory() && backupName(entry.path().filename()) && fs::exists(entry.path()/"files.json"))out.push_back(entry.path());
	std::sort(out.begin(),out.end(),[](const fs::path& a,const fs::path& b) { auto first=fs::last_write_time(a/"files.json"),second=fs::last_write_time(b/"files.json");return first==second?a<b:first<second; });
	return out;
}
}
std::string plan(const std::string& raw,const std::string& text,const std::string& previousText,const std::string& optionsText) {
	auto table=parse(raw),previous=parse(previousText),options=parse(optionsText);require(json_object_get_boolean(field(table.get(),"crc_verified")),"Doğrulanmış TKGS tablosu yok");Database old=database(text),updated=old;
	auto carriers=rows(field(table.get(),"carriers"));auto services=rows(field(table.get(),"channels"));require(!services.empty(),"TKGS kanal listesi boş");std::map<int,int> positions;auto orders=field(table.get(),"orders");auto order=field(orders,str(options.get(),"order","HD").c_str());
	if(order)for(auto row:rows(order)) { auto pair=rows(row);require(pair.size()==2,"Kanal sırası geçersiz");positions[json_object_get_int(pair[1])]=json_object_get_int(pair[0]); }
	else for(auto service:services)positions[num(service,"lcn")]=num(service,"lcn");
	std::map<std::string,json_object*> previousNames;std::map<std::string,int> priority;int oldIndex=0;
	for(auto channel:rows(field(previous.get(),"channels"))) { previousNames[str(channel,"name")]=channel;priority[str(channel,"reference")]=oldIndex++; }
	std::vector<Json> catalog;std::set<std::string> references;int filtered=0;
	const std::set<int> tvTypes={1,4,17,22,25,28,31,32,134,195},namespaceTsids={1,2,3,4,5,6,7,8,9,11,15,22,1001};
	for(auto service:services) {
		int kind=num(service,"service_type"),lcn=num(service,"lcn");if(!tvTypes.count(kind) || !positions.count(lcn))continue;
		if((num(service,"encrypted") && !num(options.get(),"encrypted")) || num(service,"video_type",-1)==7 || kind==31 || kind==32) { ++filtered;continue; }
		int carrierIndex=num(service,"carrier",-1);require(carrierIndex>=0 && carrierIndex<static_cast<int>(carriers.size()),"Transponder kimliği geçersiz");auto carrier=carriers[carrierIndex];int sid=num(service,"sid"),frequency=num(carrier,"frequency"),rate=num(carrier,"symbol_rate"),pol=num(carrier,"polarisation");
		int ns=420<<16,tsid=num(service,"tsid"),onid=num(service,"onid");bool known=false;std::tuple<bool,int,MuxKey> best;
		for(const auto& pair:old.muxes) {
			auto values=muxFields(pair.second);if(values.size()<5 || values[4]%3600!=420 || values[2]!=pol || std::abs(values[0]-frequency)>3000 || std::abs(values[1]-rate)>500000)continue;
			int n=std::get<0>(pair.first),t=std::get<1>(pair.first),o=std::get<2>(pair.first);auto rank=std::make_tuple(!old.services.count({sid,n,t,o}),std::abs(values[0]-frequency),pair.first);
			if(!known || rank<best) { best=rank;known=true; }
		}
		if(known)std::tie(ns,tsid,onid)=std::get<2>(best);
		else { require(tsid>0 && onid>0 && onid!=0x1111,"Gerçek DVB kimlikleri bulunamadı; mevcut liste korunuyor");if(onid==42 && namespaceTsids.count(tsid))ns|=(frequency/1000)|((pol&1)<<15); }
		require(sid>0 && sid<=65535 && tsid>0 && tsid<=65535 && onid>0 && onid<=65535 && pol>=0 && pol<4,"Gerçek DVB servis kimlikleri eksik");MuxKey mux={ns,tsid,onid};
		if(updated.muxes.count(mux)) { auto fields=muxFields(updated.muxes.at(mux));require(fields.size()>=3 && std::abs(fields[0]-frequency)<=3000 && fields[2]==pol,"Çakışan transponder kimliği; listeye dokunulmadı"); }
		std::string params="s "+std::to_string(frequency)+":"+std::to_string(rate)+":"+std::to_string(pol)+":"+std::to_string(num(carrier,"fec"))+":420:2:0";
		if(num(carrier,"system"))params+=":1:"+std::to_string(num(carrier,"modulation"))+":"+std::to_string(num(carrier,"rolloff"))+":2";
		updated.muxes[mux]=params;
		std::string ref="1:0:"+hex(kind)+":"+hex(sid)+":"+hex(tsid)+":"+hex(onid)+":"+hex(ns)+":0:0:0:";
		require(references.insert(ref).second,"Tekrarlanan DVB servis kaydı");ServiceKey identity={sid,ns,tsid,onid};auto provider=clean(str(service,"provider"));std::replace(provider.begin(),provider.end(),',',' ');std::string metadata="p:"+provider;
		if(field(service,"video_pid"))metadata+=",c:00"+hex(num(service,"video_pid"),4)+",c:05"+hex(num(service,"video_type"),4);
		if(field(service,"pcr_pid") && num(service,"pcr_pid")!=8191)metadata+=",c:03"+hex(num(service,"pcr_pid"),4);
		auto audio=rows(field(service,"audio_pids"));if(!audio.empty())metadata+=",c:01"+hex(json_object_get_int(audio[0]),4);
		if(old.services.count(identity))for(const auto& extra:split(old.services.at(identity)[2],','))if(extra.rfind("p:",0) && extra.rfind("c:00",0) && extra.rfind("c:01",0) && extra.rfind("c:03",0) && extra.rfind("c:05",0))metadata+=","+extra;
		std::string name=clean(str(service,"name"));updated.services[identity]={hex(sid,4)+":"+hex(ns,8)+":"+hex(tsid,4)+":"+hex(onid,4)+":"+std::to_string(kind)+":0",name,metadata};
		Json channel(json_object_new_object(),json_object_put);put(channel.get(),"name",name);put(channel.get(),"reference",ref);put(channel.get(),"frequency",frequency/1000);put(channel.get(),"symbol_rate",rate/1000);put(channel.get(),"polarization",std::string(1,"HVLR"[pol]));put(channel.get(),"quality",kind==17 || kind==25 || kind==134?"HD":"SD");put(channel.get(),"satellite",std::string("Türksat 42°E"));put(channel.get(),"lcn",positions[lcn]);put(channel.get(),"tkgs_lcn",lcn);json_object_object_add(channel.get(),"encrypted",json_object_new_boolean(num(service,"encrypted")));
		if(previousNames.count(name))put(channel.get(),"picon",str(previousNames[name],"picon"));
		catalog.push_back(std::move(channel));
	}
	require(!catalog.empty(),"Uygulanabilecek TV kanalı yok; mevcut liste korunuyor");bool flexible=str(options.get(),"mode","flexible")=="flexible";
	std::stable_sort(catalog.begin(),catalog.end(),[&](const Json& a,const Json& b) { auto rank=[&](json_object* c) { auto ref=str(c,"reference");int lcn=num(c,"lcn");return std::make_pair(flexible && priority.count(ref)?priority.at(ref):100000+lcn,lcn); };return rank(a.get())<rank(b.get()); });
	Json result(json_object_new_object(),json_object_put);put(result.get(),"database",serialize(updated));std::string bouquet="#NAME Magic Box TKGS\n";auto channels=json_object_new_array();for(auto& channel:catalog) { bouquet+="#SERVICE "+str(channel.get(),"reference")+"\n#DESCRIPTION "+str(channel.get(),"name")+"\n";json_object_array_add(channels,channel.release()); }
	put(result.get(),"bouquet",bouquet);auto cat=json_object_new_object();json_object_object_add(cat,"channels",channels);put(cat,"source",std::string("Türksat TKGS uydu tablosu"));put(cat,"tkgs_sha256",str(table.get(),"sha256"));json_object_object_add(cat,"tkgs_versions",json_object_get(field(table.get(),"versions")));json_object_object_add(result.get(),"catalog",cat);put(result.get(),"tv",json_object_array_length(channels));put(result.get(),"filtered",filtered);put(result.get(),"added",updated.services.size()-old.services.size());put(result.get(),"sha256",str(table.get(),"sha256"));json_object_object_add(result.get(),"unresolved",json_object_new_array());return encode(result.get());
}
bool recover(const std::string& directory) {
	fs::path root=directory,state=root/"magicbox-tkgs",marker=state/"transaction.json";if(!fs::exists(marker))return false;auto transaction=parse(read(marker));auto name=str(transaction.get(),"backup");require(backupName(name),"TKGS kurtarma kaydı geçersiz");restoreSnapshot(root,state/"backups"/name);fs::remove(marker);syncDir(state);return true;
}
std::string commit(const std::string& raw,const std::string& directory) {
	fs::path root=directory,state=root/"magicbox-tkgs";recover(directory);auto result=parse(raw);
	uint64_t required=128*1024;
	for(const auto& name:FILES)if(fs::exists(root/name))required+=fs::file_size(root/name);
	required+=str(result.get(),"database").size()+str(result.get(),"bouquet").size()+encode(field(result.get(),"catalog")).size();
	if(fs::exists(root/"bouquets.tv"))required+=fs::file_size(root/"bouquets.tv");
	struct statvfs disk;require(statvfs(root.c_str(),&disk)==0,"Boş alan denetlenemedi");require(disk.f_bavail*static_cast<uint64_t>(disk.f_frsize)>required,"Güncelleme/yedek için boş alan yetersiz");
	auto ticks=std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
	time_t seconds=static_cast<time_t>(ticks/1000000);tm local{};localtime_r(&seconds,&local);std::ostringstream stamp;stamp<<std::put_time(&local,"%Y%m%d-%H%M%S-")<<std::setfill('0')<<std::setw(6)<<ticks%1000000;
	fs::path backup=state/"backups"/stamp.str();fs::create_directories(backup);Json manifest(json_object_new_object(),json_object_put);
	for(const auto& name:FILES) { bool existed=fs::exists(root/name);json_object_object_add(manifest.get(),name.c_str(),json_object_new_boolean(existed));if(existed)atomic(backup/name,read(root/name)); }
	atomic(backup/"files.json",encode(manifest.get()));Json transaction(json_object_new_object(),json_object_put);put(transaction.get(),"backup",backup.filename().string());atomic(state/"transaction.json",encode(transaction.get()));
	try {
		atomic(root/"lamedb",str(result.get(),"database"));atomic(root/"userbouquet.magicbox.tv",str(result.get(),"bouquet"));std::string index=fs::exists(root/"bouquets.tv")?read(root/"bouquets.tv"):"#NAME Bouquets (TV)\n";auto lines=split(index);lines.erase(std::remove_if(lines.begin(),lines.end(),[](const std::string& line) { return line.find("\"userbouquet.magicbox.tv\"")!=std::string::npos; }),lines.end());lines.insert(lines.begin()+std::min<size_t>(1,lines.size()),"#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET \"userbouquet.magicbox.tv\" ORDER BY bouquet");index.clear();for(const auto& line:lines)index+=line+'\n';atomic(root/"bouquets.tv",index);atomic(state/"channels.json",encode(field(result.get(),"catalog")));Json installed(json_object_new_object(),json_object_put);put(installed.get(),"sha256",str(result.get(),"sha256"));put(installed.get(),"tv",num(result.get(),"tv"));atomic(state/"installed.json",encode(installed.get()));fs::remove(state/"transaction.json");syncDir(state);
	} catch(...) { restoreSnapshot(root,backup);fs::remove(state/"transaction.json");syncDir(state);throw; }
	// Pruning must never turn a successful channel transaction into a failure.
	try { auto retained=backups(state/"backups");while(retained.size()>3) { fs::remove_all(retained.front());retained.erase(retained.begin()); } }catch(const fs::filesystem_error&) {}
	return backup.string();
}
std::string restore(const std::string& directory) {
	fs::path root=directory;auto candidates=backups(root/"magicbox-tkgs/backups");require(!candidates.empty(),"Geri yüklenecek TKGS yedeği yok");restoreSnapshot(root,candidates.back());return candidates.back().string();
}
} }
