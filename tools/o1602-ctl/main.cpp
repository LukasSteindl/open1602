// SPDX-License-Identifier: GPL-3.0-or-later
//
// o1602-ctl: gives one command to a running game started with --control PORT and prints its
// answer (engine/app/src/control_server.hpp). The arguments are the command, joined by spaces
// (an argument with spaces is put in double quotes). The port: --port N before the command, else
// the environment variable O1602_CONTROL_PORT, else 7602. "-" as the command reads commands from
// standard input, one per line, and sends them as one batch. --timeout N: seconds to wait for the
// answer (default 130). Exit code 0 for an answer, 1 for an answer that starts with "error", 2 when
// no game listens, 3 when no answer came in time.
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iostream>
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
#include <poll.h>
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
        "usage: o1602-ctl [--port N] [--timeout SECONDS] COMMAND [ARGS...]\n"
        "       o1602-ctl [--port N] [--timeout SECONDS] -\n"
        "  Gives COMMAND to the game started with: open1602 --control N (default port 7602, or\n"
        "  O1602_CONTROL_PORT). 'o1602-ctl help' lists the commands the game knows.\n"
        "  '-' reads commands from standard input, one per line (empty lines and lines starting\n"
        "  with # are skipped), and sends them as one batch; 'advance' cannot be part of it.\n"
        "  --timeout: seconds to wait for the answer (default 130). Exit code 0 answer, 1 answer\n"
        "  'error: ...', 2 no game listens, 3 no answer in time.\n",
        stderr);
    return 2;
}

/// Waits up to `ms` for the socket to have data (or to be closed by the game).
bool readable(Socket s, int ms) {
#ifdef _WIN32
    WSAPOLLFD p{};
    p.fd = s;
    p.events = POLLRDNORM;
    return WSAPoll(&p, 1, ms) > 0;
#else
    pollfd p{};
    p.fd = s;
    p.events = POLLIN;
    return ::poll(&p, 1, ms) > 0;
#endif
}

}  // namespace

int main(int argc, char** argv) {
    int first = 1;
    long port = 7602;
    long timeout = 130;
    if (const char* env = std::getenv("O1602_CONTROL_PORT"); env != nullptr && *env != '\0') {
        port = std::strtol(env, nullptr, 10);
    }
    while (first + 1 < argc) {
        const std::string_view option = argv[first];
        if (option == "--port") {
            port = std::strtol(argv[first + 1], nullptr, 10);
        } else if (option == "--timeout") {
            timeout = std::strtol(argv[first + 1], nullptr, 10);
        } else {
            break;
        }
        first += 2;
    }
    if (first >= argc || port <= 0 || port > 65535 || timeout <= 0 || timeout > 86400) {
        return usage();
    }
    std::string line;
    if (std::string_view(argv[first]) == "-" && first + 1 == argc) {
        // One batch from standard input; the game answers each command under a "### " line.
        std::string text;
        for (std::string in; std::getline(std::cin, in);) {
            if (!in.empty() && in.back() == '\r') {
                in.pop_back();
            }
            const std::size_t start = in.find_first_not_of(" \t");
            if (start == std::string::npos || in[start] == '#') {
                continue;
            }
            text += (text.empty() ? "" : " ; ") + in.substr(start);
        }
        if (text.empty()) {
            std::fputs("o1602-ctl: no command on standard input\n", stderr);
            return 2;
        }
        line = "batch " + text;
    } else {
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
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(timeout);
    for (;;) {
        const auto left =
            std::chrono::duration_cast<std::chrono::milliseconds>(deadline - std::chrono::steady_clock::now());
        if (left.count() <= 0) {
            close_socket(s);
            std::printf("error: no answer within %ld s (the game may be in a menu or busy)\n", timeout);
            return 3;
        }
        if (!readable(s, static_cast<int>(std::min<std::int64_t>(left.count(), 1000)))) {
            continue;
        }
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
