#include <lib/gui/emagicboximages.h>
#include <lib/base/message.h>
#include <lib/magicbox/curltransfer.h>
#include <curl/curl.h>
#include <json-c/json.h>
#include <atomic>
#include <mutex>
#include <thread>

struct eMagicBoxImages::State {
	eFixedMessagePump<int> pump{eApp,1};
	std::thread worker;
	std::atomic<bool> stop{false},busy{false};
	mutable std::mutex mutex;
	std::string data,error,notes;
	~State() { stop=true;if(worker.joinable())worker.join(); }
};
eMagicBoxImages::eMagicBoxImages():m(new State) { CONNECT(m->pump.recv_msg,eMagicBoxImages::receive); }
eMagicBoxImages::~eMagicBoxImages() { delete m; }
std::string eMagicBoxImages::getData() const { std::lock_guard<std::mutex> guard(m->mutex);return m->data; }
std::string eMagicBoxImages::getError() const { std::lock_guard<std::mutex> guard(m->mutex);return m->error; }
std::string eMagicBoxImages::getNotes() const { std::lock_guard<std::mutex> guard(m->mutex);return m->notes; }
void eMagicBoxImages::receive(const int& event) { completed(event); }
void eMagicBoxImages::load() {
	if(m->busy.exchange(true))return;
	if(m->worker.joinable())m->worker.join();
	m->worker=std::thread([this] {
		std::string body,error,notes;CURL* curl=curl_easy_init();
		if(curl) {
			curl_easy_setopt(curl,CURLOPT_URL,"https://45.87.174.241:8448/images/vuduo.json");
			curl_easy_setopt(curl,CURLOPT_CAINFO,"/usr/share/ca-certificates/magicbox/updates.crt");
			curl_easy_setopt(curl,CURLOPT_CONNECTTIMEOUT,3L);curl_easy_setopt(curl,CURLOPT_TIMEOUT,10L);curl_easy_setopt(curl,CURLOPT_NOSIGNAL,1L);
			curl_easy_setopt(curl,CURLOPT_FOLLOWLOCATION,0L);curl_easy_setopt(curl,CURLOPT_NOPROGRESS,0L);
			curl_easy_setopt(curl,CURLOPT_XFERINFODATA,&m->stop);
			curl_easy_setopt(curl,CURLOPT_XFERINFOFUNCTION,+[](void* context,curl_off_t,curl_off_t,curl_off_t,curl_off_t)->int { return *static_cast<std::atomic<bool>*>(context); });
			curl_easy_setopt(curl,CURLOPT_WRITEDATA,&body);
			curl_easy_setopt(curl,CURLOPT_WRITEFUNCTION,+[](char* data,size_t a,size_t b,void* context)->size_t { auto& body=*static_cast<std::string*>(context);size_t n=a*b;if(body.size()+n>1024*1024)return 0;body.append(data,n);return n; });
			auto code=MagicBox::performCancellable(curl,m->stop);long status=0;curl_easy_getinfo(curl,CURLINFO_RESPONSE_CODE,&status);curl_easy_cleanup(curl);
			if(code!=CURLE_OK || status!=200) { body.clear();error="Magic Box imaj listesi alınamadı. Yerel USB imajlarını seçebilirsiniz."; }
		} else error="İmaj listesi istemcisi başlatılamadı.";
		if(m->stop) { m->busy=false;return; }
		if(error.empty()) {
			auto root=json_tokener_parse(body.c_str());
			if(root && json_object_get_type(root)==json_type_object) {
				json_object_object_foreach(root,category,images) {
					(void)category;if(json_object_get_type(images)!=json_type_object)continue;
					json_object_object_foreach(images,key,image) {
						(void)key;json_object *name=nullptr,*text=nullptr;
						if(!image || json_object_get_type(image)!=json_type_object || !json_object_object_get_ex(image,"release_notes",&text) || json_object_get_type(text)!=json_type_string)continue;
						json_object_object_get_ex(image,"name",&name);
						if(name && json_object_get_type(name)==json_type_string)notes+=std::string(json_object_get_string(name)).substr(0,256)+"\n\n";
						notes+=std::string(json_object_get_string(text)).substr(0,8192)+"\n\n";
						if(notes.size()>32768) { notes.resize(32768);break; }
					}
					if(notes.size()>=32768)break;
				}
			}else error="Magic Box imaj listesi geçersiz.";
			json_object_put(root);
			if(notes.empty())notes="Yeni sürüm notu henüz yayımlanmadı.";
		}
		if(m->stop) { m->busy=false;return; }
		{ std::lock_guard<std::mutex> guard(m->mutex);m->data=body;m->error=error;m->notes=notes; }
		m->pump.send(error.empty()?0:1);m->busy=false;
	});
}
