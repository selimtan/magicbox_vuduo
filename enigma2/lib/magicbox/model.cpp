/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "model.h"
#include <json-c/json.h>
#include <curl/curl.h>
#include <openssl/sha.h>
#include <zlib.h>
#include <algorithm>
#include <array>
#include <cctype>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <set>
#include <stdexcept>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace MagicBox {
namespace {
constexpr size_t MAX_BYTES = 8 * 1024 * 1024;
using Json = std::unique_ptr<json_object, decltype(&json_object_put)>;
Json json(const std::string& text) {
	json_tokener* tok = json_tokener_new_ex(32);
	if (!tok) throw std::bad_alloc();
	json_object* value = json_tokener_parse_ex(tok, text.data(), text.size());
	bool ok = json_tokener_get_error(tok) == json_tokener_success;
	json_tokener_free(tok);
	if (!ok || !value) { if (value) json_object_put(value); throw std::runtime_error("Veri biçimi geçersiz."); }
	return Json(value, json_object_put);
}
json_object* field(json_object* object, const char* name) {
	json_object* value = nullptr;
	if (object && json_object_get_type(object) == json_type_object) json_object_object_get_ex(object, name, &value);
	return value;
}
std::string str(json_object* object, const char* name, const std::string& fallback = "") {
	auto value = field(object, name);
	if (!value || (json_object_get_type(value) != json_type_string && json_object_get_type(value) != json_type_int && json_object_get_type(value) != json_type_boolean)) return fallback;
	std::string result = json_object_get_string(value);
	return result.substr(0, 2048);
}
void put(json_object* object, const char* name, const std::string& value) {
	json_object_object_add(object, name, json_object_new_string_len(value.data(), value.size()));
}
std::string read(const std::string& path) {
	std::ifstream file(path, std::ios::binary);
	if (!file) throw std::runtime_error("Dosya okunamadı.");
	file.seekg(0, std::ios::end); std::streamoff n = file.tellg();
	if (n < 0 || n > static_cast<std::streamoff>(MAX_BYTES)) throw std::runtime_error("Dosya boyut sınırını aştı.");
	file.seekg(0); std::string text(static_cast<size_t>(n), '\0');
	if (n && !file.read(&text[0], n)) throw std::runtime_error("Dosya tamamlanamadı.");
	return text;
}
void atomic(const std::string& path, const std::string& text) {
	auto dir = std::filesystem::path(path).parent_path();
	std::filesystem::create_directories(dir);
	if (chmod(dir.c_str(), 0700)) throw std::runtime_error("Özel dizin korunamadı.");
	std::string temporary = path + ".new.XXXXXX";
	std::vector<char> name(temporary.begin(), temporary.end()); name.push_back(0);
	int fd = mkstemp(name.data());
	if (fd < 0) throw std::runtime_error("Dosya oluşturulamadı.");
	bool ok = fchmod(fd, 0600) == 0;
	size_t done = 0;
	while (ok && done < text.size()) {
		auto n = write(fd, text.data() + done, text.size() - done);
		if (n < 0 && errno == EINTR) continue;
		if (n <= 0) { ok = false; break; } done += n;
	}
	if (ok) ok = fsync(fd) == 0;
	if (close(fd)) ok = false;
	if (!ok || rename(name.data(), path.c_str())) { unlink(name.data()); throw std::runtime_error("Dosya kaydedilemedi."); }
	fd = open(dir.c_str(), O_RDONLY | O_DIRECTORY);
	if (fd >= 0) { fsync(fd); close(fd); }
}
std::string readCache(const std::string& path) {
	gzFile file=gzopen(path.c_str(),"rb");if(!file)throw std::runtime_error("Önbellek okunamadı.");
	std::string text;std::array<char,65536> buffer{};int count=0;
	while((count=gzread(file,buffer.data(),buffer.size()))>0) {
		if(text.size()+count>MAX_BYTES) { gzclose(file);throw std::runtime_error("Önbellek boyut sınırını aştı."); }
		text.append(buffer.data(),count);
	}
	int result=gzclose(file);if(count<0 || result!=Z_OK)throw std::runtime_error("Önbellek eksik.");return text;
}
void saveCache(const std::string& path,const std::string& text) {
	constexpr size_t limit=2*1024*1024;
	z_stream stream{};
	if(deflateInit2(&stream,1,Z_DEFLATED,MAX_WBITS+16,8,Z_DEFAULT_STRATEGY)!=Z_OK)throw std::runtime_error("Önbellek hazırlanamadı.");
	stream.next_in=reinterpret_cast<Bytef*>(const_cast<char*>(text.data()));stream.avail_in=text.size();
	std::string compressed;std::array<unsigned char,65536> buffer{};int result=Z_OK;
	do {
		stream.next_out=buffer.data();stream.avail_out=buffer.size();result=deflate(&stream,Z_FINISH);
		compressed.append(reinterpret_cast<const char*>(buffer.data()),buffer.size()-stream.avail_out);
		if(compressed.size()>limit) { deflateEnd(&stream);return; }
	}while(result==Z_OK);
	deflateEnd(&stream);if(result!=Z_STREAM_END)throw std::runtime_error("Önbellek hazırlanamadı.");
	atomic(path,compressed);
	std::vector<std::filesystem::path> files;auto base=std::filesystem::path(path).parent_path();
	for(const auto& entry:std::filesystem::directory_iterator(base)) {
		auto name=entry.path().filename().string();
		if(!entry.is_symlink() && entry.is_regular_file() && name.size()==72 && name.substr(64)==".json.gz" && name.substr(0,64).find_first_not_of("0123456789abcdef")==std::string::npos)files.push_back(entry.path());
	}
	std::sort(files.begin(),files.end(),[](const auto& a,const auto& b) { return std::filesystem::last_write_time(a)>std::filesystem::last_write_time(b); });
	size_t used=0;
	for(size_t i=0;i<files.size();++i) { used+=std::filesystem::file_size(files[i]);if(used>limit || i>=96)std::filesystem::remove(files[i]); }
}
bool digits(const std::string& value) {
	return !value.empty() && value.size() < 24 && std::all_of(value.begin(), value.end(), [](unsigned char c) { return c >= '0' && c <= '9'; });
}
bool scopeValid(const std::string& value) {
	return value.size() == 64 && value.find_first_not_of("0123456789abcdef") == std::string::npos;
}
std::string extension(std::string value, const std::string& fallback) {
	if (!value.empty() && value[0] == '.') value.erase(0, 1);
	if (value.empty() || value.size() > 8 || value.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789") != std::string::npos) return fallback;
	return value;
}
Row rowFrom(json_object* value) {
	Row r; r.name = str(value, "name", "İsimsiz yayın"); r.id = str(value, "id");
	r.kind = str(value, "kind", "stream"); r.group = str(value, "group", "tv");
	r.reference = str(value, "reference"); r.scope = str(value, "scope");
	r.extension = extension(str(value, "extension"), r.group == "live" ? "ts" : "mp4");
	r.picon = str(value, "picon"); r.detail = str(value, "detail");
	if (r.group == "tv") {
		// DVB references only: never persist a receiver service URL into public metadata.
		if (r.reference.find_first_not_of("0123456789abcdefABCDEF:") != std::string::npos) r.reference.clear();
		std::transform(r.reference.begin(), r.reference.end(), r.reference.begin(), [](unsigned char c) { return std::tolower(c); });
		if(!r.reference.empty())r.key="tv:"+r.reference;
		else {
			auto previous=str(value,"key");
			if(previous.rfind("tv:pending:",0)==0 && scopeValid(previous.substr(11)))r.key=previous;
			else {
				std::string identity="[";int i=0;
				for(auto key:{"name","frequency","polarization","symbol_rate","satellite"}) {
					if(i++)identity+=", ";
					auto item=field(value,key);Json empty(json_object_new_string(""),json_object_put);
					identity+=json_object_to_json_string_ext(item?item:empty.get(),JSON_C_TO_STRING_PLAIN|JSON_C_TO_STRING_NOSLASHESCAPE);
				}
				r.key="tv:pending:"+Model::digest(identity+"]");
			}
		}
	} else if (r.playable() && digits(r.id) && scopeValid(r.scope)) r.key = "iptv:" + r.scope + ":" + r.group + ":" + r.id;
	auto children = field(value, "children");
	if (children && json_object_get_type(children) == json_type_array)
		for (size_t i = 0; i < json_object_array_length(children); ++i) r.children.push_back(rowFrom(json_object_array_get_idx(children, i)));
	return r;
}
json_object* rowJson(const Row& r) {
	auto value = json_object_new_object();
	put(value, "name", r.name); put(value, "id", r.id); put(value, "kind", r.kind); put(value, "group", r.group);
	put(value, "reference", r.group == "tv" ? r.reference : ""); put(value, "scope", r.scope);
	put(value, "extension", r.extension); put(value, "picon", r.picon); put(value, "detail", r.detail);
	put(value, "source", r.group == "tv" ? "tv" : "iptv"); put(value, "key", r.key);
	if (!r.children.empty()) { auto children = json_object_new_array(); for (const auto& child : r.children) json_object_array_add(children, rowJson(child)); json_object_object_add(value, "children", children); }
	return value;
}
std::string serialize(const Page& page, const char* arrayName = "rows") {
	Json root(json_object_new_object(), json_object_put); put(root.get(), "title", page.title);
	auto rows = json_object_new_array();
	for (const auto& row : page.rows) json_object_array_add(rows, rowJson(row));
	json_object_object_add(root.get(), arrayName, rows);
	return json_object_to_json_string_ext(root.get(), JSON_C_TO_STRING_PLAIN);
}
size_t footprint(const Row& row) {
	size_t bytes = sizeof(Row) + row.name.capacity() + row.id.capacity() + row.kind.capacity() + row.group.capacity() + row.reference.capacity() + row.extension.capacity() + row.key.capacity() + row.scope.capacity() + row.picon.capacity() + row.detail.capacity();
	for (const auto& child : row.children) bytes += footprint(child);
	return bytes;
}
size_t footprint(const Page& page) { size_t bytes = sizeof(Page); for (const auto& row : page.rows) bytes += footprint(row); return bytes; }
std::vector<json_object*> array(json_object* root) {
	std::vector<json_object*> values;
	if (root && json_object_get_type(root) == json_type_array) {
		for (size_t i = 0; i < json_object_array_length(root); ++i) {
			auto item = json_object_array_get_idx(root, i);
			if (item && json_object_get_type(item) == json_type_object) values.push_back(item);
		}
	} else if (root && json_object_get_type(root) == json_type_object) {
		json_object_object_foreach(root, key, value) { (void)key; if (json_object_get_type(value) == json_type_object) values.push_back(value); }
	} else throw std::runtime_error("Sunucu geçerli bir liste göndermedi.");
	if (values.size() > 25000) throw std::runtime_error("Kategori cihaz için çok büyük.");
	return values;
}
std::string categoryName(std::string name, const std::string& group) {
	if (group != "live") return name;
	if (name.rfind("TR", 0) == 0 || name.rfind("tr",0)==0) {
		std::string candidate=name.substr(2);bool removed=false;
		while(true) {
			while(!candidate.empty() && candidate[0]==' ')candidate.erase(0,1);
			bool matched=false;
			for(auto separator:{"➾","►",">","→",":","|","−","-"})if(candidate.rfind(separator,0)==0) { candidate.erase(0,strlen(separator));matched=removed=true;break; }
			if(!matched)break;
		}
		if(removed)name=candidate;
	}
	while (!name.empty() && name.front() == ' ') name.erase(0, 1);
	while (!name.empty() && name.back() == ' ') name.pop_back();
	const std::map<std::string, std::string> names = {{"ULUSAL", "Türk Ulusal"}, {"TÜRK ULUSAL", "Türk Ulusal"}, {"SPOR", "Spor"}, {"HABER", "Haber"}, {"BELGESEL", "Belgesel"}, {"COCUK", "Çocuk"}, {"ÇOCUK", "Çocuk"}, {"DINI", "Dini"}, {"DİNİ", "Dini"}, {"YEREL", "Yerel"}, {"MUZIK", "Müzik"}, {"MÜZİK", "Müzik"}, {"RADYO", "Radyo"}};
	auto upper=name;std::transform(upper.begin(),upper.end(),upper.begin(),[](unsigned char c) { return c<128?std::toupper(c):c; });
	auto i = names.find(upper); return i == names.end() ? name : i->second;
}
struct Transfer { std::string body; std::atomic<bool>* stop; std::atomic<unsigned>* generation; unsigned request; };
size_t receive(char* data, size_t a, size_t b, void* context) {
	auto& transfer = *static_cast<Transfer*>(context); size_t n = a * b;
	if (transfer.body.size() + n > MAX_BYTES) return 0;
	transfer.body.append(data, n); return n;
}
int progress(void* context, curl_off_t, curl_off_t, curl_off_t, curl_off_t) {
	auto& t = *static_cast<Transfer*>(context); return *t.stop || *t.generation != t.request;
}
} // namespace

std::string Model::digest(const std::string& value) {
	unsigned char hash[SHA256_DIGEST_LENGTH]; SHA256(reinterpret_cast<const unsigned char*>(value.data()), value.size(), hash);
	std::ostringstream out; for (auto c : hash) out << std::hex << std::setw(2) << std::setfill('0') << unsigned(c); return out.str();
}
std::string Model::quote(const std::string& value) {
	static const char hex[] = "0123456789ABCDEF"; std::string out;
	for (unsigned char c : value) { if (std::isalnum(c) || c == '-' || c == '.' || c == '_' || c == '~') out += c; else { out += '%'; out += hex[c >> 4]; out += hex[c & 15]; } } return out;
}
std::string Account::scope() const { return valid() ? Model::digest(url + "\n" + username) : ""; }
Account Model::normalize(Account a) {
	auto trim=[](std::string text) { auto first=text.find_first_not_of(" \t\r\n"),last=text.find_last_not_of(" \t\r\n");return first==std::string::npos?std::string():text.substr(first,last-first+1); };
	a.url=trim(a.url);a.username=trim(a.username);
	if (a.url.find("://") == std::string::npos) a.url = "http://" + a.url;
	while (!a.url.empty() && a.url.back() == '/') a.url.pop_back();
	for (auto tail : {"/player_api.php", "/get.php", "/xmltv.php"})
		if (a.url.size() >= strlen(tail) && a.url.compare(a.url.size() - strlen(tail), strlen(tail), tail) == 0) a.url.resize(a.url.size() - strlen(tail));
	auto scheme = a.url.find("://"); auto hostEnd = a.url.find('/', scheme + 3);
	std::string authority = a.url.substr(scheme + 3, hostEnd == std::string::npos ? hostEnd : hostEnd - scheme - 3);
	if ((a.url.rfind("http://", 0) && a.url.rfind("https://", 0)) || authority.empty() || authority.find('@') != std::string::npos || a.url.find_first_of("?#\r\n\t ") != std::string::npos || a.url.size() > 1024 || a.username.empty() || a.password.empty() || a.username.size() > 256 || a.password.size() > 256) throw std::runtime_error("URL, kullanıcı adı ve parola geçersiz.");
	a.output = a.output == "m3u8" ? "m3u8" : "ts"; return a;
}
Model::Model(Paths paths) : m_paths(std::move(paths)) {
	static std::once_flag init; std::call_once(init, [] { curl_global_init(CURL_GLOBAL_DEFAULT); });
	m_worker = std::thread(&Model::run, this);
	enqueue([this] { loadPrivate(); });
}
Model::~Model() { shutdown(); }
void Model::shutdown() { m_stop = true; ++m_generation; m_wake.notify_all(); if (m_worker.joinable()) m_worker.join(); }
void Model::run() {
	while (!m_stop) {
		std::function<void()> task;
		{ std::unique_lock<std::mutex> guard(m_mutex); m_wake.wait(guard, [this] { return m_stop || !m_tasks.empty(); }); if (m_stop) return; task = std::move(m_tasks.front()); m_tasks.pop_front(); }
		try { task(); } catch (...) { /* Tasks report their own sanitized errors. */ }
	}
}
void Model::enqueue(std::function<void()> task) { { std::lock_guard<std::mutex> guard(m_mutex); m_tasks.push_back(std::move(task)); } m_wake.notify_one(); }
void Model::cancel() { ++m_generation; }
void Model::loadPrivate() {
	Account account; std::vector<Row> favorites; bool corrupt = false;
	try { auto root = json(read(m_paths.account)); account = normalize({str(root.get(), "url"), str(root.get(), "username"), str(root.get(), "password"), str(root.get(), "output", "ts")}); } catch (...) {}
	try {
		if (std::filesystem::exists(m_paths.favorites)) {
			auto root = json(read(m_paths.favorites));
			for (auto value : array(field(root.get(), "entries"))) {
				Row r = rowFrom(value); if (!r.key.empty() && (r.group == "tv" || r.group == "live" || r.group == "vod" || r.group == "episode")) favorites.push_back(std::move(r));
			}
		}
	} catch (...) { corrupt = true; }
	std::lock_guard<std::mutex> guard(m_mutex); m_account = account; m_favorites = favorites; m_corruptFavorites = corrupt;
	for (const auto& row : favorites) m_favoriteKeys.insert(row.key);
}
bool Model::hasAccount() const { std::lock_guard<std::mutex> guard(m_mutex); return m_account.valid(); }
void Model::remember(const std::string& key, const std::shared_ptr<Page>& page) {
	if (footprint(*page) > 4 * 1024 * 1024) return;
	std::lock_guard<std::mutex> guard(m_mutex); m_cache[key] = page;
	m_lru.erase(std::remove(m_lru.begin(), m_lru.end(), key), m_lru.end()); m_lru.push_back(key);
	auto bytes = [&] { size_t total = 0; for (const auto& item : m_cache) total += footprint(*item.second); return total; };
	while (m_lru.size() > 12 || bytes() > 4 * 1024 * 1024) { m_cache.erase(m_lru.front()); m_lru.pop_front(); }
}
std::shared_ptr<Page> Model::cached(const std::string& key) {
	std::lock_guard<std::mutex> guard(m_mutex); auto i = m_cache.find(key); return i == m_cache.end() ? nullptr : i->second;
}
void Model::invalidate(const std::string& key) { std::lock_guard<std::mutex> guard(m_mutex);m_cache.erase(key); }
bool Model::favorite(const Row& r) const { std::lock_guard<std::mutex> guard(m_mutex); return !r.key.empty() && m_favoriteKeys.count(r.key); }
std::shared_ptr<Page> Model::favoritesPage() const {
	auto page = std::make_shared<Page>(); page->key = "favorites"; page->title = "Favorites";
	std::lock_guard<std::mutex> guard(m_mutex);
	for (const auto& row : m_favorites) if (row.group == "tv" || row.scope == m_account.scope()) page->rows.push_back(row);
	if (m_corruptFavorites) page->error = "Favori dosyası okunamadı; mevcut dosya korundu.";
	return page;
}
void Model::toggle(const Row& row, const Callback& callback) {
	enqueue([this, row, callback] {
		auto result = std::make_shared<Page>(); result->key = "favorite-change";
		result->rows.push_back(row);
		try {
			std::vector<Row> updated;
			{ std::lock_guard<std::mutex> guard(m_mutex); if (m_corruptFavorites) throw std::runtime_error("Hasarlı favori dosyası korundu."); updated = m_favorites; }
			if (!row.playable() || row.key.empty()) throw std::runtime_error("Bir kanal veya yayın seçin.");
			auto found = std::find_if(updated.begin(), updated.end(), [&](const Row& r) { return r.key == row.key; });
			if (found != updated.end()) updated.erase(found); else updated.push_back(row);
			Page file; file.rows = updated; atomic(m_paths.favorites, serialize(file, "entries"));
			{ std::lock_guard<std::mutex> guard(m_mutex); m_favorites = updated; m_favoriteKeys.clear(); for (const auto& r : updated) m_favoriteKeys.insert(r.key); m_cache.erase("favorites"); }
		} catch (const std::exception& e) { result->error = e.what(); }
		callback(result);
	});
}
void Model::saveAccount(const Account& candidate, const Callback& callback) {
	unsigned generation=++m_generation;
	enqueue([this, candidate, callback, generation] {
		if(generation!=m_generation)return;
		auto result = std::make_shared<Page>(); result->key = "account-change";
		try {
			Account a = normalize(candidate); auto reply = json(fetch("", generation, a));
			auto info = field(reply.get(), "user_info"); auto auth = str(info, "auth");
			auto status=str(info,"status","Active");std::transform(status.begin(),status.end(),status.begin(),[](unsigned char c) { return std::tolower(c); });
			if ((auth != "1" && auth != "true") || status != "active") throw std::runtime_error("IPTV girişi reddedildi veya hesap aktif değil.");
			auto formats=field(info,"allowed_output_formats");
			if(formats && json_object_get_type(formats)==json_type_array) {
				std::vector<std::string> allowed;
				for(size_t i=0;i<json_object_array_length(formats);++i) {
					auto format=json_object_array_get_idx(formats,i);
					if(format && json_object_get_type(format)==json_type_string)allowed.emplace_back(json_object_get_string(format));
				}
				if(std::find(allowed.begin(),allowed.end(),a.output)==allowed.end() && std::find(allowed.begin(),allowed.end(),"m3u8")!=allowed.end())a.output="m3u8";
			}
			Json root(json_object_new_object(), json_object_put); put(root.get(), "url", a.url); put(root.get(), "username", a.username); put(root.get(), "password", a.password); put(root.get(), "output", a.output);
			if(generation!=m_generation)return;
			atomic(m_paths.account, json_object_to_json_string_ext(root.get(), JSON_C_TO_STRING_PLAIN));
			{ std::lock_guard<std::mutex> guard(m_mutex); m_account = a; m_cache.clear(); m_lru.clear(); }
		} catch (const std::exception& e) { result->error = e.what(); }
		if(generation==m_generation)callback(result);
	});
}
void Model::request(const std::string& key, const Callback& callback, bool force) {
	unsigned generation = ++m_generation;
	enqueue([this, key, callback, force, generation] {
		if (generation != m_generation) return;
		std::shared_ptr<Page> page;
		try { page = load(key, force, generation); }
		catch (const std::exception& e) { auto old = cached(key); page = old ? std::make_shared<Page>(*old) : std::make_shared<Page>(); page->key = key; if (page->title.empty()) page->title = key == "tv" ? "TV" : "IPTV"; page->error = e.what(); page->stale = bool(old); }
		if (generation == m_generation && !m_stop) callback(page);
	});
}
std::string Model::fetch(const std::string& query, unsigned generation, const Account& a) {
	if (!a.valid()) throw std::runtime_error("IPTV hesabınızı girin.");
	std::string url = a.url + "/player_api.php?username=" + quote(a.username) + "&password=" + quote(a.password) + query;
	std::unique_ptr<CURL, decltype(&curl_easy_cleanup)> curl(curl_easy_init(), curl_easy_cleanup);
	if (!curl) throw std::runtime_error("Ağ istemcisi başlatılamadı.");
	Transfer transfer{{}, &m_stop, &m_generation, generation};
	curl_easy_setopt(curl.get(), CURLOPT_URL, url.c_str());
#if LIBCURL_VERSION_NUM >= 0x075500
	curl_easy_setopt(curl.get(), CURLOPT_PROTOCOLS_STR, "http,https");
	curl_easy_setopt(curl.get(), CURLOPT_REDIR_PROTOCOLS_STR, "http,https");
#else
	curl_easy_setopt(curl.get(), CURLOPT_PROTOCOLS, CURLPROTO_HTTP | CURLPROTO_HTTPS);
	curl_easy_setopt(curl.get(), CURLOPT_REDIR_PROTOCOLS, CURLPROTO_HTTP | CURLPROTO_HTTPS);
#endif
	curl_easy_setopt(curl.get(), CURLOPT_FOLLOWLOCATION, 0L);
	curl_easy_setopt(curl.get(), CURLOPT_CONNECTTIMEOUT, 5L); curl_easy_setopt(curl.get(), CURLOPT_TIMEOUT, 15L);
	curl_easy_setopt(curl.get(), CURLOPT_NOSIGNAL, 1L); curl_easy_setopt(curl.get(), CURLOPT_ACCEPT_ENCODING, "");
	curl_easy_setopt(curl.get(), CURLOPT_USERAGENT, "MagicBoxOS/2.0");
	curl_easy_setopt(curl.get(), CURLOPT_WRITEFUNCTION, receive); curl_easy_setopt(curl.get(), CURLOPT_WRITEDATA, &transfer);
	curl_easy_setopt(curl.get(), CURLOPT_NOPROGRESS, 0L); curl_easy_setopt(curl.get(), CURLOPT_XFERINFOFUNCTION, progress); curl_easy_setopt(curl.get(), CURLOPT_XFERINFODATA, &transfer);
	auto code = curl_easy_perform(curl.get()); long status = 0; curl_easy_getinfo(curl.get(), CURLINFO_RESPONSE_CODE, &status);
	// Never return libcurl diagnostics: they can contain the credential-bearing URL.
	if (status == 401 || status == 403) throw std::runtime_error("IPTV girişi reddedildi.");
	if (code != CURLE_OK || status != 200) throw std::runtime_error("IPTV sunucusuna bağlanılamadı. Yeşil tuşla yeniden deneyin.");
	return transfer.body;
}
std::shared_ptr<Page> Model::load(const std::string& key, bool force, unsigned generation) {
	if (key == "favorites") { auto p = favoritesPage(); remember(key, p); return p; }
	if (!force) if (auto p = cached(key)) return p;
	auto page = std::make_shared<Page>(); page->key = key;
	if (key == "tv") {
		page->title = "TV · Türksat 42°E";
		std::string path = std::filesystem::exists(m_paths.channels) ? m_paths.channels : m_paths.data + "/channels.json";
		auto root = json(read(path)); for (auto value : array(field(root.get(), "channels"))) {
			Row r = rowFrom(value); r.group = "tv"; r.kind = "stream";
			r.detail = str(value, "frequency") + " " + str(value, "polarization") + " · " + str(value, "symbol_rate"); page->rows.push_back(std::move(r));
		}
		remember(key, page); return page;
	}
	if (key == "media" || key.rfind("media:",0)==0) {
		// Directory IO/metadata belongs to the existing native worker, never the
		// GUI thread. Browsing is shallow; only an opened directory is scanned.
		page->title = "Medya";
		std::filesystem::path path = key == "media" ? m_paths.media : key.substr(6);
		if (key == "media") {
			std::ifstream settings(m_paths.settings); std::string line;
			const std::string prefix="config.EMC.movie_homepath=";
			while (std::getline(settings,line)) if(line.rfind(prefix,0)==0) { path=line.substr(prefix.size()); break; }
			std::error_code error;
			if(!std::filesystem::is_directory(path,error))path=m_paths.mediaMounts;
		}
		if (!path.is_absolute() || path.string().find('\0')!=std::string::npos)throw std::runtime_error("Medya klasörü geçersiz.");
		std::error_code error;path=std::filesystem::canonical(path,error);
		if(error || !std::filesystem::is_directory(path,error))throw std::runtime_error("Medya klasörü bulunamadı. Disk bağlantısını kontrol edin.");
		const std::set<std::string> extensions={".ac3",".dts",".flac",".m4a",".mp2",".mp3",".ogg",".wav",".wma",".aac",".ts",".trp",".avi",".divx",".f4v",".flv",".img",".ifo",".iso",".m2ts",".m4v",".mkv",".mov",".mp4",".mpeg",".mpg",".mts",".vob",".wmv",".bdmv",".asf",".stream",".webm",".m3u",".e2pls"};
		std::vector<std::pair<std::filesystem::file_time_type,Row>> files;
		for(std::filesystem::directory_iterator i(path,error),end;i!=end && !error;i.increment(error)) {
			if(generation!=m_generation || m_stop)return page;
			auto name=i->path().filename().string();if(name.empty() || name[0]=='.')continue;
			std::error_code statusError;bool directory=i->is_directory(statusError);
			if(statusError || (!directory && !i->is_regular_file(statusError)))continue;
			std::string extension=i->path().extension();std::transform(extension.begin(),extension.end(),extension.begin(),[](unsigned char c){return std::tolower(c);});
			if(!directory && !extensions.count(extension))continue;
			Row row;row.name=name;row.reference=i->path().string();row.group="media";row.kind=directory?"media-folder":"media-file";row.extension=extension;row.detail=directory?"Klasör":extension.substr(1)+" · EMC ile oynat";
			if(directory)page->rows.push_back(std::move(row));
			else {
				if(extension==".ts" || extension==".trp") {
					std::ifstream meta(row.reference+".meta");char service[4096],title[4096];
					if(meta.getline(service,sizeof(service)) && meta.getline(title,sizeof(title)) && title[0])row.name=title;
				}
				auto date=i->last_write_time(statusError);files.emplace_back(statusError?std::filesystem::file_time_type::min():date,std::move(row));
			}
			if(page->rows.size()+files.size()>=10000) { page->error="Bu klasörde ilk 10000 öğe gösteriliyor.";break; }
		}
		if(error)throw std::runtime_error("Medya klasörü okunamadı. Disk bağlantısını kontrol edin.");
		std::sort(page->rows.begin(),page->rows.end(),[](const Row& a,const Row& b){return a.name<b.name;});
		std::sort(files.begin(),files.end(),[](const auto& a,const auto& b){return a.first!=b.first?a.first>b.first:a.second.name<b.second.name;});
		for(auto& entry:files)page->rows.push_back(std::move(entry.second));
		if(path.has_parent_path() && path.parent_path()!=path) {
			Row parent;parent.name=".. Üst klasör";parent.kind="media-folder";parent.group="media";parent.reference=path.parent_path();parent.detail=path.string();page->rows.insert(page->rows.begin(),std::move(parent));
		}
		if(page->rows.empty())page->error="Bu klasörde medya dosyası yok.";
		remember(key,page);return page;
	}
	Account account; { std::lock_guard<std::mutex> guard(m_mutex); account = m_account; }
	if (!account.valid()) {
		page->title = "IPTV"; Row login; login.kind = "login"; login.name = "IPTV hesabı ekle"; page->rows.push_back(login); return page;
	}
	std::string cache = m_paths.cache + "/" + digest(account.scope() + "|" + key) + ".json.gz";
	if (!force && std::filesystem::exists(cache)) {
		try { auto root = json(readCache(cache)); page->title = str(root.get(), "title"); for (auto value : array(field(root.get(), "rows"))) page->rows.push_back(rowFrom(value)); remember(key, page); return page; } catch (...) { page->rows.clear(); }
	}
	std::string group = "live", id, action, parameter;
	if (key == "iptv") { action = "get_live_categories"; page->title = "IPTV"; }
	else if (key.rfind("categories:", 0) == 0) { group = key.substr(11); if (group != "vod" && group != "series") throw std::runtime_error("Kategori geçersiz."); action = "get_" + group + "_categories"; page->title = group == "vod" ? "Filmler" : "Diziler"; }
	else {
		auto first = key.find(':'); auto next = key.find(':', first + 1); if (first == std::string::npos || next == std::string::npos) throw std::runtime_error("Liste kimliği geçersiz.");
		group = key.substr(first + 1, next - first - 1); id = key.substr(next + 1);
		if (!digits(id)) throw std::runtime_error("Liste kimliği geçersiz.");
		if (key.rfind("series:", 0) == 0) { action = "get_series_info"; parameter = "&series_id=" + id; }
		else { if (group != "live" && group != "vod" && group != "series") throw std::runtime_error("Yayın türü geçersiz."); action = group == "series" ? "get_series" : "get_" + group + "_streams"; parameter = "&category_id=" + id; }
		page->title = "IPTV";
	}
	auto root = json(fetch("&action=" + action + parameter, generation, account));
	if (action == "get_series_info") {
		auto episodes = field(root.get(), "episodes");
		std::map<int, Row> seasons;
		auto addEpisode = [&](json_object* value, int season) {
			Row r; r.id = str(value, "id"); if (!digits(r.id)) return;
			r.name = str(value, "title", "Bölüm " + str(value, "episode_num")); r.group = "episode"; r.kind = "stream"; r.extension = extension(str(value, "container_extension"), "mp4"); r.scope = account.scope(); r.key = "iptv:" + r.scope + ":episode:" + r.id;
			auto& s = seasons[season]; s.name = "Sezon " + std::to_string(season); s.id = std::to_string(season); s.kind = "season"; s.group = "series"; s.children.push_back(std::move(r));
		};
		if (episodes && json_object_get_type(episodes) == json_type_object) {
			json_object_object_foreach(episodes, season, list) { if (digits(season)) for (auto value : array(list)) addEpisode(value, std::stoi(season)); }
		} else if (episodes) for (auto value : array(episodes)) { auto season = str(value, "season", "1"); if (digits(season)) addEpisode(value, std::stoi(season)); }
		for (auto& pair : seasons) page->rows.push_back(std::move(pair.second));
	} else for (auto value : array(root.get())) {
		Row r; r.group = group; r.scope = account.scope();
		if (action.find("_categories") != std::string::npos) {
			r.id = str(value, "category_id"); if (!digits(r.id)) continue;
			r.name = categoryName(str(value, "category_name", "Kategori"), group); r.kind = "category";
		} else {
			r.name = str(value, "name", "İsimsiz yayın"); r.id = str(value, group == "series" ? "series_id" : "stream_id"); if (!digits(r.id)) continue;
			if(group=="live") { unsigned bars=0;for(auto token:{"▃","▅","▆","█"})for(size_t pos=0;(pos=r.name.find(token,pos))!=std::string::npos;pos+=strlen(token))++bars;if(bars>=2)continue; }
			r.kind = group == "series" ? "series" : "stream"; r.extension = extension(str(value, "container_extension"), group == "live" ? account.output : "mp4"); r.key = "iptv:" + r.scope + ":" + r.group + ":" + r.id;
		}
		page->rows.push_back(std::move(r));
	}
	if (key == "iptv") {
		auto rank = [](const Row& r) { return r.name == "Türk Ulusal" ? 0 : r.name == "Spor" ? 1 : r.name == "Haber" ? 2 : 3; };
		std::stable_sort(page->rows.begin(), page->rows.end(), [&](const Row& a, const Row& b) { return rank(a) < rank(b); });
		for (auto groupName : {std::make_pair("vod", "Filmler"), std::make_pair("series", "Diziler")}) { Row r; r.name = groupName.second; r.group = r.id = groupName.first; r.kind = "group"; page->rows.push_back(r); }
	}
	if (generation != m_generation) throw std::runtime_error("İstek değişti.");
	try { saveCache(cache, serialize(*page)); } catch (...) { page->error = "Liste açıldı; önbellek kaydedilemedi."; }
	remember(key, page); return page;
}
std::string Model::service(const Row& row) const {
	if(row.kind=="media-file" && row.group=="media")return row.reference;
	if (!row.playable()) return "";
	if (row.group == "tv") return row.reference;
	Account account; { std::lock_guard<std::mutex> guard(m_mutex); account = m_account; }
	if (!account.valid() || row.scope != account.scope() || !digits(row.id)) return "";
	std::string folder = row.group == "live" ? "live" : row.group == "vod" ? "movie" : row.group == "episode" ? "series" : "";
	if (folder.empty()) return "";
	std::string url = account.url + "/" + folder + "/" + quote(account.username) + "/" + quote(account.password) + "/" + row.id + "." + (row.group == "live" ? account.output : extension(row.extension, "mp4"));
	// Enigma2's service reference escapes ':' only, not the already quoted URL.
	std::string escaped; for (char c : url) escaped += c == ':' ? "%3a" : std::string(1, c);
	return "4097:0:1:0:0:0:0:0:0:0:" + escaped + ":" + row.name;
}
} // namespace MagicBox
