/* Separate wire implementation based on the existing Magic Box test fixtures.
 * MPEG/DVB lengths/CRC are strict; an incomplete table cannot be installed.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "tkgs.h"
#include "model.h"
#include <json-c/json.h>
#include <algorithm>
#include <array>
#include <cerrno>
#include <iconv.h>
#include <memory>
#include <set>
#include <stdexcept>
#include <tuple>

namespace MagicBox { namespace TKGS {
namespace {
constexpr size_t MAX_BYTES = 8*1024*1024;
void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
using Json = std::unique_ptr<json_object, decltype(&json_object_put)>;
void put(json_object* object,const char* key,int value) { json_object_object_add(object,key,json_object_new_int(value)); }
void put(json_object* object,const char* key,const std::string& value) { json_object_object_add(object,key,json_object_new_string(value.c_str())); }
struct Cursor {
	Bytes data; size_t offset = 0;
	explicit Cursor(Bytes input): data(std::move(input)) {}
	size_t left() const { return data.size()-offset; }
	Bytes take(size_t count) { require(count <= left(),"Tablo eksik veya alan uzunluğu geçersiz"); Bytes out(data.begin()+offset,data.begin()+offset+count); offset+=count; return out; }
	int byte() { require(left()>=1,"Tablo eksik"); return data[offset++]; }
	int word() { int a=byte(); return (a<<8)|byte(); }
	Bytes block() { int n=word(); return take(n); }
};
int word(const Bytes& b,size_t offset) { require(offset+2<=b.size(),"Tablo eksik"); return (b[offset]<<8)|b[offset+1]; }
using Descriptors = std::vector<std::pair<int,Bytes>>;
Descriptors descriptors(const Bytes& bytes) { Cursor c(bytes); Descriptors out; while(c.left()) { int tag=c.byte(),n=c.byte(); out.push_back({tag,c.take(n)}); } return out; }
Bytes slice(const Bytes& bytes,size_t offset,size_t count) { require(offset<=bytes.size() && count<=bytes.size()-offset,"Tablo eksik"); return {bytes.begin()+offset,bytes.begin()+offset+count}; }
std::string text(Bytes bytes) {
	if(bytes.empty()) return "";
	std::string encoding="ISO-8859-9"; size_t offset=0;
	if(bytes[0]==0x15) { encoding="UTF-8";offset=1; }
	else if(bytes[0]==0x11) { encoding="UTF-16BE";offset=1; }
	else if(bytes[0]==0x10) { require(bytes.size()>=3 && bytes[1]==0 && bytes[2]>=1 && bytes[2]<=15 && bytes[2]!=12,"Geçersiz metin kodlaması");encoding="ISO-8859-"+std::to_string(bytes[2]);offset=3; }
	else if(bytes[0]>=1 && bytes[0]<=11) { require(bytes[0]!=8,"Geçersiz metin kodlaması");encoding="ISO-8859-"+std::to_string(bytes[0]+4);offset=1; }
	else require(bytes[0]>=32,"Desteklenmeyen DVB metin kodlaması");
	iconv_t converter=iconv_open("UTF-8",encoding.c_str()); require(converter!=reinterpret_cast<iconv_t>(-1),"Metin kodlaması açılamadı");
	std::string output(bytes.size()*4+4,'\0'); char* source=reinterpret_cast<char*>(bytes.data()+offset); size_t inputLeft=bytes.size()-offset, outputLeft=output.size(); char* destination=&output[0];
	bool ok=iconv(converter,&source,&inputLeft,&destination,&outputLeft)!=static_cast<size_t>(-1);iconv_close(converter);require(ok,"Geçersiz DVB metni");output.resize(output.size()-outputLeft);
	std::string clean; bool space=false;
	for(size_t i=0;i<output.size();) {
		unsigned char ch=output[i]; size_t count=ch<128?1:ch<224?2:ch<240?3:4;
		bool control=ch<=32 || ch==127 || (ch==0xc2 && i+1<output.size() && static_cast<unsigned char>(output[i+1])>=0x80 && static_cast<unsigned char>(output[i+1])<=0x9f);
		if(control) space=!clean.empty(); else { if(space)clean+=' '; space=false;clean.append(output,i,count); }
		i+=count; if(clean.size()>640)break;
	}
	return clean;
}
Bytes section(Cursor& c,int table) { auto header=c.take(3);int n=((header[1]&15)<<8)|header[2];auto tail=c.take(n);header.insert(header.end(),tail.begin(),tail.end());require(header.size()>=12 && header[0]==table && (header[1]&0x80) && (header[5]&1) && header[6]<=header[7] && crc(header)==0,"Bölüm kimliği, uzunluğu veya CRC geçersiz");return header; }
int decimal(const Bytes& bytes) { int value=0;for(auto b:bytes) { require((b>>4)<10 && (b&15)<10,"Geçersiz BCD değeri");value=value*100+(b>>4)*10+(b&15); }return value; }
Json satellite(const Bytes& bytes) {
	require(bytes.size()==11,"Uydu descriptor uzunluğu geçersiz");
	int frequency=decimal(slice(bytes,0,4))*10, orbit=decimal(slice(bytes,4,2));require((bytes[10]>>4)<10,"Sembol hızı BCD değeri geçersiz");
	int rate=(decimal(slice(bytes,7,3))*10+(bytes[10]>>4))*100;if(!(bytes[6]&0x80))orbit=(3600-orbit)%3600;
	require(frequency>=3000000 && frequency<=13000000 && rate>=1000000 && rate<=50000000 && orbit==420,"TKGS tablosu Türksat 42°E yayın parametrelerini içermiyor");
	Json value(json_object_new_object(),json_object_put);put(value.get(),"frequency",frequency);put(value.get(),"symbol_rate",rate);put(value.get(),"orbital_position",orbit);put(value.get(),"polarisation",(bytes[6]>>5)&3);put(value.get(),"system",(bytes[6]>>2)&1);put(value.get(),"modulation",bytes[6]&3);put(value.get(),"rolloff",(bytes[6]>>3)&3);put(value.get(),"fec",bytes[10]&15);return value;
}
std::map<int,Json> services(Cursor& input) {
	std::map<int,Json> result; std::tuple<int,int,int,int> identity;bool first=true;std::set<int> parts;
	while(true) {
		auto data=section(input,0x42); require(data.size()>=15,"SDT başlığı eksik");
		int tsid=word(data,3),onid=word(data,8);auto group=std::make_tuple(tsid,onid,(data[5]>>1)&31,data[7]);require(first || identity==group,"SDT kimlikleri veya sürümü tutarsız");identity=group;first=false;
		require(parts.insert(data[6]).second,"Tekrarlanan SDT bölümü");Cursor c(slice(data,11,data.size()-15));
		while(c.left()) {
			int sid=c.word();c.byte();int info=c.word();Json meta(json_object_new_object(),json_object_put);
			put(meta.get(),"sid",sid);put(meta.get(),"tsid",tsid);put(meta.get(),"onid",onid);json_object_object_add(meta.get(),"encrypted",json_object_new_boolean(info&0x1000));put(meta.get(),"name",std::string());put(meta.get(),"provider",std::string());put(meta.get(),"service_type",0);json_object_object_add(meta.get(),"category",nullptr);
			for(const auto& descriptor:descriptors(c.take(info&4095))) {
				if(descriptor.first==0x48) { Cursor d(descriptor.second);put(meta.get(),"service_type",d.byte());int n=d.byte();put(meta.get(),"provider",text(d.take(n)));n=d.byte();put(meta.get(),"name",text(d.take(n)));require(!d.left(),"Servis açıklaması uzunluğu tutarsız"); }
				else if(descriptor.first==0x95 && descriptor.second.size()>=8) put(meta.get(),"category",word(descriptor.second,6)>>4);
			}
			require(!result.count(sid),"SDT içinde tekrarlanan servis kimliği");result.emplace(sid,std::move(meta));
		}
		if(parts.size()==static_cast<size_t>(data[7]+1))return result;
		require(input.left()>0,"SDT bölümleri eksik");
	}
}
void pmt(const Bytes& data,json_object* channel) {
	Cursor c(slice(data,8,data.size()-12));put(channel,"pcr_pid",c.word()&8191);int n=c.word()&4095;c.take(n);
	json_object_object_add(channel,"video_pid",nullptr);json_object_object_add(channel,"video_type",nullptr);auto audio=json_object_new_array();json_object_object_add(channel,"audio_pids",audio);bool video=false;
	while(c.left()) {
		int type=c.byte(),pid=c.word()&8191,length=c.word()&4095;descriptors(c.take(length));
		if(!video && (type==1 || type==2 || type==16 || type==27 || type==36)) { put(channel,"video_pid",pid);put(channel,"video_type",type==16?4:type==27?1:type==36?7:0);video=true; }
		else if(type==3 || type==4 || type==15 || type==17 || type==129 || type==135)json_object_array_add(audio,json_object_new_int(pid));
	}
}
}
uint32_t crc(const Bytes& bytes) {
	static const auto table=[] { std::array<uint32_t,256> t{};for(unsigned i=0;i<256;++i) { uint32_t a=i<<24;for(int b=0;b<8;++b)a=(a<<1)^((a&0x80000000)?0x04c11db7:0);t[i]=a; }return t; }();
	uint32_t value=0xffffffff;for(auto b:bytes)value=(value<<8)^table[(value>>24)^b];return value;
}
bool Sections::add(const Bytes& data) {
	require(data.size()>=12 && data[0]==TABLE_ID && (data[1]&0x80) && data.size()==static_cast<size_t>(3+((data[1]&15)<<8)+data[2]) && (data[5]&1) && data[6]<=data[7] && crc(data)==0,"TKGS bölüm kimliği, uzunluğu veya CRC geçersiz");
	int id=word(data,3),version=(data[5]>>1)&31,number=data[6],last=data[7];require(m_groups.count(id) || m_groups.size()<64,"Çok fazla TKGS tablo grubu");auto& group=m_groups[id];
	if(group.version>=0 && group.version!=version) { if((version-group.version+32)%32>=16)return false;for(const auto& part:group.parts)m_bytes-=part.second.size();group=Group(); }
	if(group.version<0) { group.version=version;group.last=last; }
	require(last==group.last,"Aynı sürümde tutarsız bölüm sayısı");
	if(group.parts.count(number)) { require(group.parts[number]==data,"Aynı sürümde çelişen TKGS bölümü");return false; }
	require(m_bytes+data.size()<=MAX_BYTES,"TKGS tablosu boyut sınırını aştı");group.parts[number]=data;m_bytes+=data.size();return true;
}
bool Sections::complete() const { if(m_groups.empty())return false;for(const auto& pair:m_groups)if(pair.second.parts.size()!=static_cast<size_t>(pair.second.last+1))return false;return true; }
std::vector<Bytes> Sections::ordered() const { require(complete(),"TKGS tablosunda eksik bölümler var");std::vector<Bytes> out;for(const auto& pair:m_groups)for(const auto& part:pair.second.parts)out.push_back(part.second);return out; }
std::map<int,int> Sections::versions() const { std::map<int,int> out;for(const auto& pair:m_groups)out[pair.first]=pair.second.version;return out; }
void Stream::emit(std::vector<Bytes>& output) {
	while(!m_pending.empty()) {
		if(m_pending.front()==255) { m_pending.clear();break; }
		if(m_pending.size()<3)break;
		if(!m_transport && (m_pending[0]!=TABLE_ID || !(m_pending[1]&0x80))) { m_pending.erase(m_pending.begin());continue; }
		size_t n=3+((m_pending[1]&15)<<8)+m_pending[2];if(n<12) { m_pending.erase(m_pending.begin());continue; }
		if(m_pending.size()<n)break;
		if(m_pending[0]==TABLE_ID)output.push_back(slice(m_pending,0,n));
		m_pending.erase(m_pending.begin(),m_pending.begin()+n);
	}
	require(m_pending.size()<65536,"Bölüm tamponu sınırı aşıldı");
}
std::vector<Bytes> Stream::feed(const Bytes& input) {
	require(input.size()<=MAX_BYTES*8,"Kayıt dosyası çok büyük");std::vector<Bytes> output;
	if(!m_transport) { m_pending.insert(m_pending.end(),input.begin(),input.end());emit(output);return output; }
	m_buffer.insert(m_buffer.end(),input.begin(),input.end());size_t offset=0;
	while(m_buffer.size()-offset>=188) {
		if(m_buffer[offset]!=0x47) { ++offset;continue; }
		auto packet=slice(m_buffer,offset,188);offset+=188;
		if((((packet[1]&31)<<8)|packet[2])!=PID)continue;
		int mode=(packet[3]>>4)&3,counter=packet[3]&15;
		if((packet[1]&0x80) || (packet[3]&0xc0)) { m_pending.clear();m_counter=-1;continue; }
		if(mode!=1 && mode!=3)continue;
		size_t start=mode==3?5+packet[4]:4;if(start>=188)continue;
		if(mode==3 && packet[4] && (packet[5]&0x80)) { m_pending.clear();m_counter=-1; }
		if(counter==m_counter)continue;
		if(m_counter>=0 && counter!=(m_counter+1)%16)m_pending.clear();
		m_counter=counter;
		auto payload=slice(packet,start,188-start);
		if(packet[1]&0x40) {
			size_t pointer=payload[0];if(pointer>=payload.size()) { m_pending.clear();continue; }
			m_pending.insert(m_pending.end(),payload.begin()+1,payload.begin()+1+pointer);emit(output);m_pending.assign(payload.begin()+1+pointer,payload.end());
		} else if(!m_pending.empty())m_pending.insert(m_pending.end(),payload.begin(),payload.end());
		emit(output);
	}
	m_buffer.erase(m_buffer.begin(),m_buffer.begin()+offset);return output;
}
std::string decode(const std::vector<Bytes>& sections) {
	Sections collection;for(const auto& s:sections)collection.add(s);auto ordered=collection.ordered();Bytes payload,joined;
	for(const auto& s:ordered) { payload.insert(payload.end(),s.begin()+8,s.end()-4);joined.insert(joined.end(),s.begin(),s.end()); }
	Cursor c(payload);std::string name;
	for(const auto& d:descriptors(c.block()))if(d.first==0x90 && d.second.size()>=4)name=text(slice(d.second,4,std::min<size_t>(d.second[3],d.second.size()-4)));
	bool found=false;
	for(size_t position=c.offset;position<std::min(c.offset+512,payload.size());++position) {
		size_t count=payload[position];if(count<13 || position+1+count>=payload.size() || payload[position+1+count]!=0x42)continue;
		try { for(const auto& d:descriptors(slice(payload,position+1,count)))if(d.first==0x43 && d.second.size()==11) { c.offset=position;found=true;break; } }catch(const std::runtime_error&) {}
		if(found)break;
	}
	require(found,"TKGS yayın parametreleri bulunamadı");Json root(json_object_new_object(),json_object_put);auto carriers=json_object_new_array(),channels=json_object_new_array(),orders=json_object_new_object(),categories=json_object_new_object();
	json_object_object_add(root.get(),"carriers",carriers);json_object_object_add(root.get(),"channels",channels);json_object_object_add(root.get(),"orders",orders);json_object_object_add(root.get(),"categories",categories);std::set<int> identifiers;std::map<int,Json> sorted;
	while(true) {
		int n=c.byte();if(!n)break;Json carrier(nullptr,json_object_put);
		for(const auto& d:descriptors(c.take(n)))if(d.first==0x43) { require(!carrier,"Tek uydu yayın descriptorı bekleniyor");carrier=satellite(d.second); }
		require(bool(carrier),"Uydu yayın descriptorı eksik");int index=json_object_array_length(carriers);json_object_array_add(carriers,carrier.release());auto sdt=services(c);Cursor entries(c.block());
		while(entries.left()) {
			int lcn=entries.word();auto data=section(entries,2);int sid=word(data,3);require(sdt.count(sid) && lcn>0 && identifiers.insert(lcn).second,"Kanal numarası veya SDT/PMT eşleştirmesi geçersiz");
			auto meta=json_object_get(sdt.at(sid).get());Json channel(meta,json_object_put);put(meta,"lcn",lcn);put(meta,"carrier",index);pmt(data,meta);json_object* title=nullptr;json_object_object_get_ex(meta,"name",&title);require(title && json_object_get_string_len(title)>0,"Kanal adı eksik");sorted.emplace(lcn,std::move(channel));
		}
	}
	if(c.left()) {
		Cursor loop(c.block());while(loop.left()) {
			int n=loop.word()&4095;std::string title;auto rows=json_object_new_array();Json owned(rows,json_object_put);std::set<int> positions;
			for(const auto& d:descriptors(loop.take(n))) {
				if(d.first==0x93 && d.second.size()>=4)title=text(slice(d.second,4,std::min<size_t>(d.second[3],d.second.size()-4)));
				else if(d.first==0x94) { require(d.second.size()==4,"Kanal sıralama descriptorı geçersiz");int a=word(d.second,0),b=word(d.second,2);require(positions.insert(a).second && identifiers.count(b),"Kanal sıralama listesi tutarsız");auto row=json_object_new_array();json_object_array_add(row,json_object_new_int(a));json_object_array_add(row,json_object_new_int(b));json_object_array_add(rows,row); }
			}
			json_object* existing=nullptr;require(!title.empty() && !json_object_object_get_ex(orders,title.c_str(),&existing),"Kanal sıralama adı eksik veya tekrar ediyor");json_object_object_add(orders,title.c_str(),owned.release());
		}
	}
	if(c.left())for(const auto& d:descriptors(c.block()))if(d.first==0x92 && d.second.size()>=6) { auto title=text(slice(d.second,6,std::min<size_t>(d.second[5],d.second.size()-6)));put(categories,std::to_string(word(d.second,0)>>4).c_str(),title); }
	require(!c.left() && !sorted.empty() && json_object_array_length(carriers)>0,"Tablo sonu veya kanal sayısı geçersiz");for(auto& pair:sorted)json_object_array_add(channels,pair.second.release());
	put(root.get(),"name",name.empty()?"Türksat TKGS":name);auto versions=json_object_new_object();for(const auto& pair:collection.versions())put(versions,std::to_string(pair.first).c_str(),pair.second);json_object_object_add(root.get(),"versions",versions);put(root.get(),"sha256",Model::digest(std::string(joined.begin(),joined.end())));json_object_object_add(root.get(),"crc_verified",json_object_new_boolean(true));return json_object_to_json_string_ext(root.get(),JSON_C_TO_STRING_PLAIN);
}
std::string capture(const Bytes& bytes) { require(bytes.size()<=MAX_BYTES*8,"Kayıt dosyası çok büyük");Stream stream(!bytes.empty() && bytes.front()==0x47);return decode(stream.feed(bytes)); }
std::string capture(std::istream& input,const std::function<bool()>& cancelled) {
	require(bool(input),"Kayıt dosyası okunamadı");
	Stream stream(input.peek()==0x47);Sections collection;std::array<char,65536> buffer{};size_t total=0;
	while(input) {
		require(!cancelled || !cancelled(),"TKGS okuması iptal edildi; mevcut liste korundu.");
		input.read(buffer.data(),buffer.size());auto count=input.gcount();total+=count;
		require(total<=MAX_BYTES*8,"Kayıt dosyası çok büyük");
		if(count)for(const auto& section:stream.feed(Bytes(buffer.begin(),buffer.begin()+count)))collection.add(section);
	}
	require(input.eof(),"Kayıt dosyası eksik okundu");
	return decode(collection.ordered());
}
} }
