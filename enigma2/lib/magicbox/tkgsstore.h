#ifndef ENIGMA_MAGICBOX_TKGSSTORE_H
#define ENIGMA_MAGICBOX_TKGSSTORE_H
#include <string>
namespace MagicBox { namespace TKGS {
std::string plan(const std::string& table, const std::string& database, const std::string& previous, const std::string& options);
std::string commit(const std::string& result, const std::string& root = "/etc/enigma2");
bool recover(const std::string& root = "/etc/enigma2");
std::string restore(const std::string& root = "/etc/enigma2");
} }
#endif
