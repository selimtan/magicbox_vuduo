/* Magic Box native home model. SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef ENIGMA_MAGICBOX_MODEL_H
#define ENIGMA_MAGICBOX_MODEL_H

#include <atomic>
#include <condition_variable>
#include <deque>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_set>
#include <vector>

namespace MagicBox {

struct Row {
	std::string name, id, kind, group, reference, extension, key, scope, picon, detail;
	std::vector<Row> children;
	bool playable() const { return kind == "stream"; }
};
struct Page {
	std::string title, key, error;
	std::vector<Row> rows;
	bool stale = false;
};
struct Account {
	std::string url, username, password, output = "ts";
	bool valid() const { return !url.empty() && !username.empty() && !password.empty(); }
	std::string scope() const;
};
struct Paths {
	std::string data = "/usr/share/enigma2/magicbox";
	std::string account = "/etc/enigma2/magicbox-iptv/account.json";
	std::string favorites = "/etc/enigma2/magicbox-favorites/favorites.json";
	std::string cache = "/tmp/magicbox-iptv-cache-native";
	std::string channels = "/etc/enigma2/magicbox-tkgs/channels.json";
	std::string media = "/media/hdd/movie";
	std::string mediaMounts = "/media";
	std::string settings = "/etc/enigma2/settings";
};

// One worker owns network, JSON parsing and durable writes. No Python/GIL here.
// Completion is delivered to Enigma2 through the widget's eFixedMessagePump.
class Model {
public:
	using Callback = std::function<void(std::shared_ptr<Page>)>;
	explicit Model(Paths paths = {});
	~Model();
	void shutdown();
	Model(const Model&) = delete;
	Model& operator=(const Model&) = delete;
	void request(const std::string& key, const Callback& callback, bool force = false);
	std::shared_ptr<Page> cached(const std::string& key);
	void invalidate(const std::string& key);
	bool favorite(const Row& row) const;
	void toggle(const Row& row, const Callback& callback);
	bool hasAccount() const;
	void saveAccount(const Account& account, const Callback& callback);
	std::string service(const Row& row) const;
	void cancel();
	static std::string digest(const std::string& value);
	static std::string quote(const std::string& value);
	static Account normalize(Account account);
private:
	Paths m_paths;
	mutable std::mutex m_mutex;
	std::condition_variable m_wake;
	std::deque<std::function<void()>> m_tasks;
	std::map<std::string, std::shared_ptr<Page>> m_cache;
	std::deque<std::string> m_lru;
	std::vector<Row> m_favorites;
	std::unordered_set<std::string> m_favoriteKeys;
	Account m_account;
	bool m_corruptFavorites = false;
	std::atomic<bool> m_stop{false};
	std::atomic<unsigned> m_generation{0};
	std::thread m_worker;
	void run();
	void enqueue(std::function<void()> task);
	std::shared_ptr<Page> load(const std::string& key, bool force, unsigned generation);
	std::string fetch(const std::string& query, unsigned generation, const Account& account);
	void remember(const std::string& key, const std::shared_ptr<Page>& page);
	void loadPrivate();
	std::shared_ptr<Page> favoritesPage() const;
};

} // namespace MagicBox
#endif
