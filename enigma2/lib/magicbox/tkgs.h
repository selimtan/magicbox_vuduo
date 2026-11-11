/* Bounded TKGS A7 wire decoder, SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef ENIGMA_MAGICBOX_TKGS_H
#define ENIGMA_MAGICBOX_TKGS_H
#include <cstdint>
#include <functional>
#include <istream>
#include <map>
#include <string>
#include <vector>

namespace MagicBox { namespace TKGS {
using Bytes = std::vector<uint8_t>;
constexpr int PID = 8181, TABLE_ID = 0xa7;
uint32_t crc(const Bytes& bytes);
class Sections {
public:
	bool add(const Bytes& section);
	bool complete() const;
	std::vector<Bytes> ordered() const;
	std::map<int,int> versions() const;
private:
	struct Group { int version = -1, last = 0; std::map<int,Bytes> parts; };
	std::map<int,Group> m_groups;
	size_t m_bytes = 0;
};
class Stream {
public:
	explicit Stream(bool transport = false): m_transport(transport) {}
	std::vector<Bytes> feed(const Bytes& input);
private:
	bool m_transport;
	Bytes m_buffer, m_pending;
	int m_counter = -1;
	void emit(std::vector<Bytes>& output);
};
std::string decode(const std::vector<Bytes>& sections);
std::string capture(const Bytes& data);
std::string capture(std::istream& input, const std::function<bool()>& cancelled = {});
} }
#endif
