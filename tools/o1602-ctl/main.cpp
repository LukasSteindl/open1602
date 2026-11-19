// SPDX-License-Identifier: GPL-3.0-or-later
//
// o1602-ctl: gives one command to a running game started with --control PORT and prints its
// answer (engine/app/src/control_server.hpp). The arguments are the command, joined by spaces
// (an argument with spaces is put in double quotes). The port: --port N before the command, else
// the environment variable O1602_CONTROL_PORT, else 7602. Exit code 0 for an answer, 1 for an
// answer that starts with "error", 2 when no game listens.
#include <cstdio>
#include <cstdlib>
#include <string>
#include <string_view>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <fcntl.h>
#include <io.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace {

#ifdef _WIN32
using Socket = SOCKET;
constexpr Socket kNoSocket = INVALID_SOCKET;
void close_socket(Socket s) {
    closesocket(s);
}
#else
using Socket = int;
constexpr Socket kNoSocket = -1;
void close_socket(Socket s) {
    ::close(s);
}
#endif

int usage() {
    std::fputs(
        "usage: o1602-ctl [--port N] COMMAND [ARGS...]\n"
        "  Gives COMMAND to the game started with: open1602 --control N (default port 7602, or\n"
        "  O1602_CONTROL_PORT). 'o1602-ctl help' lists the commands the game knows.\n",
        stderr);
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    int first = 1;
    long port = 7602;
    if (const char* env = std::getenv("O1602_CONTROL_PORT"); env != nullptr && *env != '\0') {
        port = std::strtol(env, nullptr, 10);
    }
    if (argc > 2 && std::string_view(argv[1]) == "--port") {
        port = std::strtol(argv[2], nullptr, 10);
        first = 3;
    }
    if (first >= argc || port <= 0 || port > 65535) {
        return usage();
    }
    std::string line;
    for (int i = first; i < argc; ++i) {
        const std::string_view arg = argv[i];
        if (!line.empty()) {
            line += ' ';
        }
        if (arg.find(' ') != std::string_view::npos) {
            line += '"';
            line += arg;
            line += '"';
        } else {
            line += arg;
        }
    }
    line += '\n';

#ifdef _WIN32
    WSADATA wsa{};
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        std::fputs("o1602-ctl: no sockets\n", stderr);
        return 2;
    }
    _setmode(_fileno(stdout), _O_BINARY);  // the game's answer is UTF-8 with \n
#endif
    const Socket s = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(static_cast<unsigned short>(port));
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (s == kNoSocket || ::connect(s, reinterpret_cast<const sockaddr*>(&addr), sizeof addr) != 0) {
        std::fprintf(stderr, "o1602-ctl: no game listens on 127.0.0.1:%ld (start it with --control %ld)\n", port, port);
        return 2;
    }
    std::size_t sent = 0;
    while (sent < line.size()) {
        const auto n = ::send(s, line.data() + sent, static_cast<int>(line.size() - sent), 0);
        if (n <= 0) {
            std::fputs("o1602-ctl: the game closed the connection\n", stderr);
            close_socket(s);
            return 2;
        }
        sent += static_cast<std::size_t>(n);
    }
    std::string answer;
    char buffer[8192];
    for (;;) {
        const auto n = ::recv(s, buffer, static_cast<int>(sizeof buffer), 0);
        if (n <= 0) {
            break;
        }
        answer.append(buffer, static_cast<std::size_t>(n));
    }
    close_socket(s);
    std::fwrite(answer.data(), 1, answer.size(), stdout);
    if (answer.empty()) {
        std::fputs("o1602-ctl: no answer (did the game end?)\n", stderr);
        return 2;
    }
    return answer.rfind("error", 0) == 0 ? 1 : 0;
}
