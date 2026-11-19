// SPDX-License-Identifier: GPL-3.0-or-later
#include "control_server.hpp"

#include <chrono>
#include <utility>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace o1602::app {

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

/// Waits up to `ms` for the socket to become readable; true when it did.
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

/// The command line of a connection: up to the first line break, at most 64 KiB, within 10 s.
std::optional<std::string> read_line(Socket s) {
    std::string line;
    const auto until = std::chrono::steady_clock::now() + std::chrono::seconds(10);
    char buffer[4096];
    while (line.size() < 65536 && std::chrono::steady_clock::now() < until) {
        if (!readable(s, 200)) {
            continue;
        }
        const auto n = ::recv(s, buffer, static_cast<int>(sizeof buffer), 0);
        if (n <= 0) {
            break;
        }
        line.append(buffer, static_cast<std::size_t>(n));
        if (const auto end = line.find('\n'); end != std::string::npos) {
            line.resize(end);
            if (!line.empty() && line.back() == '\r') {
                line.pop_back();
            }
            return line;
        }
    }
    if (!line.empty()) {
        return line;  // the client closed its side after the command
    }
    return std::nullopt;
}

void write_all(Socket s, const std::string& text) {
    std::size_t sent = 0;
    while (sent < text.size()) {
        const auto n = ::send(s, text.data() + sent, static_cast<int>(text.size() - sent), 0);
        if (n <= 0) {
            return;
        }
        sent += static_cast<std::size_t>(n);
    }
}

}  // namespace

void ControlServer::Request::answer(std::string text) {
    {
        const std::lock_guard lock(m_mutex);
        if (m_answer) {
            return;
        }
        m_answer = std::move(text);
    }
    m_ready.notify_all();
}

std::optional<std::string> ControlServer::Request::wait(const std::atomic<bool>& stopping) {
    std::unique_lock lock(m_mutex);
    while (!m_answer) {
        if (stopping) {
            return std::nullopt;
        }
        m_ready.wait_for(lock, std::chrono::milliseconds(200));
    }
    return m_answer;
}

core::Result<std::unique_ptr<ControlServer>> ControlServer::start(std::uint16_t port) {
#ifdef _WIN32
    WSADATA wsa{};
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        return core::make_error(core::ErrorCode::PlatformError, "control port: no sockets (WSAStartup)");
    }
#endif
    const Socket s = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == kNoSocket) {
        return core::make_error(core::ErrorCode::PlatformError, "control port: no socket");
    }
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);  // this computer only
    if (::bind(s, reinterpret_cast<const sockaddr*>(&addr), sizeof addr) != 0 || ::listen(s, 4) != 0) {
        close_socket(s);
        return core::make_error(core::ErrorCode::PlatformError,
                                "control port: cannot listen on 127.0.0.1:" + std::to_string(port) + " (in use?)");
    }
    std::unique_ptr<ControlServer> server(new ControlServer());
    server->m_port = port;
    server->m_socket = static_cast<std::intptr_t>(s);
    server->m_thread = std::thread([raw = server.get()] { raw->run(); });
    return server;
}

ControlServer::~ControlServer() {
    m_stopping = true;
    if (m_thread.joinable()) {
        m_thread.join();
    }
    close_socket(static_cast<Socket>(m_socket));
    {
        // Whoever still waits learns that the game is gone.
        const std::lock_guard lock(m_mutex);
        for (const auto& r : m_waiting) {
            r->answer("error: the game ended\n");
        }
    }
#ifdef _WIN32
    WSACleanup();
#endif
}

std::shared_ptr<ControlServer::Request> ControlServer::next() {
    const std::lock_guard lock(m_mutex);
    if (m_waiting.empty()) {
        return nullptr;
    }
    auto r = std::move(m_waiting.front());
    m_waiting.pop_front();
    return r;
}

void ControlServer::run() {
    const auto listener = static_cast<Socket>(m_socket);
    while (!m_stopping) {
        if (!readable(listener, 200)) {
            continue;
        }
        const Socket client = ::accept(listener, nullptr, nullptr);
        if (client == kNoSocket) {
            continue;
        }
        // One command at a time: the next connection waits until this one has its answer, so
        // the commands of one agent are carried out in the order it gives them.
        if (auto line = read_line(client)) {
            auto request = std::make_shared<Request>(std::move(*line));
            {
                const std::lock_guard lock(m_mutex);
                m_waiting.push_back(request);
            }
            const auto text = request->wait(m_stopping);
            write_all(client, text ? *text : std::string("error: the game ended\n"));
        }
        close_socket(client);
    }
}

}  // namespace o1602::app
