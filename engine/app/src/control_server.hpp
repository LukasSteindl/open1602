// SPDX-License-Identifier: GPL-3.0-or-later
//
// The control port (--control PORT): a program on the same computer, such as an agent driven by a
// language model through o1602-ctl, plays the local slot with text commands. It listens on
// 127.0.0.1 only. Each connection carries one line, the command, and gets the answer as text
// before it is closed. The commands are carried out by the game's own thread (MapViewer::serve_control):
// this thread only moves lines in and answers out.
#pragma once

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include "o1602/core/result.hpp"

namespace o1602::app {

class ControlServer {
public:
    /// One command waiting for its answer.
    class Request {
    public:
        explicit Request(std::string line) : m_line(std::move(line)) {}
        [[nodiscard]] const std::string& line() const noexcept { return m_line; }
        /// Gives the answer; the connection closes after it. The first answer counts.
        void answer(std::string text);
        /// Waits for the answer; nothing when the server stops first.
        std::optional<std::string> wait(const std::atomic<bool>& stopping);

    private:
        std::string m_line;
        std::mutex m_mutex;
        std::condition_variable m_ready;
        std::optional<std::string> m_answer;
    };

    /// Listens on 127.0.0.1:port.
    static core::Result<std::unique_ptr<ControlServer>> start(std::uint16_t port);
    ~ControlServer();
    ControlServer(const ControlServer&) = delete;
    ControlServer& operator=(const ControlServer&) = delete;

    /// The next command that came in, if any (the game's thread, once per frame).
    std::shared_ptr<Request> next();
    [[nodiscard]] std::uint16_t port() const noexcept { return m_port; }

private:
    ControlServer() = default;
    void run();
    /// One connection: its line to the game, the answer back.
    void serve(std::intptr_t socket);

    std::uint16_t m_port = 0;
    std::intptr_t m_socket = -1;
    std::atomic<bool> m_stopping{false};
    std::mutex m_mutex;
    std::deque<std::shared_ptr<Request>> m_waiting;
    std::thread m_thread;
    /// The connections being served, each in its thread (touched by the accepting thread only).
    struct Client {
        std::thread thread;
        std::shared_ptr<std::atomic<bool>> done;
    };
    std::vector<Client> m_clients;
};

}  // namespace o1602::app
