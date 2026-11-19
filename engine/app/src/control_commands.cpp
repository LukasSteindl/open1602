// SPDX-License-Identifier: GPL-3.0-or-later
//
// The commands of the control port (--control, control_server.hpp): what an agent sees of the
// game and what it may do, as the local player, by the rules of the game. Every order goes the
// same way as one of the interface (Simulation::execute with the local player), so it costs and is
// refused as it would be for a person. 'help' lists the commands.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

#include <SDL3/SDL.h>

#include "map_viewer.hpp"
#include "panel_common.hpp"
#include "production_utilisation.hpp"
#include "o1602/assets/game_data.hpp"
#include "o1602/assets/original_names.hpp"
#include "o1602/sim/construction.hpp"
#include "o1602/sim/consumption.hpp"
#include "o1602/sim/drag_path.hpp"
#include "o1602/sim/island_map.hpp"
#include "o1602/sim/pathfinding.hpp"
#include "o1602/sim/production.hpp"
#include "o1602/sim/diplomacy.hpp"
#include "o1602/sim/goods_statistics.hpp"
#include "o1602/core/file.hpp"
#include "o1602/core/text.hpp"
#include "o1602/ui/localization.hpp"
#include "o1602/sim/mission.hpp"
#include "o1602/sim/save_game.hpp"
#include "o1602/sim/ships.hpp"
#include "o1602/sim/logistics.hpp"
#include "o1602/sim/military.hpp"

namespace o1602::app {

namespace {

namespace kind = assets::kind;
namespace prod = assets::prod;

/// Splits a command line into words; "..." keeps spaces.
std::vector<std::string> split_words(std::string_view line) {
    std::vector<std::string> out;
    std::string word;
    bool quoted = false;
    bool any = false;
    for (const char c : line) {
        if (c == '"') {
            quoted = !quoted;
            any = true;
        } else if ((c == ' ' || c == '\t') && !quoted) {
            if (any) {
                out.push_back(std::move(word));
                word.clear();
                any = false;
            }
        } else {
            word += c;
            any = true;
        }
    }
    if (any) {
        out.push_back(std::move(word));
    }
    return out;
}

bool number(const std::vector<std::string>& args, std::size_t i, std::int64_t& value) {
    if (i >= args.size() || args[i].empty()) {
        return false;
    }
    char* end = nullptr;
    const long long v = std::strtoll(args[i].c_str(), &end, 10);
    if (end == nullptr || *end != '\0') {
        return false;
    }
    value = v;
    return true;
}

double tons(std::uint32_t units) {
    return static_cast<double>(units) / 32.0;
}

std::string fmt(const char* format, ...) {
    char buffer[1024];
    va_list args;
    va_start(args, format);
    std::vsnprintf(buffer, sizeof buffer, format, args);
    va_end(args);
    return buffer;
}

/// The stable name of a building ("marketplace"), else its id as text.
std::string building_key(std::uint32_t id) {
    for (const assets::OriginalName& n : assets::original_building_names()) {
        if (id >= n.first && id < n.first + n.count) {
            return std::string(n.name);
        }
    }
    return std::to_string(id);
}

/// The stable name of a ware ("tools"), else its number.
std::string ware_key(std::uint32_t w) {
    // The crops of the fields, as the islands' fertility names them.
    static constexpr std::array<const char*, 7> kCrops{"grain", "tobacco", "spices", "sugar", "cotton", "wine",
                                                       "cocoa"};
    if (w >= assets::ware::kCornField && w <= assets::ware::kCocoaField) {
        return kCrops[w - assets::ware::kCornField];
    }
    for (const assets::OriginalName& n : assets::original_ware_names()) {
        if (w >= n.first && w < n.first + n.count) {
            return std::string(n.name);
        }
    }
    return std::to_string(w);
}

std::string class_key(std::uint32_t c) {
    for (const assets::OriginalName& n : assets::original_class_names()) {
        if (c >= n.first && c < n.first + n.count) {
            return std::string(n.name);
        }
    }
    return "class" + std::to_string(c);
}

/// A building by name ("marketplace", "anno1602:marketplace") or id.
std::optional<std::uint32_t> building_arg(const std::string& text) {
    std::int64_t id = 0;
    if (number({text}, 0, id)) {
        return id > 0 && id <= 0xFFFFFF ? std::optional<std::uint32_t>(static_cast<std::uint32_t>(id)) : std::nullopt;
    }
    return assets::original_building_id(text.find(':') == std::string::npos ? "anno1602:" + text : text);
}

std::optional<std::uint8_t> ware_arg(const std::string& text) {
    std::int64_t w = 0;
    if (number({text}, 0, w)) {
        return w >= 0 && w < 256 ? std::optional<std::uint8_t>(static_cast<std::uint8_t>(w)) : std::nullopt;
    }
    const std::string_view name = text.rfind("anno1602:", 0) == 0 ? std::string_view(text).substr(9) : text;
    if (const auto* n = assets::find_original_name(assets::original_ware_names(), name)) {
        return static_cast<std::uint8_t>(n->first);
    }
    return std::nullopt;
}

/// One character for a tile of the text map; `mine`: the tile belongs to the asking player.
char tile_char(const assets::BuildingType* b, bool mine, bool foreign) {
    if (b == nullptr) {
        return ' ';
    }
    const auto own = [&](char c) { return foreign ? static_cast<char>(std::tolower(c)) : c; };
    switch (b->kind) {
        case kind::kSea:
        case kind::kSurf:
        case kind::kSurfCorner:
            return '~';
        case kind::kRiver:
        case kind::kRiverCorner:
        case kind::kRiverMouth:
            return 'w';
        case kind::kBeach:
        case kind::kBeachMouth:
        case kind::kBeachOuter:
        case kind::kBeachInner:
        case kind::kBeachVariant:
        case kind::kBeachRuin:
            return 'b';
        case kind::kBeachHouse:  // a fisher's hut on the shore
            return own('B');
        case kind::kPier:
            return 'p';
        case kind::kRock:
            return b->prod_kind == prod::kOreMountain ? 'O' : '^';
        case kind::kSlope:
        case kind::kSlopeCorner:
        case kind::kSlopeSpring:
            return '/';
        case kind::kForest:
            return mine ? 'T' : 't';
        case kind::kGround:
            return mine ? ':' : (foreign ? ',' : '.');
        case kind::kRoad:
            return '=';
        case kind::kBridge:
            return '#';
        case kind::kSquare:
            return '+';
        case kind::kWall:
        case kind::kGate:
        case kind::kTower:
            return own('W');
        case kind::kRuin:
            return 'x';
        case kind::kHq:
            return own('K');
        case kind::kHarbour:
            return own('S');
        case kind::kMine:
            return own('E');
        case kind::kMill:
            return own('L');
        default:
            break;
    }
    switch (b->prod_kind) {
        case prod::kHouse:
            return own('H');
        case prod::kMarket:
            return own('M');
        case prod::kKontor:
            return own('K');
        case prod::kGrowing:
        case prod::kRipe:
            return own('F');
        case prod::kKapelle:
            return own('C');
        default:
            return own('B');
    }
}

/// Whether the ship moves or turns, as `ships` and `state` print it (else it is idle).
bool ship_moving(const sim::Ship& s) {
    return !s.target.empty() || s.motion.phase == sim::ShipMotion::Phase::Run ||
           s.motion.phase == sim::ShipMotion::Phase::Turn;
}

/// The player's ship with that id, or null (also for a foreign or sinking ship).
const sim::Ship* own_ship(const sim::World& world, sim::PlayerId player, std::uint32_t id) {
    for (const sim::Ship& s : world.ships()) {
        if (s.id == id && s.owner == player && !s.sinking) {
            return &s;
        }
    }
    return nullptr;
}

/// A road, bridge or square on the island tile: what a house must touch to be connected.
bool is_road_tile(const sim::IslandMap& map, const assets::BuildingTable& buildings, std::int32_t x, std::int32_t y) {
    if (x < 0 || y < 0 || !map.contains(static_cast<std::uint32_t>(x), static_cast<std::uint32_t>(y))) {
        return false;
    }
    const sim::MapCell& c = map.top(static_cast<std::uint32_t>(x), static_cast<std::uint32_t>(y));
    const assets::BuildingType* b = c.empty() ? nullptr : buildings.by_sprite(c.sprite);
    return b != nullptr && (b->kind == kind::kRoad || b->kind == kind::kBridge || b->kind == kind::kSquare);
}

}  // namespace

void MapViewer::control_pause(bool paused) {
    sim::GameSpeedOrder order;
    order.player = m_local_player;
    order.op = paused ? sim::GameSpeedOrder::Op::Pause : sim::GameSpeedOrder::Op::Resume;
    (void)control_execute(order);
}

bool MapViewer::control_hides(std::uint16_t island) const {
    const auto& islands = m_state->world.islands();
    return m_session && island < islands.size() && !islands[island].discovered_by(m_local_player);
}

sim::CommandResult MapViewer::control_execute(const sim::Command& command) {
    if (!m_session) {
        return m_state->simulation.execute(command);
    }
    if (m_control_dry_run) {
        m_control_orders.push_back(command);
        return m_state->simulation.execute(command);  // on the copy: for the answer
    }
    // Outside a dry run (pause, resume, speed): the order goes out, its effect shows later.
    m_command_sink.submit(command);
    sim::CommandResult result;
    result.accepted = true;
    return result;
}

std::string MapViewer::control_dry_run(const std::vector<std::string>& args,
                                       const std::shared_ptr<ControlServer::Request>& request) {
    // The command runs as in a game alone, on a copy of the world: what it says (built 3 of 4,
    // paid ...) is what the shared game will do with the same orders a few ticks later, unless
    // another player changes the place in between. The shared game never runs an order of its own
    // here: that would leave this computer's game different from the others' (lockstep, ADR 0011).
    std::unique_ptr<GameState> real = std::move(m_state);
    m_state = std::make_unique<GameState>(sim::World(real->world), m_buildings, m_figures, real->simulation.rules());
    m_state->simulation.set_speed(real->simulation.speed());  // what `state` in a batch reports
    m_control_dry_run = true;
    m_control_orders.clear();
    std::string answer;
    try {
        answer = control_command(args, request);
    } catch (...) {
        m_state = std::move(real);
        m_control_dry_run = false;
        m_control_orders.clear();
        throw;
    }
    m_state = std::move(real);
    m_control_dry_run = false;
    std::vector<sim::Command> orders = std::move(m_control_orders);
    m_control_orders.clear();
    if (orders.empty() || answer.empty()) {
        return answer;
    }
    for (sim::Command& c : orders) {
        m_command_sink.submit(std::move(c));
    }
    m_control_wait = ControlWait{request, std::move(answer), m_state->world.time_ms(), SDL_GetTicks()};
    return {};  // answered by serve_control() once the shared game carried the orders out
}

void MapViewer::control_look_at_world(std::int64_t wx, std::int64_t wy) {
    // The person holds the camera (Ctrl+Shift+C, camera hold on): no jump at all, not even an
    // asked-for one (camera ISLAND X Y, screenshot ISLAND X Y).
    if (!m_control_follow || m_camera_held) {
        return;
    }
    // The person watching must be able to follow: a jump far away waits until the camera has
    // stayed 1.5 s where it is; an action close by (15 tiles) it follows at once.
    const std::uint64_t now = SDL_GetTicks();
    const bool far = std::abs(wx - m_control_look_x) > 15 || std::abs(wy - m_control_look_y) > 15;
    if (far && m_control_look_ms != 0 && now - m_control_look_ms < 1500) {
        return;
    }
    if (far || m_control_look_ms == 0) {
        m_control_look_ms = now;
    }
    m_control_look_x = wx;
    m_control_look_y = wy;
    const auto w = static_cast<std::int64_t>(m_state->world.width());
    const auto h = static_cast<std::int64_t>(m_state->world.height());
    m_camera.center_on(render::TilePos{static_cast<std::uint32_t>(std::clamp<std::int64_t>(wx, 0, w - 1)),
                                       static_cast<std::uint32_t>(std::clamp<std::int64_t>(wy, 0, h - 1))});
}

void MapViewer::control_look_for(const std::vector<std::string>& args) {
    // The camera moves only for actions, never for what the agent merely reads (map, find-site,
    // sites, coverage, cities ...: it jumped to many places in a second while nothing happened).
    // Building, roads and demolishing turn it themselves once they succeed; here only the actions
    // at a Kontor or a ship.
    const std::string& cmd = args[0];
    std::int64_t a = 0;
    std::int64_t b = 0;
    std::int64_t c = 0;
    const auto n = [&](std::size_t i, std::int64_t& v) { return number(args, i, v); };
    const sim::World& world = m_state->world;
    const auto kontor = [&](std::int64_t island, std::int64_t city) {
        const sim::City* k = island >= 0 && island <= 0xFFFF && city >= 0 && city <= 0xFF
                                 ? world.city(static_cast<std::uint16_t>(island), static_cast<std::uint8_t>(city))
                                 : nullptr;
        if (k != nullptr && k->warehouse_x && k->warehouse_y) {
            control_look_at(k->island, *k->warehouse_x, *k->warehouse_y);
        }
    };
    const auto ship_at = [&](std::int64_t id) {
        for (const sim::Ship& s : world.ships()) {
            if (s.id == id && s.owner == m_local_player) {
                control_look_at_world(s.x, s.y);
            }
        }
    };
    (void)c;
    if ((cmd == "trade" || cmd == "tax") && n(1, a) && n(2, b)) {
        kontor(a, b);
    } else if ((cmd == "load" || cmd == "unload" || cmd == "ship-stop" || cmd == "route" || cmd == "found") &&
               n(1, a)) {
        ship_at(a);
    }
}

void MapViewer::control_look_at(std::uint16_t island, std::int32_t x, std::int32_t y) {
    if (island < m_state->world.islands().size()) {
        const sim::WorldIsland& isl = m_state->world.islands()[island];
        control_look_at_world(std::int64_t{isl.x} + x, std::int64_t{isl.y} + y);
    }
}

std::string MapViewer::control_message_line(MessageId message, std::string_view text,
                                            std::optional<std::pair<double, double>> tile) const {
    // The text a player reads for it: a package's own, else the MELDUNG text of Text.cod (the status bar).
    std::string shown(text.empty() ? m_messages.text(message, ui::current_language()) : text);
    if (shown.empty() && m_hud && m_hud->texts() != nullptr) {
        const MessageDefinition* def = m_messages.get(message);
        const std::vector<std::string> meldung = m_hud->texts()->section("MELDUNG");
        if (def != nullptr && def->meldung && *def->meldung < meldung.size()) {
            shown = meldung[*def->meldung];
        }
    }
    shown = shown.empty() ? "message " + std::to_string(static_cast<int>(message))
                          : (core::is_utf8(shown) ? shown : core::cp1252_to_utf8(shown));
    const sim::World& world = m_state->world;
    if (tile && tile->first >= 0 && tile->second >= 0 && tile->first < world.width() && tile->second < world.height()) {
        const auto x = static_cast<std::uint32_t>(tile->first);
        const auto y = static_cast<std::uint32_t>(tile->second);
        const sim::World::Cell& cell = world.cell(x, y);
        shown += cell.island == sim::World::kSea
                     ? fmt(" (world %u,%u)", x, y)
                     : fmt(" (island %u at %u,%u)", cell.island, cell.local_x, cell.local_y);
    }
    return shown;
}

std::string MapViewer::control_events() {
    std::string out;
    if (m_control_dropped != 0) {
        out += fmt("  (%zu older messages dropped)\n", m_control_dropped);
    }
    for (const std::string& m : m_control_messages) {
        out += "  " + m + "\n";
    }
    m_control_messages.clear();
    m_control_dropped = 0;
    return out.empty() ? out : "messages:\n" + out;
}

void MapViewer::serve_control() {
    if (!m_control) {
        return;
    }
    if (m_control_advance && (m_pending_load || in_menu())) {
        // No game runs (a load waits, the menu is open): the time would never pass.
        const auto request = std::move(m_control_advance->request);
        m_control_advance.reset();
        request->answer("error: the game is not running (menu or loading)\n");
    }
    if (m_control_wait) {
        // A multiplayer game: the orders of the last command go out with a lead of a few ticks
        // (net::SessionConfig::min_lead .. max_lead); 2.5 s of game time covers the usual lead on
        // one network. A paused game carries them out too, but its time stands: then 3 s of real time.
        const bool gone = m_pending_load || in_menu();
        const bool done = gone || m_state->world.time_ms() >= m_control_wait->from_ms + 2500 ||
                          SDL_GetTicks() >= m_control_wait->real_from_ms + 3000;
        if (!done) {
            return;  // the next commands wait, so that they see what this one did
        }
        const auto request = std::move(m_control_wait->request);
        std::string answer = std::move(m_control_wait->answer);
        m_control_wait.reset();
        request->answer(gone ? std::string("error: the game is not running (menu or loading)\n") : std::move(answer));
    }
    if (m_control_advance) {
        const ControlAdvance& adv = *m_control_advance;
        const std::uint64_t now = m_state->world.time_ms();
        const bool partial = SDL_GetTicks() >= adv.real_from_ms + 100000;
        // Why the wait ends before its time is over (empty: it goes on). A shared game waits out the
        // referee's pause too; the real-time cap ends every wait, so an agent's call does not hang.
        std::string why;
        if (now >= adv.until_ms) {
            why = "done";
        } else if (!adv.urgent.empty()) {
            why = "stopped early: " + adv.urgent;
        } else if (adv.until_ship) {
            const sim::Ship* ship = own_ship(m_state->world, m_local_player, *adv.until_ship);
            if (ship == nullptr) {
                why = fmt("ship %u is gone", *adv.until_ship);
            } else if (!ship_moving(*ship)) {
                why = fmt("ship %u is idle", *adv.until_ship);
            }
        }
        if (why.empty() && !m_session && m_state->simulation.paused()) {
            why = "the game was paused";  // a person paused it: its time stands, nothing more happens
        }
        if (!why.empty() || partial) {
            if (!m_session && adv.was_paused && !m_state->simulation.paused()) {
                control_pause(true);  // as it was; a shared game runs on, advance only waits there
            }
            const auto request = std::move(m_control_advance->request);
            const double passed = static_cast<double>(now - adv.from_ms) / 1000.0;
            const std::uint64_t planned = (adv.until_ms - adv.from_ms) / 1000;
            std::string first = fmt("advanced %.1f s of game time", passed);
            if (why.empty()) {
                first = fmt("advanced %.1f of %llu s of game time (partial: call advance again)", passed,
                            static_cast<unsigned long long>(planned));
            } else if (why != "done") {
                first += " (" + why + ")";
            }
            m_control_advance.reset();
            const std::string messages = control_events();
            request->answer(first + "\n" + control_state() + messages);
        }
        return;  // the next commands wait until the game stands again
    }
    // A few per frame: an agent waits for each answer anyway.
    for (int n = 0; n < 16; ++n) {
        const auto request = m_control->next();
        if (!request) {
            break;
        }
        std::string answer;
        try {
            answer = control_command(split_words(request->line()), request);
        } catch (const std::exception& e) {
            answer = std::string("error: ") + e.what() + "\n";
        }
        if (!answer.empty()) {
            request->answer(std::move(answer));
        }
        if (m_control_advance || m_control_wait) {
            break;
        }
    }
}

void MapViewer::control_refuse_waiting() {
    while (m_control) {
        const auto request = m_control->next();
        if (!request) {
            break;
        }
        request->answer("error: the game is not running (menu, loading or a video)\n");
    }
}

namespace {

/// Commands that only read the game (or change only this computer's view): in a multiplayer game
/// they run on the shared game directly, without a dry run. pause, resume and speed give their
/// order to the session themselves.
bool control_reads_only(const std::vector<std::string>& args) {
    static const std::set<std::string, std::less<>> kReading = {
        "help",   "state", "ships",      "cities",  "city",         "islands", "map",      "buildings",
        "goods",  "find-site", "kontor-sites", "threats", "units", "screenshot", "houses", "house-sites",
        "sites",  "alerts", "unconnected", "camera", "coverage", "production", "plan",     "say",
        "save",   "advance", "pause",     "resume",  "speed",      "autoplay", "chat",
        "events", "economy"};
    const std::string& cmd = args[0];
    return kReading.contains(cmd) || (cmd == "diplomacy" && args.size() == 1);
}

}  // namespace

std::string MapViewer::control_command(const std::vector<std::string>& args,
                                       const std::shared_ptr<ControlServer::Request>& request) {
    if (args.empty()) {
        return "error: no command (try: help)\n";
    }
    const std::string& cmd = args[0];
    if (in_menu() || m_pending_load) {
        return "error: start a game first (--new-game, --load or --scenario with --control)\n";
    }
    if (m_state->view_only || m_local_player == sim::kNoPlayer || m_state->world.player(m_local_player) == nullptr) {
        return "error: no game with an own player is running\n";
    }
    if (m_session && !m_control_dry_run && !control_reads_only(args)) {
        return control_dry_run(args, request);  // a multiplayer game (ADR 0011)
    }
    if (m_session && (cmd == "pause" || cmd == "resume" || cmd == "speed") && !m_session->may_change_speed()) {
        return "error: only the host sets the speed of this multiplayer game\n";
    }
    if ((cmd == "pause" || cmd == "resume" || cmd == "speed" || cmd == "autoplay") &&
        std::getenv("O1602_CONTROL_NO_SPEED") != nullptr) {
        // A tournament: the players' control ports leave the game's time to the referee's.
        return "error: the referee sets the speed of this game; play on\n";
    }
    if (m_session && cmd == "autoplay") {
        return "error: autoplay plays games alone only\n";
    }
    // A multiplayer game: no look at an island this player has not discovered (its land, the
    // others' buildings), as the game shows them none.
    if (m_session) {
        const bool auto_build = cmd == "build" && args.size() > 3 && args[3] == "auto";
        const std::size_t at =
            cmd == "map" ? 1 : (cmd == "kontor-sites" || cmd == "sites" || cmd == "find-site" || auto_build) ? 2 : 0;
        std::int64_t island = 0;
        if (at != 0 && number(args, at, island) && island >= 0 && island <= 0xFFFF &&
            control_hides(static_cast<std::uint16_t>(island))) {
            return "error: island not discovered yet (a ship of yours has to see it first)\n";
        }
    }
    control_look_for(args);
    if (cmd == "help") {
        return control_help();
    }
    if (cmd == "state") {
        return control_state();
    }
    if (cmd == "ships") {
        return control_ships();
    }
    if (cmd == "cities" || cmd == "city") {
        return control_cities(args);
    }
    if (cmd == "islands") {
        if (args.size() > 2 || (args.size() == 2 && args[1] != "mine")) {
            return "error: islands [mine]\n";
        }
        return control_islands(args.size() == 2);
    }
    if (cmd == "economy") {
        std::int64_t island = 0;
        std::int64_t city = 0;
        if (args.size() != 3 || !number(args, 1, island) || !number(args, 2, city) || island < 0 || city < 0 ||
            island > 0xFFFF || city > 0xFF) {
            return "error: economy ISLAND CITY\n";
        }
        return control_economy(static_cast<std::uint16_t>(island), static_cast<std::uint8_t>(city));
    }
    if (cmd == "map") {
        return control_map(args);
    }
    if (cmd == "buildings") {
        return control_buildings(args);
    }
    if (cmd == "goods") {
        return control_goods();
    }
    if (cmd == "build" && args.size() > 3 && args[3] == "auto") {
        return control_build_auto(args);
    }
    if (cmd == "build" || cmd == "build-many" || cmd == "find-site") {
        return control_build(args);
    }
    if (cmd == "found" || cmd == "kontor-sites") {
        return control_found(args);
    }
    if (cmd == "road") {
        return control_road(args);
    }
    if (cmd == "demolish") {
        return control_demolish(args);
    }
    if (cmd == "ship-move" || cmd == "ship-stop") {
        return control_ship_move(args);
    }
    if (cmd == "load" || cmd == "unload") {
        return control_cargo(args, cmd == "load");
    }
    if (cmd == "pause") {
        control_pause(true);
        return "paused\n";
    }
    if (cmd == "resume") {
        control_pause(false);
        return "running (the game goes on until 'pause')\n";
    }
    if (cmd == "speed") {
        std::int64_t s = 0;
        const auto max = static_cast<std::int64_t>(m_state->simulation.rules().max_game_speed);
        if (!number(args, 1, s) || s < 1 || s > max) {
            return fmt("error: speed 1 to %lld\n", static_cast<long long>(max));
        }
        sim::GameSpeedOrder order;
        order.player = m_local_player;
        order.op = sim::GameSpeedOrder::Op::SetSpeed;
        order.speed = static_cast<std::uint32_t>(s);
        (void)control_execute(order);
        return fmt("speed x%lld\n", static_cast<long long>(s));
    }
    if (cmd == "advance") {
        const char* usage = "error: advance SECONDS [nostop] [until ship ID] (1 to 3600 seconds of game time)\n";
        std::int64_t seconds = 0;
        if (!number(args, 1, seconds) || seconds < 1 || seconds > 3600) {
            return usage;
        }
        const std::uint64_t now = m_state->world.time_ms();
        ControlAdvance advance{request, now + static_cast<std::uint64_t>(seconds) * 1000ULL, now, SDL_GetTicks()};
        for (std::size_t i = 2; i < args.size(); ++i) {
            std::int64_t id = 0;
            if (args[i] == "nostop") {
                advance.stop_on_message = false;
            } else if (args[i] == "until" && i + 2 < args.size() && args[i + 1] == "ship" &&
                       number(args, i + 2, id) && id >= 0) {
                advance.until_ship = static_cast<std::uint32_t>(id);
                i += 2;
            } else {
                return usage;
            }
        }
        if (advance.until_ship) {
            const sim::Ship* ship = own_ship(m_state->world, m_local_player, *advance.until_ship);
            if (ship == nullptr) {
                return fmt("error: no ship %u of yours (see: ships)\n", *advance.until_ship);
            }
            if (!ship_moving(*ship)) {
                return fmt("advanced 0.0 s of game time (ship %u is idle)\n", *advance.until_ship) + control_state();
            }
        }
        advance.was_paused = m_state->simulation.paused();
        m_control_advance = std::move(advance);
        if (!m_session) {
            control_pause(false);  // a shared game runs anyway (or the host has paused it)
        }
        return {};  // answered by serve_control() when the time has passed
    }
    if (cmd == "events") {
        const std::string messages = control_events();
        return messages.empty() ? "no new events\n" : messages;
    }
    if (cmd == "route") {
        return control_route(args);
    }
    if (cmd == "off" || cmd == "on") {
        // Switch a production building off (no running cost of work, it stands idle) or back on.
        std::int64_t island = 0;
        std::int64_t x = 0;
        std::int64_t y = 0;
        if (!number(args, 1, island) || !number(args, 2, x) || !number(args, 3, y) || island < 0 ||
            static_cast<std::size_t>(island) >= m_state->world.islands().size()) {
            return "error: off|on ISLAND X Y (the building's origin, see production)\n";
        }
        sim::ProductionSwitch s;
        s.player = m_local_player;
        s.island = static_cast<std::uint16_t>(island);
        s.x = static_cast<std::uint16_t>(x);
        s.y = static_cast<std::uint16_t>(y);
        s.on = cmd == "on";
        s.op = sim::ProductionSwitch::Op::Enable;
        return control_execute(s).accepted ? (s.on ? "switched on\n" : "switched off\n")
                                                       : "error: no such production building of yours\n";
    }
    if (cmd == "batch") {
        // Several commands in one connection: "batch state ; cities 17 0 ; alerts 17". Each answer
        // under a "### command" line. advance (it waits for game time) cannot be part of a batch.
        std::string out;
        std::vector<std::string> part;
        std::size_t total = 0;
        std::size_t failed = 0;
        const auto flush = [&] {
            if (part.empty()) {
                return;
            }
            std::string line;
            for (const std::string& w : part) {
                line += (line.empty() ? "" : " ") + w;
            }
            out += "### " + line + "\n";
            const std::string answer = (part[0] == "advance" || part[0] == "batch")
                                           ? "error: " + part[0] + " cannot run inside a batch\n"
                                           : control_command(part, request);
            out += answer;
            ++total;
            failed += answer.rfind("error", 0) == 0 ? 1 : 0;
            part.clear();
        };
        for (std::size_t i = 1; i < args.size(); ++i) {
            if (args[i] == ";") {
                flush();
            } else {
                part.push_back(args[i]);
            }
        }
        flush();
        if (out.empty()) {
            return "error: batch CMD ; CMD ; ...\n";
        }
        // The first word decides success for a client (exit code): one line up front when any part failed.
        return failed == 0 ? out : fmt("error: %zu of %zu commands failed\n", failed, total) + out;
    }
    if (cmd == "shipyard") {
        // The shipyard panel: build a ship (it takes the yard's time and the city's goods).
        std::int64_t island = 0;
        std::int64_t x = 0;
        std::int64_t y = 0;
        static const std::array<std::string, 4> kTypes = {"trade1", "trade2", "war1", "war2"};
        if (!number(args, 1, island) || !number(args, 2, x) || !number(args, 3, y) || args.size() < 5 || island < 0 ||
            static_cast<std::size_t>(island) >= m_state->world.islands().size()) {
            return "error: shipyard ISLAND X Y build trade1|trade2|war1|war2 | shipyard ISLAND X Y cancel\n";
        }
        sim::ShipyardOrder order;
        order.player = m_local_player;
        order.island = static_cast<std::uint16_t>(island);
        order.x = static_cast<std::uint16_t>(x);
        order.y = static_cast<std::uint16_t>(y);
        if (args[4] == "cancel") {
            order.op = sim::ShipyardOrder::Op::Cancel;
        } else {
            const auto it = args.size() > 5 ? std::find(kTypes.begin(), kTypes.end(), args[5]) : kTypes.end();
            if (args[4] != "build" || it == kTypes.end()) {
                return "error: shipyard ISLAND X Y build trade1|trade2|war1|war2\n";
            }
            order.op = sim::ShipyardOrder::Op::Build;
            order.ship_type = static_cast<std::uint8_t>(it - kTypes.begin());
        }
        if (!control_execute(order).accepted) {
            return order.op == sim::ShipyardOrder::Op::Cancel
                       ? "error: refused (no shipyard of yours with its origin at that tile, or it builds no ship)\n"
                       : "error: refused (no shipyard of yours with its origin at that tile, it builds a ship "
                         "already, a small yard cannot build war ships, or the fleet is full)\n";
        }
        const bool build = order.op == sim::ShipyardOrder::Op::Build;
        return fmt("shipyard order given (%s)%s\n", args[4].c_str(),
                   build ? "; a new ship appears when the yard has finished it" : "");
    }
    if (cmd == "recruit") {
        // The castle panel's "recruit": a unit trains in the castle (weapons from its store, the
        // military upkeep per minute), as many times as asked while places are free.
        std::int64_t island = 0;
        std::int64_t x = 0;
        std::int64_t y = 0;
        std::int64_t n = 1;
        static const std::array<std::string, 4> kUnits = {"swordsman", "cavalry", "musketeer", "cannoneer"};
        const auto it = args.size() > 4 ? std::find(kUnits.begin(), kUnits.end(), args[4]) : kUnits.end();
        if (!number(args, 1, island) || !number(args, 2, x) || !number(args, 3, y) || it == kUnits.end() ||
            island < 0 || static_cast<std::size_t>(island) >= m_state->world.islands().size() ||
            (args.size() > 5 && (!number(args, 5, n) || n < 1 || n > 16))) {
            return "error: recruit ISLAND X Y swordsman|cavalry|musketeer|cannoneer [N]   (X Y: the castle)\n";
        }
        const sim::Player& me = m_state->world.players()[m_local_player];
        sim::CastleOrder order;
        order.player = m_local_player;
        order.island = static_cast<std::uint16_t>(island);
        order.x = static_cast<std::uint16_t>(x);
        order.y = static_cast<std::uint16_t>(y);
        order.op = sim::CastleOrder::Op::Recruit;
        order.figure = assets::figure::unit_figure(static_cast<std::size_t>(it - kUnits.begin()),
                                                   sim::four_colour_index(me.banner));
        std::int64_t done = 0;
        for (std::int64_t i = 0; i < n; ++i) {
            if (!control_execute(order).accepted) {
                break;
            }
            ++done;
        }
        return fmt("%s%lld of %lld %s recruited in the castle at %lld,%lld (no castle, no free place or the army is "
                   "full when fewer)\n",
                   done == 0 ? "error: " : "", static_cast<long long>(done), static_cast<long long>(n), args[4].c_str(),
                   static_cast<long long>(x), static_cast<long long>(y));
    }
    if (cmd == "release") {
        // The castle panel's "all out": every trained unit leaves and lines up beside the castle
        // (the units still in training stay; a full castle trains no more until they leave).
        std::int64_t island = 0;
        std::int64_t x = 0;
        std::int64_t y = 0;
        if (!number(args, 1, island) || !number(args, 2, x) || !number(args, 3, y) || island < 0 ||
            static_cast<std::size_t>(island) >= m_state->world.islands().size()) {
            return "error: release ISLAND X Y   (X Y: the castle)\n";
        }
        const auto& isl = m_state->world.islands()[static_cast<std::size_t>(island)];
        sim::CastleOrder order;
        order.player = m_local_player;
        order.island = static_cast<std::uint16_t>(island);
        order.x = static_cast<std::uint16_t>(x);
        order.y = static_cast<std::uint16_t>(y);
        order.op = sim::CastleOrder::Op::ReleaseAll;
        order.spot = sim::Target::tile_spot(static_cast<std::uint32_t>(std::int64_t{isl.x} + x + 3),
                                            static_cast<std::uint32_t>(std::int64_t{isl.y} + y + 3));
        const bool ok = control_execute(order).accepted;
        return ok ? "trained units leave the castle (see: units)\n"
                  : "error: refused: no castle of yours there, or no trained unit in it\n";
    }
    if (cmd == "explore") {
        // The ship panel's "Insel erkunden": the ship explores the crops and the ore and gold
        // deposits of the island it lies at ('islands' lists them as known deposits afterwards).
        std::int64_t id = 0;
        if (!number(args, 1, id) || id < 0) {
            return "error: explore SHIP   (the ship must lie still at the island)\n";
        }
        sim::ExploreOrder order;
        order.player = m_local_player;
        order.ship = static_cast<std::uint32_t>(id);
        const bool ok = control_execute(order).accepted;
        return ok ? "exploring the island the ship lies at (see 'islands' for the deposits found)\n"
                  : "error: refused: the ship must lie still at an island that still hides something (inside the "
                    "island's rectangle: world position and size in islands)\n";
    }
    if (cmd == "attack") {
        // The military mode's right click with a ship on a building: the ship sails there and
        // shells it (an object of another player means war with him, as in the game).
        std::int64_t id = 0;
        std::int64_t island = 0;
        std::int64_t x = 0;
        std::int64_t y = 0;
        std::int64_t other = 0;
        if (args.size() == 4 && args[2] == "ship" && number(args, 1, id) && number(args, 3, other) && id >= 0 &&
            other >= 0) {
            // attack SHIP ship OTHER: against a ship (see: threats).
            sim::ShipOrder order;
            order.player = m_local_player;
            order.ship = static_cast<std::uint32_t>(id);
            order.target = sim::Target::other_ship(static_cast<std::uint32_t>(other));
            order.attack = true;
            return control_execute(order).accepted ? "attacking the ship\n"
                                                               : "error: refused: no ship of yours, or no such ship\n";
        }
        if (!number(args, 1, id) || !number(args, 2, island) || !number(args, 3, x) || !number(args, 4, y) || id < 0 ||
            island < 0 || static_cast<std::size_t>(island) >= m_state->world.islands().size() || x < 0 || y < 0) {
            return "error: attack SHIP ISLAND X Y   (a building at island tile X Y: the ship shells it; war with "
                   "its owner)\n";
        }
        const auto& isl = m_state->world.islands()[static_cast<std::size_t>(island)];
        sim::ShipOrder order;
        order.player = m_local_player;
        order.ship = static_cast<std::uint32_t>(id);
        // Any tile of the building: the target is its origin.
        const auto at = sim::building_at(m_state->world, m_buildings, static_cast<std::uint16_t>(island),
                                         sim::TilePos{static_cast<std::int32_t>(x), static_cast<std::int32_t>(y)});
        if (!at) {
            return "error: refused: no building at that tile\n";
        }
        order.target = sim::Target::building(static_cast<std::uint16_t>(island), static_cast<std::uint32_t>(at->origin.x),
                                             static_cast<std::uint32_t>(at->origin.y));
        order.attack = true;
        const bool ok = control_execute(order).accepted;
        if (ok) {
            control_look_at_world(std::int64_t{isl.x} + x, std::int64_t{isl.y} + y);
        }
        return ok ? "attacking: the ship sails there and fires once in range\n"
                  : "error: refused: no ship of yours, or nothing to attack there\n";
    }
    if (cmd == "threats") {
        // What a player sees coming: foreign soldiers on islands with a city of yours, armed
        // foreign ships within 30 tiles of such an island (island coordinates for soldiers, world
        // tiles for ships).
        const sim::World& world = m_state->world;
        std::vector<bool> mine(world.islands().size(), false);
        for (const sim::City& c : world.cities()) {
            if (c.owner == m_local_player && c.island < mine.size()) {
                mine[c.island] = true;
            }
        }
        std::string out;
        std::size_t n = 0;
        for (const sim::Soldier& s : world.soldiers()) {
            if (s.owner == m_local_player || s.owner == sim::kNoPlayer || s.island >= mine.size() || !mine[s.island]) {
                continue;
            }
            const auto& isl = world.islands()[s.island];
            out += fmt("  soldier %u of player %u figure %u on island %u at %lld,%lld\n", s.id,
                       static_cast<unsigned>(s.owner), s.figure, s.island,
                       static_cast<long long>(s.x()) - isl.x, static_cast<long long>(s.y()) - isl.y);
            ++n;
        }
        for (const sim::Ship& sh : world.ships()) {
            if (sh.owner == m_local_player || sh.sinking || sh.cannons == 0) {
                continue;
            }
            for (std::size_t i = 0; i < mine.size(); ++i) {
                if (!mine[i]) {
                    continue;
                }
                const auto& isl = world.islands()[i];
                const long long x0 = isl.x - 30;
                const long long y0 = isl.y - 30;
                const long long x1 = isl.x + static_cast<long long>(isl.map.width()) + 30;
                const long long y1 = isl.y + static_cast<long long>(isl.map.height()) + 30;
                if (sh.x >= x0 && sh.x <= x1 && sh.y >= y0 && sh.y <= y1) {
                    out += fmt("  ship %u of player %u cannons %u health %u at world %u,%u near island %zu\n", sh.id,
                               static_cast<unsigned>(sh.owner), sh.cannons, sh.health, sh.x, sh.y, i);
                    ++n;
                    break;
                }
            }
        }
        return fmt("%zu threats\n", n) + out;
    }
    if (cmd == "units") {
        // The own land units: id, figure, island, tile (island coordinates), health.
        std::string out;
        std::size_t n = 0;
        for (const sim::Soldier& s : m_state->world.soldiers()) {
            if (s.owner != m_local_player) {
                continue;
            }
            ++n;
            long long tx = static_cast<long long>(s.x());
            long long ty = static_cast<long long>(s.y());
            if (s.island < m_state->world.islands().size()) {
                const auto& isl = m_state->world.islands()[s.island];
                tx -= isl.x;
                ty -= isl.y;
            }
            out += fmt("  unit %u figure %u island %d at %lld,%lld health %u%s\n", s.id, s.figure,
                       s.island == 0xFFFF ? -1 : static_cast<int>(s.island), tx, ty, s.health,
                       s.target.empty() ? "" : " (on the move)");
        }
        return fmt("%zu units of yours (soldiers on board ships show as the ships' cargo)\n", n) + out;
    }
    if (cmd == "units-go" || cmd == "units-attack" || cmd == "board") {
        // units-go ISLAND X Y ID..: walk to the tile; units-attack ISLAND X Y ID..: attack the
        // building or unit there (war with its owner); board SHIP ID..: onto an own ship nearby.
        const bool board = cmd == "board";
        std::int64_t island = 0;
        std::int64_t x = 0;
        std::int64_t y = 0;
        std::int64_t ship = 0;
        const std::size_t first = board ? 2 : 4;
        if ((board && (!number(args, 1, ship) || ship < 0)) ||
            (!board && (!number(args, 1, island) || !number(args, 2, x) || !number(args, 3, y) || island < 0 ||
                        static_cast<std::size_t>(island) >= m_state->world.islands().size())) ||
            args.size() <= first) {
            return "error: units-go ISLAND X Y ID... | units-attack ISLAND X Y ID... | board SHIP ID...\n";
        }
        sim::SoldierOrder order;
        order.player = m_local_player;
        for (std::size_t i = first; i < args.size(); ++i) {
            std::int64_t id = 0;
            if (!number(args, i, id) || id < 0) {
                return "error: unit ids are numbers (see: units)\n";
            }
            order.soldiers.push_back(static_cast<std::uint32_t>(id));
        }
        if (board) {
            order.target = sim::Target::other_ship(static_cast<std::uint32_t>(ship));
        } else {
            const auto& isl = m_state->world.islands()[static_cast<std::size_t>(island)];
            const auto wx = static_cast<std::uint32_t>(std::int64_t{isl.x} + x);
            const auto wy = static_cast<std::uint32_t>(std::int64_t{isl.y} + y);
            if (cmd == "units-attack") {
                const auto at = sim::building_at(m_state->world, m_buildings, static_cast<std::uint16_t>(island),
                                                 sim::TilePos{static_cast<std::int32_t>(x), static_cast<std::int32_t>(y)});
                if (!at) {
                    return "error: refused: no building at that tile\n";
                }
                order.target = sim::Target::building(static_cast<std::uint16_t>(island),
                                                     static_cast<std::uint32_t>(at->origin.x),
                                                     static_cast<std::uint32_t>(at->origin.y));
                order.attack = true;
            } else {
                order.target = sim::Target::tile_spot(wx, wy);
                order.attack_move = true;
            }
            control_look_at_world(wx, wy);
        }
        const bool ok = control_execute(order).accepted;
        return ok ? cmd + ": ordered\n"
                  : "error: " + cmd + ": refused (unknown units, not yours, or no target there)\n";
    }
    if (cmd == "units-land") {
        // Soldiers from the ship's holds onto land within 6 tiles.
        std::int64_t id = 0;
        if (!number(args, 1, id) || id < 0) {
            return "error: units-land SHIP   (the ship within 6 tiles of land)\n";
        }
        sim::UnloadOrder order;
        order.player = m_local_player;
        order.ship = static_cast<std::uint32_t>(id);
        const bool ok = control_execute(order).accepted;
        return ok ? "units landing\n" : "error: refused: no soldiers on board or no land within 6 tiles\n";
    }
    if (cmd == "arm") {
        // The ship panel's cannons: the cannons in the holds go onto the ship's free places.
        std::int64_t id = 0;
        if (!number(args, 1, id) || id < 0) {
            return "error: arm SHIP   (load cannons first: load SHIP cannons N)\n";
        }
        sim::ShipCommand order;
        order.player = m_local_player;
        order.ship = static_cast<std::uint32_t>(id);
        order.op = sim::ShipCommand::Op::MountCannon;
        order.count = sim::ShipCommand::kAllCannons;
        const bool ok = control_execute(order).accepted;
        const sim::Ship* ship = m_state->world.ship(static_cast<std::uint32_t>(id));
        return fmt("%s; ship %lld has %u cannons\n",
                   ok ? "cannons mounted" : "error: nothing mounted (no cannons in the holds or no free place)",
                   static_cast<long long>(id), ship != nullptr ? ship->cannons : 0U);
    }
    if (cmd == "diplomacy" || cmd == "tribute" || cmd == "gesture") {
        // The diplomacy panel: treaties and mood towards every other player, and its actions.
        const sim::World& world = m_state->world;
        const auto treaty = [](sim::Treaty t) {
            switch (t) {
                case sim::Treaty::None: return "none";
                case sim::Treaty::Offered: return "you offered";
                case sim::Treaty::Received: return "they offer (accept it!)";
                case sim::Treaty::Signed: return "signed";
            }
            return "?";
        };
        if (cmd == "diplomacy" && args.size() == 1) {
            std::string out = "player: name, role, peace (none = war), trade treaty, their mood towards you\n";
            for (std::size_t p = 0; p < world.players().size(); ++p) {
                const auto id = static_cast<sim::PlayerId>(p);
                const sim::Player& pl = world.players()[p];
                if (id == m_local_player || pl.status != sim::PlayerStatus::Playing) {
                    continue;
                }
                const sim::Relation& r = world.diplomacy().relation(m_local_player, id);
                const auto mood = world.diplomacy().mood(world, id, m_local_player, 0, world.time_ms());
                const char* role = pl.role == sim::PlayerRole::Computer ? "computer"
                                   : pl.role == sim::PlayerRole::Human  ? "human"
                                                                        : "neutral";
                out += fmt("  %zu: %s, %s, peace %s, trade %s, mood %d\n", p, pl.name.c_str(), role, treaty(r.peace),
                           treaty(r.trade), mood);
            }
            return out;
        }
        std::int64_t partner = 0;
        if (!number(args, 1, partner) || partner < 0 || static_cast<std::size_t>(partner) >= world.players().size()) {
            return "error: diplomacy | diplomacy PLAYER trade|peace offer|accept|cancel | tribute PLAYER GOLD | gesture "
                   "PLAYER friendly|rude\n";
        }
        sim::DiplomacyOrder order;
        order.player = m_local_player;
        order.partner = static_cast<sim::PlayerId>(partner);
        if (cmd == "tribute") {
            std::int64_t gold = 0;
            if (!number(args, 2, gold) || gold < 1 || gold > sim::DiplomacyOrder::kMaxTribute) {
                return "error: tribute PLAYER GOLD (1-10000)\n";
            }
            order.kind = sim::DiplomacyOrder::Kind::Tribute;
            order.gold = static_cast<std::uint32_t>(gold);
        } else if (cmd == "gesture") {
            order.kind = sim::DiplomacyOrder::Kind::Gesture;
            order.friendly = args.size() < 3 || args[2] != "rude";
        } else {
            if (args.size() < 4 || (args[2] != "trade" && args[2] != "peace")) {
                return "error: diplomacy PLAYER trade|peace offer|accept|cancel\n";
            }
            order.kind = args[2] == "trade" ? sim::DiplomacyOrder::Kind::Trade : sim::DiplomacyOrder::Kind::Peace;
            order.value = args[3] == "offer"    ? sim::Treaty::Offered
                          : args[3] == "accept" ? sim::Treaty::Signed
                                                : sim::Treaty::None;
        }
        const bool accepted = control_execute(order).accepted;
        const sim::Relation& r = world.diplomacy().relation(m_local_player, order.partner);
        if (!accepted) {
            if (cmd == "tribute") {
                return "error: refused: not enough gold, or that player takes no tribute\n";
            }
            if (cmd == "gesture") {
                return "error: refused: that player is neutral or makes no gestures\n";
            }
            return fmt("error: refused: %s with player %lld is '%s' now (offer needs none, accept needs 'they offer', "
                       "cancel needs 'you offered' or signed), or that player makes no treaties\n",
                       args[2].c_str(), static_cast<long long>(partner),
                       treaty(args[2] == "trade" ? r.trade : r.peace));
        }
        return fmt("done; with player %lld now: peace %s, trade %s\n", static_cast<long long>(partner), treaty(r.peace),
                   treaty(r.trade));
    }
    if (cmd == "screenshot") {
        // What the player sees, as a PNG (F12's code): optionally after turning the camera to a
        // place first. A critic looking at the town needs the picture, not only the numbers.
        std::int64_t island = 0;
        std::int64_t x = 0;
        std::int64_t y = 0;
        if (args.size() > 1) {
            if (!number(args, 1, island) || !number(args, 2, x) || !number(args, 3, y) || island < 0 ||
                static_cast<std::size_t>(island) >= m_state->world.islands().size()) {
                return "error: screenshot [ISLAND X Y]\n";
            }
            const bool follow = m_control_follow;
            m_control_follow = true;
            m_control_look_ms = 0;
            control_look_at(static_cast<std::uint16_t>(island), static_cast<std::int32_t>(x),
                            static_cast<std::int32_t>(y));
            m_control_follow = follow;
        }
        const std::filesystem::path path = next_screenshot_path();
        m_screenshot = ScreenshotRequest{path, false};
        return "screenshot " + path.string() + " (written with the next frame)\n";
    }
    if (cmd == "houses" || cmd == "house-sites") {
        std::int64_t island = 0;
        std::int64_t max = 30;
        const bool problems = cmd == "houses" && args.size() > 2 && args[2] == "problems";
        const std::size_t max_at = problems ? 3 : 2;
        if (!number(args, 1, island) || island < 0 || static_cast<std::size_t>(island) >= m_state->world.islands().size() ||
            (args.size() > max_at && (!number(args, max_at, max) || max < 1 || max > 200)) ||
            args.size() > max_at + 1) {
            return "error: " + cmd + " ISLAND" + (cmd == "house-sites" ? " [MAX]" : " [problems] [MAX]") + "\n";
        }
        // houses lists every house unless a MAX is given; house-sites lists 30 by default.
        return cmd == "houses" ? control_houses(static_cast<std::uint16_t>(island), problems,
                                                args.size() > max_at ? static_cast<std::size_t>(max) : 0)
                               : control_house_sites(static_cast<std::uint16_t>(island), static_cast<std::size_t>(max));
    }
    if (cmd == "sites") {
        return control_sites(args);
    }
    if (cmd == "alerts") {
        std::int64_t island = 0;
        if (args.size() > 1 && (!number(args, 1, island) || island < 0 ||
                                static_cast<std::size_t>(island) >= m_state->world.islands().size())) {
            return "error: alerts [ISLAND]\n";
        }
        return control_alerts(args.size() > 1 ? std::optional<std::uint16_t>(static_cast<std::uint16_t>(island))
                                              : std::nullopt);
    }
    if (cmd == "unconnected" || cmd == "fix-roads") {
        std::int64_t island = 0;
        if (!number(args, 1, island) || island < 0 || static_cast<std::size_t>(island) >= m_state->world.islands().size()) {
            return "error: unconnected ISLAND | fix-roads ISLAND\n";
        }
        return control_unconnected(static_cast<std::uint16_t>(island), cmd == "fix-roads");
    }
    if (cmd == "camera") {
        // camera follow on|off, or camera ISLAND X Y: look there now.
        if (args.size() == 3 && args[1] == "follow" && (args[2] == "on" || args[2] == "off")) {
            m_control_follow = args[2] == "on";
            return std::string("camera follows actions: ") + args[2] + "\n";
        }
        if (args.size() == 3 && args[1] == "hold" && (args[2] == "on" || args[2] == "off")) {
            set_camera_held(args[2] == "on");
            return std::string("camera held by the person: ") + args[2] + "\n";
        }
        if (args.size() == 2 && args[1] == "hold") {
            return std::string("camera held by the person: ") + (m_camera_held ? "on" : "off") + "\n";
        }
        std::int64_t island = 0;
        std::int64_t x = 0;
        std::int64_t y = 0;
        if (!number(args, 1, island) || !number(args, 2, x) || !number(args, 3, y) || island < 0 ||
            static_cast<std::size_t>(island) >= m_state->world.islands().size()) {
            return "error: camera follow on|off | camera hold [on|off] | camera ISLAND X Y\n";
        }
        const bool follow = m_control_follow;
        m_control_follow = true;
        m_control_look_ms = 0;  // asked for: no waiting
        control_look_at(static_cast<std::uint16_t>(island), static_cast<std::int32_t>(x), static_cast<std::int32_t>(y));
        m_control_follow = follow;
        return "looking there\n";
    }
    if (cmd == "coverage") {
        std::int64_t island = 0;
        std::int64_t x = 0;
        std::int64_t y = 0;
        if (!number(args, 1, island) || !number(args, 2, x) || !number(args, 3, y) || island < 0 ||
            static_cast<std::size_t>(island) >= m_state->world.islands().size()) {
            return "error: coverage ISLAND X Y\n";
        }
        return control_coverage(static_cast<std::uint16_t>(island), static_cast<std::int32_t>(x),
                                static_cast<std::int32_t>(y), 2, 2) +
               "\n";
    }
    if (cmd == "tax") {
        std::int64_t island = 0;
        std::int64_t city = 0;
        std::int64_t cls = 0;
        std::int64_t rate = 0;
        // The class by name ("settlers") or number.
        const auto named = args.size() > 3 ? assets::find_original_name(assets::original_class_names(), args[3])
                                           : nullptr;
        if (named != nullptr) {
            cls = named->first;
        }
        const bool class_ok = named != nullptr || (number(args, 3, cls) && cls >= 0 && cls <= 4);
        if (!number(args, 1, island) || !number(args, 2, city) || !class_ok || !number(args, 4, rate)) {
            return "error: tax ISLAND CITY CLASS RATE (class pioneers|settlers|citizens|merchants|aristocrats or "
                   "0-4; rate 64..192, 128 normal)\n";
        }
        const bool in_range = island >= 0 && island <= 0xFFFF && city >= 0 && city <= 0xFF;
        const sim::City* c = in_range ? m_state->world.city(static_cast<std::uint16_t>(island),
                                                            static_cast<std::uint8_t>(city))
                                      : nullptr;
        if (c == nullptr || c->owner != m_local_player) {
            return fmt("error: island %lld city %lld is not a city of yours (see: state)\n",
                       static_cast<long long>(island), static_cast<long long>(city));
        }
        const std::int64_t set = std::clamp<std::int64_t>(rate, sim::CityOrder::kMinTax, sim::CityOrder::kMaxTax);
        sim::CityOrder order;
        order.player = m_local_player;
        order.island = static_cast<std::uint16_t>(island);
        order.city = static_cast<std::uint8_t>(city);
        order.op = sim::CityOrder::Op::TaxRate;
        order.resident_class = static_cast<std::uint8_t>(cls);
        order.rate = static_cast<std::uint8_t>(set);
        if (!control_execute(order).accepted) {
            return "error: refused (this class does not exist in the game)\n";
        }
        const std::string clamped =
            set != rate ? fmt(" - %lld was outside 64..192, clamped", static_cast<long long>(rate)) : std::string();
        return fmt("tax of %s set to %lld (128 normal)%s\n", class_key(static_cast<std::uint32_t>(cls)).c_str(),
                   static_cast<long long>(set), clamped.c_str());
    }
    if (cmd == "production") {
        // Every own production building: is it working, how well, what waits in it.
        // `production [ISLAND] [idle]`: one island only, and only those that need attention.
        const sim::World& world = m_state->world;
        std::int64_t only = -1;
        const bool idle_only = args.size() > 1 && args.back() == "idle";
        if (args.size() > (idle_only ? 2U : 1U) &&
            (!number(args, 1, only) || only < 0 || static_cast<std::size_t>(only) >= world.islands().size() ||
             args.size() > (idle_only ? 3U : 2U))) {
            return "error: production [ISLAND] [idle]\n";
        }
        const bool filtered = args.size() > 1;
        std::string out = "building at x,y (island): state, utilisation, stock waiting for carriers, raw material\n";
        std::string lines;
        std::size_t total = 0;
        std::size_t listed = 0;
        for (const sim::Production& p : world.productions()) {
            if (!p.used || p.island >= world.islands().size() || (only >= 0 && p.island != only)) {
                continue;
            }
            const sim::IslandMap& map = world.islands()[p.island].map;
            if (!map.contains(p.x, p.y)) {
                continue;
            }
            const sim::MapCell& top = map.top(p.x, p.y);
            const assets::BuildingType* b = top.empty() ? nullptr : m_buildings.by_sprite(top.sprite);
            if (b == nullptr || top.owner != m_local_player) {
                continue;
            }
            ++total;
            const std::int64_t utilisation = production_utilisation(p, *b, m_figures);
            // Needs attention: off, not working, under half used, or full with nobody collecting. Buildings
            // that make no goods (markets, warehouses, public buildings) never work and are left out.
            const bool full = b->max_stock > 0 && p.stock >= b->max_stock;
            if (idle_only && (!sim::is_producer(*b) || (p.enabled && p.working() && utilisation >= 50 && !full))) {
                continue;
            }
            ++listed;
            lines += fmt("%s at %u,%u (%u): %s, %lld%%, stock %.1f t, raw %.1f t\n", building_key(b->id).c_str(), p.x,
                         p.y, p.island, !p.enabled ? "switched off" : (p.working() ? "working" : "idle"),
                         static_cast<long long>(utilisation), tons(p.stock), tons(p.raw));
        }
        return (filtered ? fmt("%zu buildings, %zu listed\n", total, listed) : out) + lines;
    }
    if (cmd == "trade") {
        // What the Kontor buys from or sells to ships that call (the free trader, other players).
        std::int64_t island = 0;
        std::int64_t city = 0;
        const auto ware = args.size() > 3 ? ware_arg(args[3]) : std::nullopt;
        const std::string mode = args.size() > 4 ? args[4] : "";
        if (!number(args, 1, island) || !number(args, 2, city) || !ware ||
            (mode != "buy" && mode != "sell" && mode != "none")) {
            return "error: trade ISLAND CITY WARE buy|sell|none [TONS] [PRICE] (buy up to TONS in stock, sell "
                   "above TONS; PRICE per ton, default the usual)\n";
        }
        sim::TradeSetting order;
        order.player = m_local_player;
        order.island = static_cast<std::uint16_t>(island);
        order.city = static_cast<std::uint8_t>(city);
        order.ware = *ware;
        order.mode = mode == "buy"    ? sim::TradeSetting::Mode::Buy
                     : mode == "sell" ? sim::TradeSetting::Mode::Sell
                                      : sim::TradeSetting::Mode::None;
        // A TONS or PRICE the order cannot take is said, not dropped; the price is then clamped to the
        // range the game allows (below).
        std::string note;
        std::int64_t tons_limit = 0;
        if (args.size() > 5) {
            if (mode == "none") {
                note = "; TONS and PRICE ignored for none";
            } else if (number(args, 5, tons_limit) && tons_limit >= 0 && tons_limit <= 1000) {
                order.amount = static_cast<std::uint32_t>(tons_limit) * 32U;
            } else {
                note = "; TONS ignored (0..1000)";
            }
        }
        std::int64_t price = 0;
        if (args.size() > 6 && mode != "none") {
            if (number(args, 6, price) && price > 0 && price < 10000) {
                order.price = static_cast<std::uint16_t>(price);
            } else {
                note += "; PRICE ignored (1..9999)";
            }
        }
        if (!control_execute(order).accepted) {
            return "error: refused (your city? a trade good? or the Kontor's buy/sell slots are all used: set "
                   "another ware to none first)\n";
        }
        const sim::City* c = m_state->world.city(order.island, order.city);
        if (c != nullptr && *ware < c->trade.size()) {
            const auto& t = c->trade[*ware];
            const unsigned in_force = t.buy ? t.buy_price : t.sell_price;
            if (order.price && *order.price != in_force) {
                const sim::TradePriceRange range = sim::trade_price_range(m_state->world, *ware);
                note += fmt("; PRICE %lld clamped to %u (the game allows %u..%u)", static_cast<long long>(price),
                            in_force, range.min, range.max);
            }
            if (!t.buy && !t.sell) {
                return fmt("%s: not traded any more (the Kontor neither buys nor sells it)%s\n",
                           ware_key(*ware).c_str(), note.c_str());
            }
            return fmt("%s: %s%s, buy price %u, sell price %u, buy up to %.0f t, sell above %.0f t%s\n",
                       ware_key(*ware).c_str(), t.buy ? "buying " : "", t.sell ? "selling" : "", t.buy_price,
                       t.sell_price, tons(t.limit), tons(t.keep), note.c_str());
        }
        return "set" + note + "\n";
    }
    if (cmd == "chat") {
        // A multiplayer game's chat (ADR 0011): what the agent writes appears in every player's
        // chat box, so the people watching read along; what the others wrote comes back here.
        if (!m_session) {
            return "error: chat is for multiplayer games (the other players read it)\n";
        }
        if (args.size() == 1) {
            if (m_control_chat.empty()) {
                return "no new chat lines\n";
            }
            std::string out;
            for (const std::string& line : m_control_chat) {
                out += line + "\n";
            }
            m_control_chat.clear();
            return out;
        }
        std::string text;
        for (std::size_t i = 1; i < args.size(); ++i) {
            text += (i > 1 ? " " : "") + args[i];
        }
        if (text.size() > 400) {
            return "error: at most 400 letters a line\n";
        }
        // The chat box cuts a line at its width: a long text goes out as several lines, broken
        // between words, so that the people watching can read all of it.
        constexpr std::size_t kWidth = 52;
        std::string rest = core::is_utf8(text) ? core::utf8_to_cp1252(text) : text;  // the game's font: Windows-1252
        while (!rest.empty()) {
            std::size_t cut = rest.size();
            if (cut > kWidth) {
                cut = rest.rfind(' ', kWidth);
                cut = cut == std::string::npos || cut == 0 ? kWidth : cut;
            }
            m_session->say(rest.substr(0, cut));
            rest.erase(0, cut);
            rest.erase(0, rest.find_first_not_of(' ') == std::string::npos ? rest.size() : rest.find_first_not_of(' '));
        }
        return "said: " + text + "\n";
    }
    if (cmd == "plan" || cmd == "say") {
        // The rest of the line, as typed; for 'plan', " | " starts a new line.
        std::string text;
        for (std::size_t i = 1; i < args.size(); ++i) {
            text += (i > 1 ? " " : "") + args[i];
        }
        const auto wrap = [](const std::string& s, std::vector<std::string>& out) {
            constexpr std::size_t kWidth = 62;  // letters of the small font in the box
            std::string rest = s;
            while (rest.size() > kWidth) {
                std::size_t cut = rest.rfind(' ', kWidth);
                cut = cut == std::string::npos || cut == 0 ? kWidth : cut;
                out.push_back(rest.substr(0, cut));
                rest = "  " + rest.substr(rest[cut] == ' ' ? cut + 1 : cut);
            }
            out.push_back(rest);
        };
        if (cmd == "plan") {
            m_agent_plan.clear();
            if (text != "clear") {
                std::size_t start = 0;
                int n = 1;
                while (start <= text.size()) {
                    const std::size_t bar = text.find('|', start);
                    std::string item = text.substr(start, bar == std::string::npos ? std::string::npos : bar - start);
                    item.erase(0, item.find_first_not_of(' '));
                    item.erase(item.find_last_not_of(' ') + 1);
                    if (!item.empty()) {
                        wrap(std::to_string(n++) + ". " + item, m_agent_plan);
                    }
                    if (bar == std::string::npos) {
                        break;
                    }
                    start = bar + 1;
                }
            }
            return "plan shown\n";
        }
        if (text == "clear") {
            m_agent_steps.clear();
            m_agent_last.clear();
            return "steps cleared\n";
        }
        if (text == "idle") {
            // The agent waits: no action to show, the one line at the top goes away (user: waiting
            // is no action to show).
            m_agent_last.clear();
            return "last action cleared\n";
        }
        const std::uint64_t t = m_state->world.time_ms() / 1000;
        m_agent_last = fmt("%llu:%02llu ", static_cast<unsigned long long>(t / 60), static_cast<unsigned long long>(t % 60)) +
                       text;
        wrap(fmt("%llu:%02llu ", static_cast<unsigned long long>(t / 60), static_cast<unsigned long long>(t % 60)) +
                 text,
             m_agent_steps);
        while (m_agent_steps.size() > 6) {
            m_agent_steps.erase(m_agent_steps.begin());
        }
        std::fprintf(stderr, "agent: %s\n", text.c_str());
        return "shown\n";
    }
    if (cmd == "save") {
        if (args.size() < 2 || args[1].find_first_of("/\\:.") != std::string::npos) {
            return "error: save NAME (a plain name; the file goes to the savegame folder)\n";
        }
        const auto path = save_folder() / (args[1] + std::string(sim::kSaveExtension));
        if (auto status = save_game(path); !status) {
            return "error: " + status.error().message + "\n";
        }
        return "saved " + core::path_to_utf8(path) + "\n";
    }
    if (cmd == "autoplay") {
        const bool on = args.size() > 1 && args[1] == "on";
        set_autoplay(on);
        return on ? "autoplay on: the computer plays your slot\n" : "autoplay off\n";
    }
    return "error: unknown command '" + cmd + "' (try: help)\n";
}

std::string MapViewer::control_help() const {
    return "Open1602 control commands (coordinates: X Y are tiles of the island, from its top left;\n"
           "ship positions are world tiles; amounts of goods in tons). A failed command answers 'error: ...':\n"
           "  state                         time, money, balance (taxes, costs, trade), your cities and ships; inhabitants\n"
           "                                count the workers of your producers too, as the game's own figure\n"
           "  islands [mine]                every island (mine: where you have a city): position, size, crops, owners\n"
           "  map ISLAND [X Y W H]          the island as text (legend below), default the whole island\n"
           "  cities|city [ISLAND CITY]     your cities; with ISLAND CITY: stock, inhabitants, needs\n"
           "  ships                         your ships: id, position, cargo, moving or idle\n"
           "  buildings [all]               the buildings you may build now (all: also locked), size, costs\n"
           "  goods                         the names of the goods\n"
           "  production [ISLAND] [idle]    your production buildings: working or idle, utilisation, stock\n"
           "                                (idle: only producers off, idle, under 50 % or full)\n"
           "  economy ISLAND CITY           per good: stock/room, need per minute, trend, minutes until empty\n"
           "  coverage ISLAND X Y           which of your markets and public buildings reach a 2x2 house at X Y\n"
           "  batch CMD ; CMD ; ...         several commands in one connection, each answer under '### CMD'\n"
           "                                (a failed part: first line 'error: N of M commands failed')\n"
           "  screenshot [ISLAND X Y]       a PNG of what the player sees (after turning the camera there)\n"
           "  diplomacy [PLAYER trade|peace offer|accept|cancel]  treaties and mood, or a treaty action\n"
           "  shipyard ISLAND X Y build trade1|trade2|war1|war2 | cancel   a ship from your shipyard at X Y\n"
           "  recruit ISLAND X Y swordsman|cavalry|musketeer|cannoneer [N]  train units in your castle at X Y\n"
           "  arm SHIP                      mount the cannons in the ship's holds (load SHIP cannons N first)\n"
           "  explore SHIP                  explore the island the ship lies at (crops, ore and gold deposits)\n"
           "  tribute PLAYER GOLD | gesture PLAYER friendly|rude  make a player friendlier\n"
           "  houses ISLAND [problems] [MAX]  every own house: road, market, public buildings in reach, what the\n"
           "                                next class lacks (problems: only houses lacking something; MAX lines)\n"
           "  house-sites ISLAND [MAX]      every free house place with a road at its side and a market in reach\n"
           "  sites NAME ISLAND [MAX]       the best places on the whole island, scored by what the catchment\n"
           "                                holds: trees (forester, hunter), meadow (sheep, cattle), water\n"
           "                                (fisher), free field land (plantations, farms), quarry (stonemason)\n"
           "  alerts [ISLAND]               everything wrong at once: question marks (with the likely cause),\n"
           "                                fires, full buildings, missing roads, houses without market or the\n"
           "                                next class's public buildings, short supply, full storage, money;\n"
           "                                60 at most, most urgent first (money, fire, plague, supply)\n"
           "  unconnected ISLAND            houses no road touches (doctor, fire brigade, carriers cannot reach)\n"
           "  fix-roads ISLAND              lay roads from those houses to the nearest road\n"
           "  road ISLAND X1 Y1 X2 Y2 stone  paved road (faster; 1 t bricks a tile), also over dirt road\n"
           "  route SHIP show|start|stop|clear\n"
           "  route SHIP stop N ISLAND CITY [load|unload WARE TONS]...  stop N (0-7) at that Kontor; checked first,\n"
           "                                an error changes nothing; then 'route SHIP start' runs it\n"
           "                                (load until TONS are on board, unload up to TONS)\n"
           "  tax ISLAND CITY CLASS RATE    tax of a class (pioneers|settlers|citizens|merchants|aristocrats or 0-4),\n"
           "                                64..192 (outside: clamped), 128 normal; higher pays more, less satisfied\n"
           "  off|on ISLAND X Y             switch the production building at X Y off (idle) or on\n"
           "  kontor-sites SHIP ISLAND      where SHIP can found a Kontor (warehouse) on ISLAND\n"
           "  found SHIP ISLAND X Y         found a city: Kontor from SHIP's cargo at X Y (rotation automatic); the\n"
           "                                answer names the city and says if SHIP lies in reach for unload SHIP all\n"
           "  find-site NAME ISLAND X Y [R] free places for a building near X Y (radius R, default 8); with sites and\n"
           "                                house-sites: '(short: wood)' = you cannot pay for that place now\n"
           "  build NAME ISLAND X Y [ROT]   one building, X Y its top left tile, ROT 0-3\n"
           "  build NAME ISLAND auto [X Y]  the best place you can pay for (as sites, house-sites; near X Y as\n"
           "                                find-site), built, with a road to the nearest road unless one touches it\n"
           "  build-many NAME ISLAND X1 Y1 X2 Y2 [ROT]  fill a rectangle (fields, houses, trees)\n"
           "  road ISLAND X1 Y1 X2 Y2       a dirt road along the shortest path\n"
           "  demolish ISLAND X Y [X2 Y2]   tear down the tile's building, or a rectangle (up to 32 x 32; it leaves\n"
           "                                houses and workshops standing unless nothing else is in it)\n"
           "  ship-move SHIP X Y | ship-move SHIP city ISLAND CITY | ship-stop SHIP   (city: sail within reach of\n"
           "                                that Kontor, yours or a foreign one you trade at)\n"
           "  load SHIP WARE TONS | unload SHIP WARE TONS|all   at a Kontor within 5 tiles (all: every good on board)\n"
           "  trade ISLAND CITY WARE buy|sell|none [TONS] [PRICE]  the Kontor buys from / sells to ships that call\n"
           "                                (the free trader): buy up to TONS, sell above TONS; the answer shows the\n"
           "                                values in force (a PRICE outside the game's range is clamped)\n"
           "  advance SECONDS [nostop] [until ship ID]  pass that much game time and keep the run state; ends\n"
           "                                early at a fire/plague/attack message (nostop: not) or when the ship\n"
           "                                is idle; after 100 s real time at most ('partial': call it again)\n"
           "  events                        the game's messages since the last advance or events\n"
           "  pause | resume | speed 1-8    the game starts paused when --control is given\n"
           "  autoplay on|off               the built-in computer plays your slot\n"
           "  save NAME                     save the game (savegame folder, NAME.o1602)\n"
           "  camera ISLAND X Y | camera follow on|off   look there; by default the camera jumps to\n"
           "                                every building, road, demolition and ship order\n"
           "  attack SHIP ISLAND X Y        the ship shells the building at X Y (war with its owner)\n"
           "  release ISLAND X Y            the castle at X Y sends every trained unit out\n"
           "  threats | attack SHIP ship ID   foreign soldiers on your islands and armed ships near them;\n"
           "                                a ship of yours attacks a ship\n"
           "  units | units-go ISLAND X Y ID... | units-attack ISLAND X Y ID...   own land units: list,\n"
           "                                walk there (fighting on the way), attack a building there\n"
           "  board SHIP ID... | units-land SHIP   units onto an own ship nearby; land them within 6 tiles\n"
           "  camera hold [on|off]          the person watching holds the camera (also Ctrl+Shift+C\n"
           "                                in the game): no jump at all until it is off again\n"
           "  chat TEXT | chat              multiplayer: write to every player (their chat box shows it),\n"
           "                                or read what the others wrote since the last 'chat'\n"
           "  plan STEP | STEP | ...        show your plan over the map for the person watching (plan clear)\n"
           "  say TEXT                      show what you do now (the last six stay; say clear)\n"
           "Map legend: ~ sea, b beach (a Kontor stands next to it), p pier, w river, . free land,\n"
           "  : your land, , foreign land, t forest (T yours), ^ rock, O ore mountain, / slope,\n"
           "  = road, # bridge, + square, x ruin; buildings uppercase yours, lowercase foreign:\n"
           "  K Kontor, M market, H house, F field, C chapel, E mine, S shipyard, L mill, W wall, B other.\n";
}

std::string MapViewer::control_state() const {
    const sim::World& world = m_state->world;
    const sim::Player& me = *world.player(m_local_player);
    const auto figures = sim::player_figures(world, m_buildings, m_figures, m_local_player);
    const std::uint64_t t = world.time_ms() / 1000;
    std::string out = fmt("time %llu:%02llu:%02llu  %s  speed x%u\n", static_cast<unsigned long long>(t / 3600),
                          static_cast<unsigned long long>(t / 60 % 60), static_cast<unsigned long long>(t % 60),
                          m_state->simulation.paused() ? "paused" : "running", m_state->simulation.speed());
    out += fmt("you: player %u \"%s\", money %d, per minute: taxes %lld, running costs %lld, military %lld, "
               "sales %lld, purchases %lld, balance %lld; inhabitants %u\n",
               static_cast<unsigned>(m_local_player), me.name.c_str(), me.money, static_cast<long long>(figures.taxes),
               static_cast<long long>(figures.running_costs), static_cast<long long>(figures.military),
               static_cast<long long>(figures.sales), static_cast<long long>(figures.purchases),
               static_cast<long long>(figures.balance), figures.inhabitants);
    // The next unlock level not reached yet.
    const auto& levels = m_buildings.infra_levels();
    for (std::size_t n = 1; n < levels.size(); ++n) {
        if (!me.unlocked(static_cast<std::uint32_t>(n)) && levels[n].min_inhabitants > 0) {
            out += fmt("next unlock: %u %s or higher in one city\n", levels[n].min_inhabitants,
                       class_key(levels[n].resident_class).c_str());
            break;
        }
    }
    for (const sim::City& c : world.cities()) {
        if (c.owner != m_local_player) {
            continue;
        }
        std::string people;
        for (std::size_t k = 0; k < c.inhabitants.size() && k < 5; ++k) {
            people += fmt("%s%s %u", k ? ", " : "", class_key(static_cast<std::uint32_t>(k)).c_str(), c.inhabitants[k]);
        }
        out += fmt("city island %u city %u \"%s\": %s\n", c.island, c.index, c.name.c_str(), people.c_str());
    }
    for (const sim::Ship& s : world.ships()) {
        if (s.owner == m_local_player && !s.sinking) {
            out += fmt("ship %u \"%s\" at %u,%u %s, cargo %.1f t\n", s.id, s.name.c_str(), s.x, s.y,
                       ship_moving(s) ? "moving" : "idle", tons(s.total_load()));
        }
    }
    if (!m_control_chat.empty()) {
        out += fmt("chat: %zu new lines from the other players (read them with: chat)\n", m_control_chat.size());
    }
    if (!m_control_messages.empty()) {
        out += fmt("events: %zu new (read them with: events)\n", m_control_messages.size() + m_control_dropped);
    }
    return out;
}

std::string MapViewer::control_ships() const {
    std::string out;
    for (const sim::Ship& s : m_state->world.ships()) {
        if (s.owner != m_local_player || s.sinking) {
            continue;
        }
        out += fmt("ship %u \"%s\" figure %u at world %u,%u %s, health %u, cannons %u\n", s.id, s.name.c_str(),
                   s.figure, s.x, s.y, ship_moving(s) ? "moving" : "idle", s.health, s.cannons);
        if (const auto at = sim::kontor_in_reach(m_state->world, m_buildings, s.x, s.y)) {
            const sim::City& c = m_state->world.cities()[*at];
            out += fmt("  lies at the Kontor of island %u city %u (%s)\n", c.island, c.index,
                       c.owner == m_local_player ? "yours" : "foreign");
        }
        std::string cargo;
        for (const sim::CargoSlot& slot : s.cargo) {
            if (slot.ware != 0 && slot.amount > 0) {
                cargo += fmt(" %s %.1f t;", ware_key(slot.ware).c_str(), tons(slot.amount));
            }
        }
        out += "  cargo:" + (cargo.empty() ? std::string(" empty") : cargo) +
               fmt(" (%zu holds)\n", s.cargo.size());
    }
    return out.empty() ? "no ships\n" : out;
}

std::string MapViewer::control_cities(const std::vector<std::string>& args) const {
    const sim::World& world = m_state->world;
    std::int64_t island = 0;
    std::int64_t index = 0;
    if (args.size() < 3) {
        std::string out;
        for (const sim::City& c : world.cities()) {
            if (c.owner != m_local_player && m_session) {
                // A multiplayer game: foreign cities only where a ship of this player has been, and
                // without the count of their people, which no panel of the game shows the others.
                if (!control_hides(c.island)) {
                    out += fmt("island %u city %u \"%s\" owner %u\n", c.island, c.index, c.name.c_str(),
                               static_cast<unsigned>(c.owner));
                }
                continue;
            }
            out += fmt("island %u city %u \"%s\" owner %u%s, inhabitants %u\n", c.island, c.index, c.name.c_str(),
                       static_cast<unsigned>(c.owner), c.owner == m_local_player ? " (you)" : "",
                       [&] {
                           std::uint32_t n = 0;
                           for (const auto v : c.inhabitants) {
                               n += v;
                           }
                           return n;
                       }());
        }
        return out.empty() ? "no cities\n" : out;
    }
    if (!number(args, 1, island) || !number(args, 2, index) || island < 0 || index < 0 || island > 0xFFFF ||
        index > 0xFF) {
        return "error: cities ISLAND CITY\n";
    }
    const sim::City* c = world.city(static_cast<std::uint16_t>(island), static_cast<std::uint8_t>(index));
    if (c == nullptr || (c->owner != m_local_player && control_hides(c->island))) {
        return "error: no such city\n";
    }
    std::string out = fmt("city \"%s\" island %u city %u owner %u, Kontor at %d,%d, room %.0f t per good\n",
                          c->name.c_str(), c->island, c->index, static_cast<unsigned>(c->owner),
                          c->warehouse_x ? static_cast<int>(*c->warehouse_x) : -1,
                          c->warehouse_y ? static_cast<int>(*c->warehouse_y) : -1, tons(c->capacity));
    if (c->owner != m_local_player) {
        // What a player sees in a foreign Kontor's trade window: the treaty, and what it sells and
        // buys at which price (a ship lying there buys and sells with load/unload).
        const bool treaty = world.diplomacy().may_trade(m_local_player, c->owner);
        out += fmt("trade treaty: %s\n", treaty ? "yes (a ship of yours at this Kontor buys with load, sells with unload)"
                                                : "no (no trade here)");
        std::string sells;
        std::string buys;
        for (std::size_t w = 0; w < c->trade.size(); ++w) {
            const sim::City::Trade& t = c->trade[w];
            const auto stock = c->stock(static_cast<std::uint8_t>(w));
            if (t.sell && stock > t.keep) {
                sells += fmt(" %s %.0f t at %u;", ware_key(static_cast<std::uint32_t>(w)).c_str(), tons(stock - t.keep),
                             t.sell_price);
            }
            if (t.buy && stock < t.limit) {
                buys += fmt(" %s up to %.0f t at %u;", ware_key(static_cast<std::uint32_t>(w)).c_str(),
                            tons(t.limit - stock), t.buy_price);
            }
        }
        return out + "their Kontor sells:" + (sells.empty() ? " nothing" : sells) + "\nbuys:" +
               (buys.empty() ? " nothing" : buys) + "\n";
    }
    out += fmt("taxes %d, food supplied %u%%\n", sim::tax_income(*c, m_buildings), c->food_ratio * 100U / 128U);
    const auto& classes = m_buildings.resident_classes();
    std::size_t highest = 0;
    for (std::size_t k = 0; k < c->inhabitants.size(); ++k) {
        highest = c->inhabitants[k] > 0 ? k : highest;
    }
    for (std::size_t k = 0; k < classes.size() && k <= highest + 1; ++k) {
        const std::uint32_t people = k < c->inhabitants.size() ? c->inhabitants[k] : 0;
        if (people == 0 && k > 0 && k <= highest) {
            continue;
        }
        if (k == highest + 1) {
            // The class the houses rise to next: what it will want.
            std::string wants;
            for (const auto& need : classes[k].needs) {
                wants += " " + ware_key(need.ware);
            }
            out += fmt("next class %s will need:%s (and its public buildings in reach)\n",
                       class_key(static_cast<std::uint32_t>(k)).c_str(), wants.c_str());
            break;
        }
        std::string needs;
        for (const auto& need : classes[k].needs) {
            const auto ratio = need.ware < c->supply.size() ? c->supply[need.ware].ratio : 0;
            needs += fmt(" %s %u%%", ware_key(need.ware).c_str(), ratio * 100U / 128U);
        }
        out += fmt("%s: %u inhabitants, satisfaction %u (128 content), tax %u, supplied:%s\n",
                   class_key(static_cast<std::uint32_t>(k)).c_str(), people,
                   k < c->satisfaction.size() ? c->satisfaction[k] : 0, k < c->tax_rate.size() ? c->tax_rate[k] : 128,
                   needs.c_str());
    }
    std::string stock;
    for (const std::uint8_t w : world.goods().trade_wares()) {
        if (c->stock(w) > 0) {
            stock += fmt(" %s %.1f;", ware_key(w).c_str(), tons(c->stock(w)));
        }
    }
    out += "stock:" + (stock.empty() ? std::string(" nothing") : stock) + "\n";
    std::string trades;
    for (std::size_t w = 0; w < c->trade.size(); ++w) {
        const auto& t = c->trade[w];
        if (t.buy) {
            trades += fmt(" buys %s up to %.0f t at %u;", ware_key(static_cast<std::uint32_t>(w)).c_str(), tons(t.limit),
                          t.buy_price);
        }
        if (t.sell) {
            trades += fmt(" sells %s above %.0f t at %u;", ware_key(static_cast<std::uint32_t>(w)).c_str(),
                          tons(t.keep), t.sell_price);
        }
    }
    if (!trades.empty()) {
        out += "Kontor trade:" + trades + "\n";
    }
    // The houses of the city by class, and how many lack a market or services.
    std::array<std::uint32_t, 6> houses{};
    std::uint32_t no_market = 0;
    std::uint32_t lacking = 0;
    for (const sim::House& h : world.houses()) {
        if (h.island == c->island && h.city == c->index) {
            ++houses[std::min<std::size_t>(h.resident_class, houses.size() - 1)];
            no_market += h.market ? 0 : 1;
            lacking += h.services_complete ? 0 : 1;
        }
    }
    out += fmt("houses by class: %u/%u/%u/%u/%u; without market %u; lacking public buildings %u\n", houses[0],
               houses[1], houses[2], houses[3], houses[4], no_market, lacking);
    return out;
}

std::string MapViewer::control_islands(bool mine) const {
    const sim::World& world = m_state->world;
    std::string out = fmt("world %ux%u tiles, %zu islands\n", world.width(), world.height(), world.islands().size());
    for (std::size_t i = 0; i < world.islands().size(); ++i) {
        const sim::WorldIsland& isl = world.islands()[i];
        if (mine && !std::any_of(world.cities().begin(), world.cities().end(), [&](const sim::City& c) {
                return c.island == i && c.owner == m_local_player;
            })) {
            continue;
        }
        if (control_hides(static_cast<std::uint16_t>(i))) {
            // A multiplayer game: what a player sees of an island no ship of theirs has seen yet.
            out += fmt("island %zu: world %u,%u size %ux%u, %s, not discovered, crops: unknown; cities of: unknown\n",
                       i, isl.x, isl.y, isl.map.width(), isl.map.height(),
                       isl.header.climate == 0 ? "north" : "south");
            continue;
        }
        // What grows where is learnt by exploring the island with a ship, or by settling on it
        // (fertility_view.cpp); a multiplayer game tells no more than that.
        const bool settled = std::any_of(world.cities().begin(), world.cities().end(), [&](const sim::City& c) {
            return c.island == i && c.owner == m_local_player;
        });
        const bool crops_known = !m_session || isl.explored_by(m_local_player) || settled;
        std::string crops;
        for (std::uint8_t w = assets::ware::kCornField; w <= assets::ware::kCocoaField; ++w) {
            const auto f = sim::island_fertility(world, isl, w);
            if (f > 0) {
                crops += fmt(" %s%s", ware_key(w).c_str(), f < 128 ? "(half)" : "");
            }
        }
        std::map<unsigned, unsigned> owners;
        for (const sim::City& c : world.cities()) {
            if (c.island == i) {
                ++owners[static_cast<unsigned>(c.owner)];
            }
        }
        std::string who;
        for (const auto& [o, n] : owners) {
            who += fmt(" %u%s", o, o == m_local_player ? "(you)" : "");
        }
        std::string ore;
        for (const auto& d : isl.header.deposits) {
            if (sim::deposit_known(d, m_local_player)) {
                ore += fmt(" %s at %u,%u (%s)", d.ware == assets::ware::kGold ? "gold" : "ore", d.x, d.y,
                           d.kind == 0 ? "big" : "small");
            }
        }
        out += fmt("island %zu: world %u,%u size %ux%u, %s, %s, crops:%s; cities of:%s%s%s\n", i, isl.x, isl.y,
                   isl.map.width(), isl.map.height(), isl.header.climate == 0 ? "north" : "south",
                   isl.discovered_by(m_local_player) ? "discovered" : "not discovered",
                   !crops_known ? " unknown (explore SHIP)" : crops.empty() ? " none" : crops.c_str(),
                   who.empty() ? " nobody" : who.c_str(),
                   ore.empty() ? "" : "; known deposits:", ore.c_str());
    }
    return out;
}

std::string MapViewer::control_map(const std::vector<std::string>& args) const {
    const sim::World& world = m_state->world;
    std::int64_t island = 0;
    if (!number(args, 1, island) || island < 0 || static_cast<std::size_t>(island) >= world.islands().size()) {
        return "error: map ISLAND [X Y W H]\n";
    }
    const sim::IslandMap& map = world.islands()[static_cast<std::size_t>(island)].map;
    std::int64_t x0 = 0;
    std::int64_t y0 = 0;
    std::int64_t w = map.width();
    std::int64_t h = map.height();
    if (args.size() >= 6 && !(number(args, 2, x0) && number(args, 3, y0) && number(args, 4, w) && number(args, 5, h))) {
        return "error: map ISLAND X Y W H\n";
    }
    x0 = std::clamp<std::int64_t>(x0, 0, map.width() - 1);
    y0 = std::clamp<std::int64_t>(y0, 0, map.height() - 1);
    w = std::clamp<std::int64_t>(w, 1, std::min<std::int64_t>(160, map.width() - x0));
    h = std::clamp<std::int64_t>(h, 1, std::min<std::int64_t>(160, map.height() - y0));
    std::string out = fmt("island %lld, tiles x %lld..%lld, y %lld..%lld (see 'help' for the legend)\n",
                          static_cast<long long>(island), static_cast<long long>(x0), static_cast<long long>(x0 + w - 1),
                          static_cast<long long>(y0), static_cast<long long>(y0 + h - 1));
    // Column numbers: tens, then ones.
    std::string tens = "     ";
    std::string ones = "     ";
    for (std::int64_t x = x0; x < x0 + w; ++x) {
        tens += x % 10 == 0 ? static_cast<char>('0' + (x / 10) % 10) : ' ';
        ones += static_cast<char>('0' + x % 10);
    }
    out += tens + "\n" + ones + "\n";
    for (std::int64_t y = y0; y < y0 + h; ++y) {
        out += fmt("%4lld ", static_cast<long long>(y));
        for (std::int64_t x = x0; x < x0 + w; ++x) {
            const auto ux = static_cast<std::uint32_t>(x);
            const auto uy = static_cast<std::uint32_t>(y);
            const sim::MapCell& top = map.top(ux, uy);
            const sim::MapCell& cell = top.empty() ? map.ground(ux, uy) : top;
            const assets::BuildingType* b = cell.empty() ? nullptr : m_buildings.by_sprite(cell.sprite);
            const bool mine = top.owner == m_local_player;
            const bool foreign = top.owner != sim::kNoPlayer && !mine;
            out += tile_char(b, mine, foreign);
        }
        out += '\n';
    }
    return out;
}

std::string MapViewer::control_buildings(const std::vector<std::string>& args) const {
    const sim::Player& me = *m_state->world.player(m_local_player);
    const bool all = args.size() > 1 && args[1] == "all";
    std::string out = "name: id, size WxH, costs gold/tools t/wood t/bricks t, running cost per minute\n";
    for (const assets::OriginalName& n : assets::original_building_names()) {
        const assets::BuildingType* b = m_buildings.by_id(n.first);
        const auto& cost = b != nullptr ? b->build_cost : assets::BuildingType::BuildCost{};
        if (b == nullptr || (cost.money == 0 && cost.tools == 0 && cost.wood == 0 && cost.bricks == 0)) {
            continue;  // nothing a player builds (natives', pirates', landscape)
        }
        const bool available = sim::building_available(me, *b);
        if (!available && !all) {
            continue;
        }
        out += fmt("%s: %u, %ux%u, %d/%g/%g/%g, %u%s\n", std::string(n.name).c_str(), b->id, b->size_x, b->size_y,
                   cost.money, tons(cost.tools), tons(cost.wood), tons(cost.bricks), b->running_cost,
                   available ? "" : " (locked)");
    }
    return out;
}

std::string MapViewer::control_goods() const {
    std::string out;
    for (const std::uint8_t w : m_state->world.goods().trade_wares()) {
        out += fmt("%u %s\n", w, ware_key(w).c_str());
    }
    return out;
}

namespace {

/// What a place the player cannot pay for right now lacks, as a mark for a list of places ("" when it is payable).
std::string short_mark(sim::BuildRefusal refusal) {
    switch (refusal) {
        case sim::BuildRefusal::Money: return " (short: gold)";
        case sim::BuildRefusal::Tools: return " (short: tools)";
        case sim::BuildRefusal::Wood: return " (short: wood)";
        case sim::BuildRefusal::Bricks: return " (short: bricks)";
        case sim::BuildRefusal::Cannons: return " (short: cannons)";
        default: return "";
    }
}

std::string plan_text(const sim::BuildPlan& plan) {
    // Per reason: how many items and the first few tiles (island tiles), so that the agent sees where.
    struct Refused {
        std::size_t count = 0;
        std::string tiles;
    };
    constexpr std::size_t kExamples = 6;
    std::map<std::string, Refused> refused;
    for (const sim::PlannedBuild& item : plan.items) {
        if (!item.ok()) {
            Refused& r = refused[sim::refusal_name(item.refusal)];
            if (r.count++ < kExamples) {
                r.tiles += fmt("%s%d,%d", r.tiles.empty() ? "" : " ", item.x, item.y);
            }
        }
    }
    std::string out = fmt("built %zu of %zu", plan.placed, plan.items.size());
    if (!refused.empty()) {
        out += ", refused:";
        for (const auto& [why, r] : refused) {
            out += fmt(" %s x%zu (%s%s)", why.c_str(), r.count, r.tiles.c_str(), r.count > kExamples ? " ..." : "");
        }
    }
    out += fmt("; paid gold %d tools %g t wood %g t bricks %g t\n", plan.bill.money, tons(plan.bill.tools),
               tons(plan.bill.wood), tons(plan.bill.bricks));
    return out;
}

}  // namespace

std::string MapViewer::control_build(const std::vector<std::string>& args, std::vector<ControlSite>* found) {
    const std::string& cmd = args[0];
    const sim::World& world = m_state->world;
    std::int64_t island = 0;
    std::int64_t x = 0;
    std::int64_t y = 0;
    const auto id = args.size() > 1 ? building_arg(args[1]) : std::nullopt;
    if (!id || m_buildings.by_id(*id) == nullptr) {
        return "error: no such building (see: buildings)\n";
    }
    if (!number(args, 2, island) || !number(args, 3, x) || !number(args, 4, y) || island < 0 ||
        static_cast<std::size_t>(island) >= world.islands().size()) {
        return "error: " + cmd + " NAME ISLAND X Y ...\n";
    }
    sim::BuildOrder order;
    order.player = m_local_player;
    order.island = static_cast<std::uint16_t>(island);
    const assets::BuildingType& type = *m_buildings.by_id(*id);
    if (cmd == "find-site") {
        std::int64_t radius = 8;
        if (args.size() > 5 && (!number(args, 5, radius) || radius < 1 || radius > 30)) {
            return "error: radius 1 to 30\n";
        }
        struct Site {
            std::int64_t x, y;
            int rotation;
            std::int64_t d2;
            sim::BuildRefusal refusal;
        };
        std::vector<Site> sites;
        const int rotations = type.rotate > 0 ? 4 : 1;
        for (std::int64_t sy = y - radius; sy <= y + radius; ++sy) {
            for (std::int64_t sx = x - radius; sx <= x + radius; ++sx) {
                for (int r = 0; r < rotations; ++r) {
                    order.items = {sim::BuildItem{*id, static_cast<std::int32_t>(sx), static_cast<std::int32_t>(sy),
                                                  static_cast<std::uint8_t>(r), 0}};
                    const sim::BuildPlan plan = sim::plan_build(world, m_buildings, order);
                    if (!plan.items.empty() && (plan.items.front().ok() || sim::short_of_means(plan.items.front().refusal))) {
                        sites.push_back(Site{sx, sy, r, (sx - x) * (sx - x) + (sy - y) * (sy - y),
                                             plan.items.front().refusal});
                        break;  // one rotation per place is enough
                    }
                }
            }
        }
        // Whether a road (or a market or Kontor) touches the footprint: carts and carriers need one.
        const sim::IslandMap& map = world.islands()[static_cast<std::size_t>(island)].map;
        const auto road_next = [&](const Site& s) {
            std::uint32_t w = type.size_x;
            std::uint32_t h = type.size_y;
            sim::rotated_size(type, static_cast<std::uint8_t>(s.rotation), w, h);
            for (std::int64_t ty = s.y - 1; ty <= s.y + static_cast<std::int64_t>(h); ++ty) {
                for (std::int64_t tx = s.x - 1; tx <= s.x + static_cast<std::int64_t>(w); ++tx) {
                    const bool inside = tx >= s.x && tx < s.x + static_cast<std::int64_t>(w) && ty >= s.y &&
                                        ty < s.y + static_cast<std::int64_t>(h);
                    const bool corner = (tx == s.x - 1 || tx == s.x + static_cast<std::int64_t>(w)) &&
                                        (ty == s.y - 1 || ty == s.y + static_cast<std::int64_t>(h));
                    if (inside || corner || tx < 0 || ty < 0 ||
                        !map.contains(static_cast<std::uint32_t>(tx), static_cast<std::uint32_t>(ty))) {
                        continue;
                    }
                    const sim::MapCell& c = map.top(static_cast<std::uint32_t>(tx), static_cast<std::uint32_t>(ty));
                    const assets::BuildingType* b = c.empty() ? nullptr : m_buildings.by_sprite(c.sprite);
                    if (b != nullptr && (b->kind == kind::kRoad || b->kind == kind::kBridge ||
                                         b->kind == kind::kSquare || b->prod_kind == prod::kMarket ||
                                         b->prod_kind == prod::kKontor)) {
                        return true;
                    }
                }
            }
            return false;
        };
        const bool house = type.prod_kind == prod::kHouse;
        // Places with a road next to them first, then by distance.
        std::vector<std::pair<bool, Site>> ranked;
        for (const Site& s : sites) {
            ranked.emplace_back(road_next(s), s);
        }
        std::stable_sort(ranked.begin(), ranked.end(), [&](const auto& a, const auto& b) {
            if (!house && a.first != b.first) {
                return a.first;  // production needs the road: those places first
            }
            return a.second.d2 < b.second.d2;
        });
        std::string out = fmt("%s (%ux%u) fits at %zu places near %lld,%lld; the best (x y rotation, road next to "
                              "it%s):\n",
                              building_key(*id).c_str(), type.size_x, type.size_y, sites.size(),
                              static_cast<long long>(x), static_cast<long long>(y),
                              house ? ", what reaches it" : "");
        if (found != nullptr) {
            // For build ... auto: every place, the nearest first (it lays the road itself).
            std::stable_sort(sites.begin(), sites.end(), [](const Site& a, const Site& b) { return a.d2 < b.d2; });
            for (const Site& s : sites) {
                found->push_back(ControlSite{static_cast<std::int32_t>(s.x), static_cast<std::int32_t>(s.y),
                                             static_cast<std::uint8_t>(s.rotation), s.refusal});
            }
        }
        for (std::size_t i = 0; i < ranked.size() && i < 12; ++i) {
            const Site& s = ranked[i].second;
            out += fmt("  %lld %lld %d %s", static_cast<long long>(s.x), static_cast<long long>(s.y), s.rotation,
                       ranked[i].first ? "road" : "no-road");
            if (house) {
                out += " " + control_coverage(static_cast<std::uint16_t>(island), static_cast<std::int32_t>(s.x),
                                              static_cast<std::int32_t>(s.y), 2, 2);
            }
            out += short_mark(s.refusal) + "\n";
        }
        return out;
    }
    std::int64_t rotation = 0;
    if (cmd == "build-many") {
        std::int64_t x2 = 0;
        std::int64_t y2 = 0;
        if (!number(args, 5, x2) || !number(args, 6, y2)) {
            return "error: build-many NAME ISLAND X1 Y1 X2 Y2 [ROT]\n";
        }
        if (args.size() > 7 && (!number(args, 7, rotation) || rotation < 0 || rotation > 3)) {
            return "error: rotation 0 to 3\n";
        }
        std::uint32_t w = type.size_x;
        std::uint32_t h = type.size_y;
        if (rotation % 2 == 1) {
            std::swap(w, h);
        }
        for (std::int64_t sy = std::min(y, y2); sy + h - 1 <= std::max(y, y2); sy += h) {
            for (std::int64_t sx = std::min(x, x2); sx + w - 1 <= std::max(x, x2); sx += w) {
                order.items.push_back(sim::BuildItem{*id, static_cast<std::int32_t>(sx), static_cast<std::int32_t>(sy),
                                                     static_cast<std::uint8_t>(rotation), 0});
            }
        }
        if (order.items.empty() || order.items.size() > 512) {
            return "error: the rectangle holds no building or more than 512\n";
        }
        order.skip_unpaid = true;
    } else {
        if (args.size() > 5 && (!number(args, 5, rotation) || rotation < 0 || rotation > 3)) {
            return "error: rotation 0 to 3\n";
        }
        order.items.push_back(sim::BuildItem{*id, static_cast<std::int32_t>(x), static_cast<std::int32_t>(y),
                                             static_cast<std::uint8_t>(rotation), 0});
    }
    const sim::CommandResult result = control_execute(order);
    if (!result.build) {
        return "error: refused (the game did not accept the order: is your player still in the game?)\n";
    }
    if (result.build->placed > 0) {
        control_look_at(order.island, static_cast<std::int32_t>(x), static_cast<std::int32_t>(y));
    }
    std::string out = building_key(*id) + ": " + plan_text(*result.build);
    return result.build->placed == 0 ? "error: " + out : out;
}

std::string MapViewer::control_found(const std::vector<std::string>& args) {
    const sim::World& world = m_state->world;
    std::int64_t ship_id = 0;
    std::int64_t island = 0;
    if (!number(args, 1, ship_id) || !number(args, 2, island) || island < 0 ||
        static_cast<std::size_t>(island) >= world.islands().size()) {
        return "error: " + args[0] + " SHIP ISLAND ...\n";
    }
    const sim::Ship* ship = nullptr;
    for (const sim::Ship& s : world.ships()) {
        if (s.id == ship_id && s.owner == m_local_player) {
            ship = &s;
        }
    }
    if (ship == nullptr) {
        return "error: no such ship of yours\n";
    }
    sim::BuildOrder order;
    order.player = m_local_player;
    order.island = static_cast<std::uint16_t>(island);
    order.ship = ship->id;
    const std::uint32_t kontor = assets::id::kKontor1;
    if (args[0] == "kontor-sites") {
        const sim::WorldIsland& isl = world.islands()[static_cast<std::size_t>(island)];
        struct Site {
            std::int32_t x, y;
            std::string why;
            std::int64_t d2;
        };
        std::vector<Site> sites;
        for (std::uint32_t y = 0; y < isl.map.height(); ++y) {
            for (std::uint32_t x = 0; x < isl.map.width(); ++x) {
                order.items = {sim::BuildItem{kontor, static_cast<std::int32_t>(x), static_cast<std::int32_t>(y), 0, 0}};
                const sim::BuildPlan plan = sim::plan_build(world, m_buildings, order);
                if (plan.items.empty()) {
                    continue;
                }
                const auto r = plan.items.front().refusal;
                if (plan.items.front().ok() || sim::short_of_means(r) || r == sim::BuildRefusal::ShipTooFar) {
                    const std::int64_t dx = static_cast<std::int64_t>(isl.x + x) - ship->x;
                    const std::int64_t dy = static_cast<std::int64_t>(isl.y + y) - ship->y;
                    sites.push_back(Site{static_cast<std::int32_t>(x), static_cast<std::int32_t>(y),
                                         plan.items.front().ok() ? "ok" : sim::refusal_name(r), dx * dx + dy * dy});
                }
            }
        }
        std::sort(sites.begin(), sites.end(), [](const Site& a, const Site& b) { return a.d2 < b.d2; });
        std::string out = fmt("%zu Kontor sites on island %lld (world position of tile 0,0: %u,%u); nearest to the "
                              "ship first (x y: result; ship_too_far: sail closer, within 16 tiles):\n",
                              sites.size(), static_cast<long long>(island), isl.x, isl.y);
        for (std::size_t i = 0; i < sites.size() && i < 15; ++i) {
            out += fmt("  %d %d: %s (world %u,%u)\n", sites[i].x, sites[i].y, sites[i].why.c_str(),
                       isl.x + static_cast<std::uint32_t>(sites[i].x), isl.y + static_cast<std::uint32_t>(sites[i].y));
        }
        return out;
    }
    std::int64_t x = 0;
    std::int64_t y = 0;
    if (!number(args, 3, x) || !number(args, 4, y)) {
        return "error: found SHIP ISLAND X Y\n";
    }
    order.items = {sim::BuildItem{kontor, static_cast<std::int32_t>(x), static_cast<std::int32_t>(y), 0, 0}};
    const sim::CommandResult result = control_execute(order);
    if (!result.build) {
        return "error: refused (the game did not accept the order: is your player still in the game?)\n";
    }
    if (result.build->placed > 0) {
        control_look_at(order.island, static_cast<std::int32_t>(x), static_cast<std::int32_t>(y));
    }
    std::string out = "Kontor: " + plan_text(*result.build);
    if (result.build->placed == 0) {
        return "error: " + out;
    }
    // Where the new city is and whether the ship lies within reach of its Kontor already.
    const sim::WorldIsland& isl = world.islands()[static_cast<std::size_t>(island)];
    const std::uint8_t city_no = isl.map.contains(static_cast<std::uint32_t>(x), static_cast<std::uint32_t>(y))
                                    ? isl.map.top(static_cast<std::uint32_t>(x), static_cast<std::uint32_t>(y)).city
                                    : sim::MapCell::kNoCity;
    const sim::City* city =
        city_no == sim::MapCell::kNoCity ? nullptr : world.city(static_cast<std::uint16_t>(island), city_no);
    const sim::Ship* now = own_ship(world, m_local_player, ship->id);
    if (city != nullptr && city->warehouse_x && city->warehouse_y && now != nullptr) {
        const std::int64_t far = std::max(std::abs(isl.x + *city->warehouse_x - std::int64_t{now->x}),
                                          std::abs(isl.y + *city->warehouse_y - std::int64_t{now->y}));
        out += sim::building_in_reach(world, m_buildings, city->island, *city->warehouse_x, *city->warehouse_y, now->x,
                                      now->y)
                   ? fmt("new city: island %u city %u; ship %u lies in reach: unload %u all works now\n", city->island,
                         city->index, now->id, now->id)
                   : fmt("new city: island %u city %u; ship %u is %lld tiles from its Kontor (reach 5): ship-move %u "
                         "city %u %u first\n",
                         city->island, city->index, now->id, static_cast<long long>(far), now->id, city->island,
                         city->index);
    }
    return out;
}

std::string MapViewer::control_road(const std::vector<std::string>& args) {
    const sim::World& world = m_state->world;
    std::int64_t island = 0;
    std::int64_t x1 = 0;
    std::int64_t y1 = 0;
    std::int64_t x2 = 0;
    std::int64_t y2 = 0;
    if (!number(args, 1, island) || !number(args, 2, x1) || !number(args, 3, y1) || !number(args, 4, x2) ||
        !number(args, 5, y2) || island < 0 || static_cast<std::size_t>(island) >= world.islands().size()) {
        return "error: road ISLAND X1 Y1 X2 Y2\n";
    }
    const auto steps = sim::drag_path(world, m_buildings, static_cast<std::uint16_t>(island), sim::DragLine::Road,
                                      sim::TilePos{static_cast<std::int32_t>(x1), static_cast<std::int32_t>(y1)},
                                      sim::TilePos{static_cast<std::int32_t>(x2), static_cast<std::int32_t>(y2)}, 0);
    if (steps.size() == 1 && (x1 != x2 || y1 != y2)) {
        return "error: no road path between those tiles (both ends must be land a road may take: ground, forest, "
               "road; not beach, rock or buildings)\n";
    }
    sim::BuildOrder order;
    order.player = m_local_player;
    order.island = static_cast<std::uint16_t>(island);
    order.skip_unpaid = true;
    const sim::IslandMap& map = world.islands()[static_cast<std::size_t>(island)].map;
    for (const sim::DragStep& s : steps) {
        // Over a river a wooden bridge, turned along the way (as the computer players build them).
        const assets::BuildingType* b = nullptr;
        if (map.contains(static_cast<std::uint32_t>(s.x), static_cast<std::uint32_t>(s.y))) {
            const sim::MapCell& top = map.top(static_cast<std::uint32_t>(s.x), static_cast<std::uint32_t>(s.y));
            b = top.empty() ? nullptr : m_buildings.by_sprite(top.sprite);
        }
        // "stone" as the last word: paved roads (faster carriers; 1 t of bricks per tile), also over
        // an existing dirt road.
        const bool stone = args.size() > 6 && args[6] == "stone";
        if (b != nullptr && b->kind == kind::kRoad && (!stone || b->id == assets::id::kRoadStone)) {
            continue;  // already a road (of the kind wanted)
        }
        if (b != nullptr && (b->kind == kind::kRiver || b->kind == kind::kRiverCorner)) {
            order.items.push_back(
                sim::BuildItem{assets::id::kBridgeWood, s.x, s.y, static_cast<std::uint8_t>(s.rotation & 1U), 0});
        } else {
            order.items.push_back(
                sim::BuildItem{stone ? assets::id::kRoadStone : assets::id::kRoadDirt, s.x, s.y, s.rotation, 0});
        }
    }
    if (order.items.empty()) {
        return "the road is there already\n";
    }
    const sim::CommandResult result = control_execute(order);
    if (!result.build) {
        return "error: refused (the game did not accept the order: is your player still in the game?)\n";
    }
    if (result.build->placed > 0) {
        control_look_at(order.island, static_cast<std::int32_t>((x1 + x2) / 2), static_cast<std::int32_t>((y1 + y2) / 2));
    }
    std::string out = fmt("road of %zu tiles: ", steps.size()) + plan_text(*result.build);
    return result.build->placed == 0 ? "error: " + out : out;
}

std::string MapViewer::control_unconnected(std::uint16_t island, bool fix) {
    // Houses and production buildings of the player that no road touches: the doctor's and the
    // fire brigade's walkers, the carts and the carriers cannot reach them. With `fix`, a road is
    // laid from a free tile at the building to the nearest road.
    const sim::World& world = m_state->world;
    const sim::IslandMap& map = world.islands()[island].map;
    const auto is_road = [&](std::int32_t x, std::int32_t y) { return is_road_tile(map, m_buildings, x, y); };
    struct Spot {
        std::int32_t x, y;
        std::uint32_t w, h;
        std::string name;
    };
    std::vector<Spot> lonely;
    std::size_t houses = 0;
    for (const sim::House& h : world.houses()) {
        if (h.island != island || !map.contains(h.x, h.y) || map.top(h.x, h.y).owner != m_local_player) {
            continue;
        }
        ++houses;
        const std::uint32_t w = 2;
        const std::uint32_t hh = 2;
        bool touched = false;
        for (std::int32_t d = 0; d < 2 && !touched; ++d) {
            touched = is_road(h.x + d, h.y - 1) || is_road(h.x + d, h.y + 2) || is_road(h.x - 1, h.y + d) ||
                      is_road(h.x + 2, h.y + d);
        }
        if (!touched) {
            lonely.push_back(Spot{h.x, h.y, w, hh, "house"});
        }
    }
    std::string out = fmt("%zu of %zu houses on island %u have no road at their sides", lonely.size(), houses, island);
    if (lonely.empty()) {
        return out + " (all connected)\n";
    }
    out += fix ? ": laying roads\n" : ":\n";
    std::size_t fixed = 0;
    for (const Spot& s : lonely) {
        if (!fix) {
            out += fmt("  %s at %d,%d\n", s.name.c_str(), s.x, s.y);
            continue;
        }
        if (fixed >= 12) {
            break;
        }
        // The nearest road within 7 tiles.
        const auto link = control_link_road(island, s.x, s.y, s.w, s.h, 7, false, false);
        if (link) {
            control_look_at(island, s.x, s.y);
            out += fmt("  house at %d,%d: road of %zu tiles\n", s.x, s.y, link->placed);
            ++fixed;
        } else {
            out += fmt("  house at %d,%d: no way to a road found\n", s.x, s.y);
        }
    }
    return out;
}

std::optional<MapViewer::ControlRoadLink> MapViewer::control_link_road(std::uint16_t island, std::int32_t x,
                                                                      std::int32_t y, std::uint32_t w, std::uint32_t h,
                                                                      std::int32_t reach, bool to_market,
                                                                      bool only_test) {
    // A dirt road from a free tile beside the footprint to the nearest road tile within `reach` tiles; with
    // `to_market` a free tile beside one of the player's markets or Kontors counts as the end too (the carriers
    // reach the building from there, and a new colony has no road yet).
    const sim::World& world = m_state->world;
    const sim::IslandMap& map = world.islands()[island].map;
    const auto side_tiles = [](std::int32_t bx, std::int32_t by, std::uint32_t bw, std::uint32_t bh, auto&& visit) {
        const auto bwi = static_cast<std::int32_t>(bw);
        const auto bhi = static_cast<std::int32_t>(bh);
        for (std::int32_t ty = by - 1; ty <= by + bhi; ++ty) {
            for (std::int32_t tx = bx - 1; tx <= bx + bwi; ++tx) {
                const bool inside = tx >= bx && tx < bx + bwi && ty >= by && ty < by + bhi;
                const bool corner = (tx == bx - 1 || tx == bx + bwi) && (ty == by - 1 || ty == by + bhi);
                if (!inside && !corner) {
                    visit(tx, ty);
                }
            }
        }
    };
    std::set<std::pair<std::int32_t, std::int32_t>> market_sides;
    if (to_market) {
        for (const sim::Production& p : world.productions()) {
            if (!p.used || p.island != island || !map.contains(p.x, p.y)) {
                continue;
            }
            const sim::MapCell& cell = map.top(p.x, p.y);
            const assets::BuildingType* b = cell.empty() ? nullptr : m_buildings.by_sprite(cell.sprite);
            if (b != nullptr && cell.owner == m_local_player &&
                (b->prod_kind == prod::kMarket || b->prod_kind == prod::kKontor)) {
                std::uint32_t bw = 1;
                std::uint32_t bh = 1;
                sim::rotated_size(*b, cell.rotation, bw, bh);
                side_tiles(static_cast<std::int32_t>(p.x), static_cast<std::int32_t>(p.y), bw, bh,
                           [&](std::int32_t tx, std::int32_t ty) { market_sides.insert({tx, ty}); });
            }
        }
    }
    const auto is_end = [&](std::int32_t tx, std::int32_t ty) {
        return is_road_tile(map, m_buildings, tx, ty) || market_sides.contains({tx, ty});
    };
    std::optional<ControlRoadLink> link;
    side_tiles(x, y, w, h, [&](std::int32_t cx, std::int32_t cy) {
        if (link) {
            return;
        }
        const std::int32_t none = reach * 2 + 1;
        std::int32_t best_d = none;
        sim::TilePos best{};
        for (std::int32_t ry = cy - reach; ry <= cy + reach; ++ry) {
            for (std::int32_t rx = cx - reach; rx <= cx + reach; ++rx) {
                if (is_end(rx, ry) && std::abs(rx - cx) + std::abs(ry - cy) < best_d) {
                    best_d = std::abs(rx - cx) + std::abs(ry - cy);
                    best = sim::TilePos{rx, ry};
                }
            }
        }
        if (best_d == none) {
            return;
        }
        const auto steps =
            sim::drag_path(world, m_buildings, island, sim::DragLine::Road, sim::TilePos{cx, cy}, best, 0);
        if (steps.size() < 1 || (steps.size() == 1 && best_d > 0)) {
            return;
        }
        sim::BuildOrder order;
        order.player = m_local_player;
        order.island = island;
        order.skip_unpaid = true;
        for (const sim::DragStep& st : steps) {
            if (is_road_tile(map, m_buildings, st.x, st.y)) {
                continue;
            }
            // Over a river a wooden bridge, turned along the way (as `road` lays it).
            const assets::BuildingType* b = nullptr;
            if (st.x >= 0 && st.y >= 0 &&
                map.contains(static_cast<std::uint32_t>(st.x), static_cast<std::uint32_t>(st.y))) {
                const sim::MapCell& top = map.top(static_cast<std::uint32_t>(st.x), static_cast<std::uint32_t>(st.y));
                b = top.empty() ? nullptr : m_buildings.by_sprite(top.sprite);
            }
            const bool river = b != nullptr && (b->kind == kind::kRiver || b->kind == kind::kRiverCorner);
            order.items.push_back(river ? sim::BuildItem{assets::id::kBridgeWood, st.x, st.y,
                                                         static_cast<std::uint8_t>(st.rotation & 1U), 0}
                                        : sim::BuildItem{assets::id::kRoadDirt, st.x, st.y, st.rotation, 0});
        }
        if (order.items.empty()) {
            return;
        }
        if (only_test) {
            link = ControlRoadLink{0, order.items.size(), best, {}};
            return;
        }
        const sim::CommandResult r = control_execute(order);
        if (r.build && r.build->placed > 0) {
            // Why tiles are missing, when some are: the reasons the game gave, each once.
            std::string refused;
            for (const sim::PlannedBuild& item : r.build->items) {
                const std::string why = item.ok() ? std::string() : std::string(sim::refusal_name(item.refusal));
                if (!why.empty() && refused.find(why) == std::string::npos) {
                    refused += (refused.empty() ? "" : ", ") + why;
                }
            }
            link = ControlRoadLink{r.build->placed, order.items.size(), best, std::move(refused)};
        }
    });
    return link;
}

std::string MapViewer::control_alerts(std::optional<std::uint16_t> only) const {
    // Everything that needs the agent's attention, in one answer: the question marks the game
    // draws (production_status, as world_renderer), fires, full buildings nobody empties, missing
    // roads, houses without market or the public buildings of the next class, goods in short supply,
    // full storage, low building materials and money.
    const sim::World& world = m_state->world;
    std::vector<std::string> lines;
    const auto add = [&](const std::string& s) { lines.push_back(s); };
    const auto count_kind = [&](const sim::IslandMap& map, std::int32_t x, std::int32_t y, std::uint32_t w,
                                std::uint32_t h, std::int32_t r, auto pred) {
        std::int32_t n = 0;
        for (std::int32_t ty = y - r; ty < y + static_cast<std::int32_t>(h) + r; ++ty) {
            for (std::int32_t tx = x - r; tx < x + static_cast<std::int32_t>(w) + r; ++tx) {
                if (tx < 0 || ty < 0 || !map.contains(static_cast<std::uint32_t>(tx), static_cast<std::uint32_t>(ty))) {
                    continue;
                }
                const sim::MapCell& c = map.top(static_cast<std::uint32_t>(tx), static_cast<std::uint32_t>(ty));
                const assets::BuildingType* t = c.empty() ? nullptr : m_buildings.by_sprite(c.sprite);
                n += pred(t) ? 1 : 0;
            }
        }
        return n;
    };
    const auto road_beside = [&](const sim::IslandMap& map, std::int32_t x, std::int32_t y, std::uint32_t w,
                                 std::uint32_t h) {
        for (std::int32_t ty = y - 1; ty <= y + static_cast<std::int32_t>(h); ++ty) {
            for (std::int32_t tx = x - 1; tx <= x + static_cast<std::int32_t>(w); ++tx) {
                const bool inside = tx >= x && tx < x + static_cast<std::int32_t>(w) && ty >= y &&
                                    ty < y + static_cast<std::int32_t>(h);
                const bool corner = (tx == x - 1 || tx == x + static_cast<std::int32_t>(w)) &&
                                    (ty == y - 1 || ty == y + static_cast<std::int32_t>(h));
                if (inside || corner || tx < 0 || ty < 0 ||
                    !map.contains(static_cast<std::uint32_t>(tx), static_cast<std::uint32_t>(ty))) {
                    continue;
                }
                const sim::MapCell& c = map.top(static_cast<std::uint32_t>(tx), static_cast<std::uint32_t>(ty));
                const assets::BuildingType* t = c.empty() ? nullptr : m_buildings.by_sprite(c.sprite);
                if (t != nullptr && (t->kind == kind::kRoad || t->kind == kind::kBridge || t->kind == kind::kSquare ||
                                     t->kind == kind::kPier ||  // carts walk on piers (fisher at 48,7)
                                     t->prod_kind == prod::kMarket || t->prod_kind == prod::kKontor)) {
                    return true;
                }
            }
        }
        return false;
    };
    // Production buildings.
    for (const sim::Production& p : world.productions()) {
        if (!p.used || p.island >= world.islands().size() || (only && p.island != *only)) {
            continue;
        }
        const sim::IslandMap& map = world.islands()[p.island].map;
        if (!map.contains(p.x, p.y)) {
            continue;
        }
        const sim::MapCell& top = map.top(p.x, p.y);
        const assets::BuildingType* b = top.empty() ? nullptr : m_buildings.by_sprite(top.sprite);
        if (b == nullptr || top.owner != m_local_player || b->prod_kind == prod::kMarket || b->prod_kind == prod::kKontor ||
            b->ware == 0) {
            continue;
        }
        std::uint32_t w = 1;
        std::uint32_t h = 1;
        sim::rotated_size(*b, top.rotation, w, h);
        const std::string where = fmt("%s at %u,%u (island %u)", building_key(b->id).c_str(), p.x, p.y, p.island);
        const auto x = static_cast<std::int32_t>(p.x);
        const auto y = static_cast<std::int32_t>(p.y);
        const auto r = static_cast<std::int32_t>(b->radius);
        const sim::ProductionStatus status = sim::production_status(p, *b);
        if (status == sim::ProductionStatus::Burning) {
            add("[FIRE] " + where + " is burning");
        } else if (status == sim::ProductionStatus::NoRawGoods) {
            std::string why;
            const std::string key = building_key(b->id);
            if (key == "forester") {
                why = fmt("%d trees in reach (wants about 40): plant forest or move it",
                          count_kind(map, x, y, w, h, r, [](const assets::BuildingType* t) {
                              return t != nullptr && t->kind == kind::kForest;
                          }));
            } else if (key == "sheep_farm" || key == "cattle_farm") {
                const auto meadow = count_kind(map, x, y, w, h, r, [](const assets::BuildingType* t) {
                    return t != nullptr && t->kind == kind::kGround;
                });
                const auto trees = count_kind(map, x, y, w, h, r, [](const assets::BuildingType* t) {
                    return t != nullptr && t->kind == kind::kForest;
                });
                why = fmt("%d meadow tiles, %d forest tiles in reach: animals need open meadow", meadow, trees);
            } else if (key == "fishers_hut") {
                why = fmt("%d fish-ground tiles in reach: a fisher needs sea with fish (no inland lake)",
                          count_kind(map, x, y, w, h, r, [](const assets::BuildingType* t) {
                              return t != nullptr && t->kind == kind::kSea && t->prod_kind == prod::kRipe &&
                                     t->ware == assets::ware::kFish;
                          }));
            } else if (b->prod_kind == prod::kFarm) {
                why = fmt("%d fields in reach (radius %d): plant more fields",
                          count_kind(map, x, y, w, h, r, [](const assets::BuildingType* t) {
                              return t != nullptr && (t->prod_kind == prod::kGrowing || t->prod_kind == prod::kRipe);
                          }),
                          r);
            } else if (b->raw_ware != 0) {
                const sim::City* c = world.city(p.island, top.city);
                const double have = c != nullptr ? tons(c->stock(b->raw_ware)) : 0.0;
                why = fmt("no %s delivered (%.1f t in the Kontor): build its producers or connect them",
                          ware_key(b->raw_ware).c_str(), have);
            } else {
                why = "no raw material";
            }
            add("[?] " + where + ": " + why);
        }
        if (b->max_stock > 0 && p.stock >= b->max_stock) {
            add(fmt("[FULL] %s: %.1f t waiting, nobody collects (road to a market? storage full?)", where.c_str(),
                    tons(p.stock)));
        }
        if (!road_beside(map, x, y, w, h)) {
            add("[ROAD] " + where + " has no road at its side: carts cannot reach it");
        }
    }
    // Houses.
    std::map<std::string, std::vector<std::string>> house_issues;
    for (const sim::House& hs : world.houses()) {
        if (hs.island >= world.islands().size() || (only && hs.island != *only)) {
            continue;
        }
        const sim::IslandMap& map = world.islands()[hs.island].map;
        if (!map.contains(hs.x, hs.y) || map.top(hs.x, hs.y).owner != m_local_player) {
            continue;
        }
        const std::string at = fmt("%u,%u", hs.x, hs.y);
        const std::string isl = fmt("island %u", hs.island);
        // Fire and plague on houses (the original's disaster bits): the most urgent of all.
        const auto disaster = hs.services & sim::house_service::kDisasterMask;
        if (disaster == 2) {
            house_issues["BURNING: a fire station (radius 15) puts it out  " + isl].push_back(at);
        } else if (disaster == 1) {
            house_issues["PLAGUE: a doctor (radius 16) heals it  " + isl].push_back(at);
        }
        if (!road_beside(map, hs.x, hs.y, 2, 2)) {
            house_issues["no road at its side (fire brigade, doctor)  " + isl].push_back(at);
        }
        if (!hs.market) {
            house_issues["no market in reach (gets no goods)  " + isl].push_back(at);
        }
        const auto next = static_cast<std::uint8_t>(hs.resident_class + 1);
        if (next < 5 && !sim::has_services(hs, m_buildings, next)) {
            house_issues[fmt("lacks the public buildings %s need (cannot rise)  ", class_key(next).c_str()) + isl]
                .push_back(at);
        }
    }
    for (const auto& [issue, at] : house_issues) {
        std::string list;
        for (std::size_t i = 0; i < at.size() && i < 8; ++i) {
            list += (i ? " " : "") + at[i];
        }
        // "BURNING" and "PLAGUE" sort before the lower-case issues: the fires come first.
        const char* tag = issue.rfind("BURNING", 0) == 0 ? "[FIRE]" : (issue.rfind("PLAGUE", 0) == 0 ? "[PLAGUE]" : "[HOUSE]");
        add(fmt("%s %zu houses: %s: %s%s", tag, at.size(), issue.c_str(), list.c_str(), at.size() > 8 ? " ..." : ""));
    }
    // Cities: supply, storage, materials.
    const auto& classes = m_buildings.resident_classes();
    for (const sim::City& c : world.cities()) {
        if (c.owner != m_local_player || (only && c.island != *only)) {
            continue;
        }
        const std::string city = fmt("island %u city %u", c.island, c.index);
        if (c.food_ratio < 128) {
            add(fmt("[SUPPLY] %s: food %u%%", city.c_str(), c.food_ratio * 100U / 128U));
        }
        std::set<std::uint8_t> wanted;
        for (std::size_t k = 0; k < c.inhabitants.size() && k < classes.size(); ++k) {
            if (c.inhabitants[k] == 0) {
                continue;
            }
            for (const auto& need : classes[k].needs) {
                wanted.insert(need.ware);
            }
        }
        for (const std::uint8_t ware : wanted) {
            const auto ratio = ware < c.supply.size() ? c.supply[ware].ratio : 0;
            if (ratio < 128) {
                add(fmt("[SUPPLY] %s: %s only %u%%", city.c_str(), ware_key(ware).c_str(), ratio * 100U / 128U));
            }
        }
        for (const std::uint8_t w : world.goods().trade_wares()) {
            if (c.capacity > 0 && c.stock(w) + 32 >= c.capacity) {
                add(fmt("[STORE] %s: %s storage full (%.0f t): sell or use it, producers stop", city.c_str(),
                        ware_key(w).c_str(), tons(c.stock(w))));
            }
        }
        for (const char* m : {"tools", "wood", "bricks"}) {
            const auto w = ware_arg(m);
            if (w && tons(c.stock(*w)) < 5.0) {
                add(fmt("[MATERIAL] %s: only %.1f t %s", city.c_str(), tons(c.stock(*w)), m));
            }
        }
    }
    const sim::Player& me = *world.player(m_local_player);
    const auto figures = sim::player_figures(world, m_buildings, m_figures, m_local_player);
    if (figures.balance < 0) {
        add(fmt("[MONEY] balance %lld per minute (taxes %lld, running costs %lld)", static_cast<long long>(figures.balance),
                static_cast<long long>(figures.taxes), static_cast<long long>(figures.running_costs)));
    }
    if (me.money < 1000) {
        add(fmt("[MONEY] only %d gold left (bankrupt below -1000)", me.money));
    }
    // Money first, then fire, plague, hunger and short supply; the rest keeps its order. Then the cut.
    const auto urgency = [](const std::string& line) {
        constexpr std::array<std::string_view, 4> kUrgent = {"[MONEY]", "[FIRE]", "[PLAGUE]", "[SUPPLY]"};
        for (std::size_t i = 0; i < kUrgent.size(); ++i) {
            if (line.starts_with(kUrgent[i])) {
                return i;
            }
        }
        return kUrgent.size();
    };
    std::stable_sort(lines.begin(), lines.end(), [&](const std::string& a, const std::string& b) {
        return urgency(a) < urgency(b);
    });
    constexpr std::size_t kShown = 60;
    std::string out = lines.size() > kShown ? fmt("%zu alerts (%zu shown, most urgent first)\n", lines.size(), kShown)
                                            : fmt("%zu alerts\n", lines.size());
    for (std::size_t i = 0; i < lines.size() && i < kShown; ++i) {
        out += lines[i] + "\n";
    }
    return out;
}

std::string MapViewer::control_economy(std::uint16_t island, std::uint8_t city) const {
    // Per good of an own city: stock and room, what the inhabitants use, the trend the Kontor panel shows
    // (the city's goods ledger over panel_detail::StockList::kTrendMinutes) and how long the stock lasts at the balance
    // of the goods window (sim::minutes_left).
    const sim::World& world = m_state->world;
    const sim::City* c = world.city(island, city);
    if (c == nullptr) {
        return "error: no such city\n";
    }
    if (c->owner != m_local_player) {
        return "error: not your city (economy shows only your own, see: cities)\n";
    }
    // The inhabitants' use per 10-s tick is demand / 256 units; a minute has six ticks (consumption.cpp).
    std::vector<std::uint64_t> demand(256);
    const auto& classes = m_buildings.resident_classes();
    for (std::size_t k = 0; k < c->inhabitants.size() && k < classes.size(); ++k) {
        for (const auto& need : classes[k].needs) {
            demand[need.ware] += std::uint64_t{need.amount} * c->inhabitants[k];
        }
        demand[m_buildings.food_ware()] += std::uint64_t{m_buildings.food_need()} * c->inhabitants[k];
    }
    struct Row {
        std::uint64_t soonest = UINT64_MAX;  // minutes until empty, the sort key
        std::string text;
    };
    std::vector<Row> rows;
    std::string full;
    for (const std::uint8_t w : world.goods().trade_wares()) {
        const sim::FlowTotals t = c->ledger.totals(w, panel_detail::StockList::kTrendMinutes);
        const std::uint32_t stock = c->stock(w);
        const std::uint64_t use = demand[w] * 6 / 256;
        if (c->capacity > 0 && stock + 32 >= c->capacity) {
            full += (full.empty() ? " " : ", ") + ware_key(w);
        }
        if (stock == 0 && use == 0 && t.in() == 0 && t.out() == 0) {
            continue;
        }
        Row row;
        const std::optional<std::uint32_t> left = sim::minutes_left(stock, t);
        row.soonest = stock == 0 ? (use > 0 ? 0 : UINT64_MAX) : (left ? *left : UINT64_MAX);
        const std::string trend = panel_detail::StockList::trend_text(*c, w);
        row.text = fmt("%s %.1f/%.0f t, need %.1f/min, trend %s", ware_key(w).c_str(), tons(stock), tons(c->capacity),
                       tons(static_cast<std::uint32_t>(use)),
                       t.minutes == 0 ? "?" : (trend.empty() ? "0" : trend.c_str()));
        row.text += stock == 0 ? (use > 0 ? ", empty" : "") : (left ? fmt(", empty in %u min", *left) : std::string());
        rows.push_back(std::move(row));
    }
    std::stable_sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) { return a.soonest < b.soonest; });
    std::string out = fmt("economy island %u city %u: stock/room, the inhabitants' need, trend over the last %u min "
                          "(t per minute, as the Kontor panel)\n",
                          island, city, panel_detail::StockList::kTrendMinutes);
    for (const Row& r : rows) {
        out += r.text + "\n";
    }
    return out + (full.empty() ? "none at the room limit\n" : "at the room limit (producers stop):" + full + "\n");
}

std::string MapViewer::control_demolish(const std::vector<std::string>& args) {
    std::int64_t island = 0;
    std::int64_t x = 0;
    std::int64_t y = 0;
    std::int64_t x2 = 0;
    std::int64_t y2 = 0;
    const bool rectangle = args.size() == 6;
    if (!number(args, 1, island) || !number(args, 2, x) || !number(args, 3, y) || island < 0 ||
        static_cast<std::size_t>(island) >= m_state->world.islands().size() ||
        (args.size() != 4 && !(rectangle && number(args, 4, x2) && number(args, 5, y2)))) {
        return "error: demolish ISLAND X Y | demolish ISLAND X1 Y1 X2 Y2\n";
    }
    if (!rectangle) {
        x2 = x;
        y2 = y;
    }
    constexpr std::int64_t kMaxSide = 32;
    if (std::abs(x2 - x) >= kMaxSide || std::abs(y2 - y) >= kMaxSide) {
        return "error: the rectangle is larger than 32 x 32 tiles\n";
    }
    sim::DemolishOrder order;
    order.player = m_local_player;
    order.island = static_cast<std::uint16_t>(island);
    order.from = sim::TilePos{static_cast<std::int32_t>(x), static_cast<std::int32_t>(y)};
    order.to = sim::TilePos{static_cast<std::int32_t>(x2), static_cast<std::int32_t>(y2)};
    const auto n = control_execute(order).demolished;
    if (n > 0) {
        control_look_at(order.island, static_cast<std::int32_t>((x + x2) / 2), static_cast<std::int32_t>((y + y2) / 2));
    }
    if (n == 0) {
        return "error: nothing of yours to demolish there\n";
    }
    // A rectangle leaves houses and workshops standing unless nothing else is in it (as the game's drag does).
    return rectangle ? fmt("demolished %zu in %lld x %lld tiles (houses and workshops in it stay unless it holds "
                           "nothing else)\n",
                           n, static_cast<long long>(std::abs(x2 - x) + 1),
                           static_cast<long long>(std::abs(y2 - y) + 1))
                     : fmt("demolished %zu\n", n);
}

std::string MapViewer::control_ship_move(const std::vector<std::string>& args) {
    std::int64_t id = 0;
    if (!number(args, 1, id)) {
        return "error: ship-move SHIP X Y | ship-move SHIP city ISLAND CITY | ship-stop SHIP\n";
    }
    sim::ShipOrder order;
    order.player = m_local_player;
    order.ship = static_cast<std::uint32_t>(id);
    std::string where = "sailing\n";
    if (args[0] == "ship-move" && args.size() > 2 && args[2] == "city") {
        // As a trade route's stop: the ship sails until it lies within reach of that city's Kontor.
        const sim::World& world = m_state->world;
        std::int64_t island = 0;
        std::int64_t city = 0;
        if (args.size() != 5 || !number(args, 3, island) || !number(args, 4, city) || island < 0 || island > 0xFFFF ||
            city < 0 || city > 0xFF) {
            return "error: ship-move SHIP city ISLAND CITY\n";
        }
        const sim::City* kontor = world.city(static_cast<std::uint16_t>(island), static_cast<std::uint8_t>(city));
        if (kontor == nullptr || !kontor->warehouse_x || !kontor->warehouse_y ||
            control_hides(static_cast<std::uint16_t>(island))) {
            return "error: no city with a Kontor there (see: cities, or islands for the numbers)\n";
        }
        const sim::WorldIsland& isl = world.islands()[kontor->island];
        order.target = sim::Target::city_of(kontor->island, kontor->index);
        where = fmt("sailing to the Kontor of island %lld city %lld (world tile %u,%u); it stops within 5 tiles of "
                    "it, then load and unload work\n",
                    static_cast<long long>(island), static_cast<long long>(city), isl.x + *kontor->warehouse_x,
                    isl.y + *kontor->warehouse_y);
    } else if (args[0] == "ship-move") {
        std::int64_t x = 0;
        std::int64_t y = 0;
        if (!number(args, 2, x) || !number(args, 3, y) || x < 0 || y < 0 || x >= m_state->world.width() ||
            y >= m_state->world.height()) {
            return "error: ship-move SHIP X Y (world tiles)\n";
        }
        order.target = sim::Target::position(static_cast<std::uint32_t>(x), static_cast<std::uint32_t>(y));
    }
    const bool ok = control_execute(order).accepted;
    if (ok) {
        for (const sim::Ship& s : m_state->world.ships()) {
            if (s.id == order.ship) {
                control_look_at_world(s.x, s.y);  // the ship setting off
            }
        }
    }
    return ok ? (args[0] == "ship-move" ? where : "stopped\n") : "error: refused (your ship? sea tile?)\n";
}

std::string MapViewer::control_cargo(const std::vector<std::string>& args, bool to_ship) {
    std::int64_t id = 0;
    std::int64_t amount = 0;
    const bool all = !to_ship && args.size() == 3 && args[2] == "all";
    const auto ware = args.size() > 2 ? ware_arg(args[2]) : std::nullopt;
    if (!number(args, 1, id) || (!all && (!ware || !number(args, 3, amount) || amount < 1 || amount > 10000))) {
        return "error: " + args[0] + " SHIP WARE TONS" + (to_ship ? "" : " | unload SHIP all") + " (see: goods)\n";
    }
    const sim::Player* me = m_state->world.player(m_local_player);
    // One transfer of `units` (1/32 t) of a ware: the line saying what moved, empty when nothing did.
    const auto transfer = [&](std::uint8_t w, std::uint32_t units) {
        sim::CargoTransfer order;
        order.player = m_local_player;
        order.ship = static_cast<std::uint32_t>(id);
        order.ware = w;
        order.to_ship = to_ship;
        order.amount = units;
        const std::int64_t money_before = me != nullptr ? me->money : 0;
        const auto result = control_execute(order);
        if (result.moved == 0) {
            return std::string();
        }
        // At another player's Kontor (trade treaty) the goods are bought or sold at its prices.
        const std::int64_t paid = (me != nullptr ? me->money : 0) - money_before;
        const std::string money = paid > 0   ? fmt(", sold for %lld gold", static_cast<long long>(paid))
                                  : paid < 0 ? fmt(", bought for %lld gold", static_cast<long long>(-paid))
                                             : std::string();
        std::string line = fmt("%s %.1f t of %s%s", to_ship ? "loaded" : "unloaded", tons(result.moved),
                               ware_key(w).c_str(), money.c_str());
        if (all && result.moved < units) {
            line += fmt(" (%.1f t stay on board: Kontor room or money)", tons(units - result.moved));
        }
        return line + "\n";
    };
    const char* nothing = "error: nothing moved (at your Kontor, or a foreign one with a trade treaty that buys or "
                          "sells it; within 5 tiles? room? stock? money?)\n";
    if (!all) {
        const std::string line = transfer(*ware, static_cast<std::uint32_t>(amount) * 32U);
        return line.empty() ? nothing : line;
    }
    // Everything on board, one ware at a time (the holds counted before the first order).
    const sim::Ship* ship = own_ship(m_state->world, m_local_player, static_cast<std::uint32_t>(id));
    if (ship == nullptr) {
        return "error: no such ship of yours\n";
    }
    std::map<std::uint8_t, std::uint32_t> board;
    for (const sim::CargoSlot& slot : ship->cargo) {
        if (slot.ware != 0 && slot.amount > 0 && m_state->world.goods().is_trade(slot.ware)) {
            board[slot.ware] += slot.amount;
        }
    }
    if (board.empty()) {
        return "error: nothing on board that a Kontor takes (see: ships)\n";
    }
    std::string out;
    for (const auto& [w, units] : board) {
        out += transfer(w, units);
    }
    return out.empty() ? nothing : out;
}

namespace {

/// The tiles between a building and a house along one axis, as sim/src/houses.cpp measures the
/// reach of markets and public buildings (from the building's middle tile or two).
std::int32_t reach_gap(std::int32_t origin, std::uint32_t size, std::int32_t house, std::uint32_t house_size) {
    const auto w = static_cast<std::int32_t>(size) - 1;
    const std::int32_t first = origin + w / 2;
    const std::int32_t last = first + (w & 1);
    const std::int32_t house_last = house + static_cast<std::int32_t>(house_size) - 1;
    if (house_last < first) {
        return first - house_last;
    }
    if (house > last) {
        return house - last;
    }
    return 0;
}

}  // namespace

std::string MapViewer::control_coverage(std::uint16_t island, std::int32_t x, std::int32_t y, std::int32_t w,
                                        std::int32_t h) const {
    // Which own markets, Kontors and public buildings reach a house of w x h at (x, y).
    const sim::World& world = m_state->world;
    const sim::IslandMap& map = world.islands()[island].map;
    std::map<std::string, int> reached;
    for (const sim::Production& p : world.productions()) {
        if (!p.used || p.island != island || !map.contains(p.x, p.y)) {
            continue;
        }
        const sim::MapCell& cell = map.top(p.x, p.y);
        const assets::BuildingType* b = cell.empty() ? nullptr : m_buildings.by_sprite(cell.sprite);
        if (b == nullptr || cell.owner != m_local_player || b->radius == 0 ||
            (b->prod_kind != prod::kMarket && b->prod_kind != prod::kKontor && b->ware != 0)) {
            continue;
        }
        std::uint32_t bw = 1;
        std::uint32_t bh = 1;
        sim::rotated_size(*b, cell.rotation, bw, bh);
        const std::int32_t dx = reach_gap(p.x, bw, x, static_cast<std::uint32_t>(w));
        const std::int32_t dy = reach_gap(p.y, bh, y, static_cast<std::uint32_t>(h));
        const auto r = static_cast<std::int32_t>(b->radius);
        if (dx > r || dy > r) {
            continue;
        }
        const auto& circle = sim::circle_table(b->radius);
        if (dx > circle[static_cast<std::size_t>(dy)]) {
            continue;
        }
        ++reached[building_key(b->id)];
    }
    std::string out = "reached by:";
    for (const auto& [name, n] : reached) {
        out += " " + name;
    }
    return reached.empty() ? "reached by: nothing (no market: a house there gets no goods)" : out;
}

namespace {

/// A road, bridge, square, market or Kontor at a side of the footprint (corners do not count):
/// what carts, carriers, the doctor and the fire brigade need.
bool road_beside(const sim::IslandMap& map, const assets::BuildingTable& buildings, std::int32_t x, std::int32_t y,
                 std::uint32_t w, std::uint32_t h) {
    const auto W = static_cast<std::int32_t>(w);
    const auto H = static_cast<std::int32_t>(h);
    for (std::int32_t ty = y - 1; ty <= y + H; ++ty) {
        for (std::int32_t tx = x - 1; tx <= x + W; ++tx) {
            const bool inside = tx >= x && tx < x + W && ty >= y && ty < y + H;
            const bool corner = (tx == x - 1 || tx == x + W) && (ty == y - 1 || ty == y + H);
            if (inside || corner || tx < 0 || ty < 0 ||
                !map.contains(static_cast<std::uint32_t>(tx), static_cast<std::uint32_t>(ty))) {
                continue;
            }
            const sim::MapCell& c = map.top(static_cast<std::uint32_t>(tx), static_cast<std::uint32_t>(ty));
            const assets::BuildingType* b = c.empty() ? nullptr : buildings.by_sprite(c.sprite);
            if (b != nullptr && (b->kind == kind::kRoad || b->kind == kind::kBridge || b->kind == kind::kSquare ||
                                 b->kind == kind::kPier || b->prod_kind == prod::kMarket ||
                                 b->prod_kind == prod::kKontor)) {
                return true;
            }
        }
    }
    return false;
}

/// The public buildings of the house panel's bits, by name.
std::string panel_names(std::uint32_t bits) {
    static constexpr std::array<std::pair<std::uint32_t, const char*>, 9> kNames = {{
        {sim::panel_service::kMarkt, "marketplace"},
        {sim::panel_service::kKapelle, "chapel"},
        {sim::panel_service::kSchule, "school"},
        {sim::panel_service::kWirtshaus, "tavern"},
        {sim::panel_service::kKirche, "church"},
        {sim::panel_service::kBadehaus, "bathhouse"},
        {sim::panel_service::kTheater, "theatre"},
        {sim::panel_service::kHochschule, "college"},
        {sim::panel_service::kKlinik, "doctor"},
    }};
    std::string out;
    for (const auto& [bit, name] : kNames) {
        if ((bits & bit) != 0) {
            out += (out.empty() ? "" : ",") + std::string(name);
        }
    }
    return out.empty() ? "-" : out;
}

}  // namespace

std::string MapViewer::control_houses(std::uint16_t island, bool problems, std::size_t max) const {
    // Every own house of the island in one answer (as the house panel shows it): road at its side,
    // market in reach, the public buildings that reach it and those the next class still lacks.
    const sim::World& world = m_state->world;
    const sim::IslandMap& map = world.islands()[island].map;
    std::string rows;
    std::size_t n = 0;
    std::size_t with_problems = 0;
    std::size_t listed = 0;
    std::size_t no_road = 0;
    std::size_t no_market = 0;
    std::map<std::string, std::size_t> lacking;
    for (const sim::House& hs : world.houses()) {
        if (hs.island != island || !map.contains(hs.x, hs.y) || map.top(hs.x, hs.y).owner != m_local_player) {
            continue;
        }
        ++n;
        const bool road = road_beside(map, m_buildings, hs.x, hs.y, 2, 2);
        const std::uint32_t have = sim::panel_services(hs);
        const auto next = static_cast<std::uint8_t>(hs.resident_class + 1);
        const std::uint32_t need = next < 5 ? sim::required_panel_services(m_buildings, next) : 0;
        const std::uint32_t lacks = need & ~have & ~sim::panel_service::kMarkt;
        no_road += road ? 0 : 1;
        no_market += hs.market ? 0 : 1;
        if (lacks != 0) {
            ++lacking[panel_names(lacks)];
        }
        const auto disaster = hs.services & sim::house_service::kDisasterMask;
        const bool problem = !road || !hs.market || lacks != 0 || disaster != 0;
        with_problems += problem ? 1 : 0;
        if ((problems && !problem) || (max != 0 && listed >= max)) {
            continue;
        }
        ++listed;
        rows += fmt("  %u %u %s %u %s %s have:%s lacks:%s%s\n", hs.x, hs.y, class_key(hs.resident_class).c_str(),
                    hs.inhabitants(), road ? "road" : "no-road", hs.market ? "market" : "no-market",
                    panel_names(have).c_str(), lacks ? panel_names(lacks).c_str() : "-",
                    disaster == 2 ? " BURNING" : (disaster == 1 ? " PLAGUE" : ""));
    }
    std::string out = fmt("%zu houses on island %u", n, island);
    out += problems ? fmt(", %zu with problems", with_problems) : std::string();
    out += fmt(": %zu without road, %zu without market", no_road, no_market);
    for (const auto& [names, count] : lacking) {
        out += fmt("; %zu lack %s for the next class", count, names.c_str());
    }
    const std::size_t matching = problems ? with_problems : n;
    out += "\n  (x y class inhabitants road market have: lacks:)\n";
    out += matching > listed ? fmt("  (%zu more not listed)\n", matching - listed) : std::string();
    return out + rows;
}

std::string MapViewer::control_house_sites(std::uint16_t island, std::size_t max,
                                           std::vector<ControlSite>* found) const {
    // Every place on the island where a house fits, has a road at its side and a market or Kontor
    // in reach (the placing preview shows the same): one answer instead of a find-site per street.
    const sim::World& world = m_state->world;
    const sim::IslandMap& map = world.islands()[island].map;
    const auto house_id = building_arg("house");
    if (!house_id || m_buildings.by_id(*house_id) == nullptr) {
        return "error: no house type\n";
    }
    struct Hub {
        std::int32_t x, y;
        std::uint32_t w, h, r;
    };
    std::vector<Hub> hubs;
    for (const sim::Production& p : world.productions()) {
        if (!p.used || p.island != island || !map.contains(p.x, p.y)) {
            continue;
        }
        const sim::MapCell& cell = map.top(p.x, p.y);
        const assets::BuildingType* b = cell.empty() ? nullptr : m_buildings.by_sprite(cell.sprite);
        if (b != nullptr && cell.owner == m_local_player &&
            (b->prod_kind == prod::kMarket || b->prod_kind == prod::kKontor) && b->radius > 0) {
            std::uint32_t w = 1;
            std::uint32_t h = 1;
            sim::rotated_size(*b, cell.rotation, w, h);
            hubs.push_back(Hub{static_cast<std::int32_t>(p.x), static_cast<std::int32_t>(p.y), w, h, b->radius});
        }
    }
    struct Site {
        std::int32_t x, y, gap;
        sim::BuildRefusal refusal;
    };
    std::vector<Site> sites;
    sim::BuildOrder order;
    order.player = m_local_player;
    order.island = island;
    for (std::uint32_t y = 0; y + 1 < map.height(); ++y) {
        for (std::uint32_t x = 0; x + 1 < map.width(); ++x) {
            const auto sx = static_cast<std::int32_t>(x);
            const auto sy = static_cast<std::int32_t>(y);
            if (!road_beside(map, m_buildings, sx, sy, 2, 2)) {
                continue;
            }
            std::int32_t best = 1 << 20;
            for (const Hub& hub : hubs) {
                const std::int32_t dx = reach_gap(hub.x, hub.w, sx, 2);
                const std::int32_t dy = reach_gap(hub.y, hub.h, sy, 2);
                const auto r = static_cast<std::int32_t>(hub.r);
                if (dx <= r && dy <= r &&
                    dx <= sim::circle_table(static_cast<std::uint8_t>(hub.r))[static_cast<std::size_t>(dy)]) {
                    best = std::min(best, dx + dy);
                }
            }
            if (best == (1 << 20)) {
                continue;
            }
            order.items = {sim::BuildItem{*house_id, sx, sy, 0, 0}};
            const sim::BuildPlan plan = sim::plan_build(world, m_buildings, order);
            if (!plan.items.empty() && (plan.items.front().ok() || sim::short_of_means(plan.items.front().refusal))) {
                sites.push_back(Site{sx, sy, best, plan.items.front().refusal});
            }
        }
    }
    // Close to a market first (goods arrive sooner); places that overlap a better one are left out.
    std::stable_sort(sites.begin(), sites.end(), [](const Site& a, const Site& b) { return a.gap < b.gap; });
    std::vector<Site> picked;
    for (const Site& s : sites) {
        const bool overlaps = std::any_of(picked.begin(), picked.end(), [&](const Site& p) {
            return std::abs(p.x - s.x) < 2 && std::abs(p.y - s.y) < 2;
        });
        if (!overlaps) {
            picked.push_back(s);
        }
        if (picked.size() >= max) {
            break;
        }
    }
    std::string out = fmt("%zu house places with a road and a market on island %u (%zu without overlap shown; x y "
                          "distance-to-market):\n",
                          sites.size(), island, picked.size());
    for (const Site& s : picked) {
        if (found != nullptr) {
            found->push_back(ControlSite{s.x, s.y, 0, s.refusal});
        }
        out += fmt("  %d %d %d%s\n", s.x, s.y, s.gap, short_mark(s.refusal).c_str());
    }
    return out;
}

std::string MapViewer::control_sites(const std::vector<std::string>& args,
                                     std::vector<ControlSite>* found) const {
    // The best places on the whole island for a building, scored as its catchment preview shows:
    // trees for a forester or hunter, open meadow (no forest) for sheep and cattle, open water for a
    // fisher, free land for the fields of a plantation or farm, quarry tiles for a stonemason; any
    // other building by its distance to the nearest own market.
    const sim::World& world = m_state->world;
    std::int64_t island = 0;
    std::int64_t max = 12;
    const auto id = args.size() > 1 ? building_arg(args[1]) : std::nullopt;
    if (!id || m_buildings.by_id(*id) == nullptr || !number(args, 2, island) || island < 0 ||
        static_cast<std::size_t>(island) >= world.islands().size() ||
        (args.size() > 3 && (!number(args, 3, max) || max < 1 || max > 60))) {
        return "error: sites NAME ISLAND [MAX]\n";
    }
    const auto isl = static_cast<std::uint16_t>(island);
    const sim::IslandMap& map = world.islands()[isl].map;
    const assets::BuildingType& type = *m_buildings.by_id(*id);
    const std::string key = building_key(*id);
    enum class Score { Trees, Meadow, Water, Fields, Quarry, Market } score = Score::Market;
    if (key == "forester" || key == "hunters_hut") {
        score = Score::Trees;
    } else if (key == "sheep_farm" || key == "cattle_farm") {
        score = Score::Meadow;
    } else if (key == "fishers_hut") {
        score = Score::Water;
    } else if (key == "stonemason") {
        score = Score::Quarry;
    } else if (type.prod_kind == prod::kFarm) {
        score = Score::Fields;
    }
    std::vector<std::pair<std::int32_t, std::int32_t>> markets;
    for (const sim::Production& p : world.productions()) {
        if (p.used && p.island == isl && map.contains(p.x, p.y)) {
            const sim::MapCell& cell = map.top(p.x, p.y);
            const assets::BuildingType* b = cell.empty() ? nullptr : m_buildings.by_sprite(cell.sprite);
            if (b != nullptr && cell.owner == m_local_player &&
                (b->prod_kind == prod::kMarket || b->prod_kind == prod::kKontor)) {
                markets.emplace_back(static_cast<std::int32_t>(p.x), static_cast<std::int32_t>(p.y));
            }
        }
    }
    const auto r = static_cast<std::int32_t>(std::max<std::uint32_t>(type.radius, 1));
    const auto value = [&](std::int32_t x, std::int32_t y, std::uint32_t w, std::uint32_t h) {
        if (score == Score::Market) {
            std::int32_t best = 1000;
            for (const auto& [mx, my] : markets) {
                best = std::min(best, std::abs(mx - x) + std::abs(my - y));
            }
            return -best;
        }
        std::int32_t v = 0;
        for (std::int32_t ty = y - r; ty < y + static_cast<std::int32_t>(h) + r; ++ty) {
            for (std::int32_t tx = x - r; tx < x + static_cast<std::int32_t>(w) + r; ++tx) {
                if (tx < 0 || ty < 0 || !map.contains(static_cast<std::uint32_t>(tx), static_cast<std::uint32_t>(ty))) {
                    continue;
                }
                const sim::MapCell& c = map.top(static_cast<std::uint32_t>(tx), static_cast<std::uint32_t>(ty));
                const assets::BuildingType* t = c.empty() ? nullptr : m_buildings.by_sprite(c.sprite);
                if (t == nullptr) {
                    continue;
                }
                switch (score) {
                    case Score::Trees: v += t->kind == kind::kForest ? 1 : 0; break;
                    case Score::Meadow: v += t->kind == kind::kGround ? 1 : (t->kind == kind::kForest ? -1 : 0); break;
                    // Fish grounds only: sea tiles that carry fish (logistics: a fisher's goal), not any
                    // water (a fisher on an inland lake caught nothing).
                    case Score::Water:
                        v += (t->kind == kind::kSea && t->prod_kind == prod::kRipe && t->ware == assets::ware::kFish) ? 1 : 0;
                        break;
                    case Score::Fields:
                        v += (t->kind == kind::kGround && c.city != sim::MapCell::kNoCity) ? 1 : 0;
                        break;
                    case Score::Quarry: v += t->prod_kind == prod::kQuarry ? 1 : 0; break;
                    case Score::Market: break;
                }
            }
        }
        return v;
    };
    struct Site {
        std::int32_t x, y;
        int rotation;
        bool road;
        std::int32_t value;
        sim::BuildRefusal refusal;
    };
    std::vector<Site> sites;
    sim::BuildOrder order;
    order.player = m_local_player;
    order.island = isl;
    const int rotations = type.rotate > 0 ? 4 : 1;
    for (std::uint32_t y = 0; y < map.height(); ++y) {
        for (std::uint32_t x = 0; x < map.width(); ++x) {
            for (int rot = 0; rot < rotations; ++rot) {
                order.items = {sim::BuildItem{*id, static_cast<std::int32_t>(x), static_cast<std::int32_t>(y),
                                              static_cast<std::uint8_t>(rot), 0}};
                const sim::BuildPlan plan = sim::plan_build(world, m_buildings, order);
                if (plan.items.empty() || !(plan.items.front().ok() || sim::short_of_means(plan.items.front().refusal))) {
                    continue;
                }
                std::uint32_t w = type.size_x;
                std::uint32_t h = type.size_y;
                sim::rotated_size(type, static_cast<std::uint8_t>(rot), w, h);
                const auto sx = static_cast<std::int32_t>(x);
                const auto sy = static_cast<std::int32_t>(y);
                sites.push_back(Site{sx, sy, rot, road_beside(map, m_buildings, sx, sy, w, h), value(sx, sy, w, h),
                                     plan.items.front().refusal});
                break;  // one rotation per place
            }
        }
    }
    std::stable_sort(sites.begin(), sites.end(), [](const Site& a, const Site& b) {
        return a.value != b.value ? a.value > b.value : a.road > b.road;
    });
    // Spread out: no two places of the list share most of their catchment.
    std::vector<Site> picked;
    const std::int32_t spread = score == Score::Market ? 2 : std::max<std::int32_t>(2, r + 1);
    for (const Site& s : sites) {
        if (std::none_of(picked.begin(), picked.end(), [&](const Site& p) {
                return std::abs(p.x - s.x) < spread && std::abs(p.y - s.y) < spread;
            })) {
            picked.push_back(s);
        }
        if (picked.size() >= static_cast<std::size_t>(max)) {
            break;
        }
    }
    static constexpr std::array<const char*, 6> kScore = {"trees", "meadow", "water", "free field land", "quarry tiles",
                                                          "minus distance to a market"};
    std::string out = fmt("%s fits at %zu places on island %u; the best by %s in reach (radius %d) (x y rotation "
                          "road score):\n",
                          key.c_str(), sites.size(), isl, kScore[static_cast<std::size_t>(score)], r);
    for (const Site& s : picked) {
        if (found != nullptr) {
            found->push_back(ControlSite{s.x, s.y, static_cast<std::uint8_t>(s.rotation), s.refusal});
        }
        out += fmt("  %d %d %d %s %d%s\n", s.x, s.y, s.rotation, s.road ? "road" : "no-road", s.value,
                   short_mark(s.refusal).c_str());
    }
    return out;
}

std::string MapViewer::control_build_auto(const std::vector<std::string>& args) {
    // build NAME ISLAND auto [X Y]: one building at the best place the searches know (sites; house-sites for a
    // house; find-site near X Y), then a road to the nearest road if none touches it.
    const sim::World& world = m_state->world;
    const auto id = building_arg(args[1]);
    if (!id || m_buildings.by_id(*id) == nullptr) {
        return "error: no such building (see: buildings)\n";
    }
    std::int64_t island = 0;
    std::int64_t near_x = 0;
    std::int64_t near_y = 0;
    const bool near = args.size() == 6;
    if (!number(args, 2, island) || island < 0 || static_cast<std::size_t>(island) >= world.islands().size() ||
        (args.size() != 4 && !(near && number(args, 4, near_x) && number(args, 5, near_y)))) {
        return "error: build NAME ISLAND auto [X Y]\n";
    }
    const auto isl = static_cast<std::uint16_t>(island);
    const assets::BuildingType& type = *m_buildings.by_id(*id);
    std::vector<ControlSite> sites;
    std::string listing;
    if (near) {
        listing = control_build({"find-site", args[1], args[2], args[4], args[5]}, &sites);
    } else if (type.prod_kind == prod::kHouse) {
        listing = control_house_sites(isl, 30, &sites);
    } else {
        listing = control_sites({"sites", args[1], args[2], "60"}, &sites);
    }
    if (sites.empty()) {
        return listing.rfind("error", 0) == 0
                   ? listing
                   : "error: no free place for " + building_key(*id) +
                         (near ? " within 8 tiles of that tile" : " on the island") +
                         ", or it is locked (see: buildings)\n";
    }
    // The first place that can be paid and that a road, a market or the Kontor touches or a road can reach:
    // a building no carrier comes to is money lost. At most 40 places are tried.
    constexpr std::int32_t kRoadReach = 20;
    const sim::IslandMap& ground = world.islands()[isl].map;
    // A house keeps out of the windows of the player's foresters (3 tiles around them) while another place
    // is left: there it would stand on the trees the forester lives off.
    std::vector<sim::TilePos> foresters;
    if (const auto forester = building_arg("forester"); forester && type.prod_kind == prod::kHouse) {
        for (const sim::Production& p : world.productions()) {
            if (!p.used || p.island != isl || !ground.contains(p.x, p.y)) {
                continue;
            }
            const sim::MapCell& cell = ground.top(p.x, p.y);
            const assets::BuildingType* b = cell.empty() ? nullptr : m_buildings.by_sprite(cell.sprite);
            if (b != nullptr && b->id == *forester && cell.owner == m_local_player) {
                foresters.push_back(sim::TilePos{static_cast<std::int32_t>(p.x), static_cast<std::int32_t>(p.y)});
            }
        }
    }
    const auto in_forester_window = [&](const ControlSite& s) {
        // Both stand on 2x2 tiles: within 3 tiles of the forester means origins at most 4 apart.
        return std::any_of(foresters.begin(), foresters.end(), [&](const sim::TilePos& f) {
            return std::max(std::abs(s.x - f.x), std::abs(s.y - f.y)) <= 4;
        });
    };
    auto best = sites.end();
    std::size_t payable = 0;
    for (const bool avoid : {true, false}) {
        payable = 0;
        for (auto s = sites.begin(); s != sites.end() && payable < 40; ++s) {
            if (s->refusal != sim::BuildRefusal::None) {
                continue;
            }
            ++payable;
            if (avoid && in_forester_window(*s)) {
                continue;
            }
            std::uint32_t sw = type.size_x;
            std::uint32_t sh = type.size_y;
            sim::rotated_size(type, s->rotation, sw, sh);
            if (road_beside(ground, m_buildings, s->x, s->y, sw, sh) ||
                control_link_road(isl, s->x, s->y, sw, sh, kRoadReach, true, true)) {
                best = s;
                break;
            }
        }
        if (best != sites.end() || foresters.empty()) {
            break;
        }
    }
    if (payable == 0) {
        return fmt("error: no place you can pay for now; the best, at %d,%d, is%s\n", sites.front().x, sites.front().y,
                   short_mark(sites.front().refusal).c_str());
    }
    if (best == sites.end()) {
        return fmt("error: none of the %zu best places can be reached by a road within %d tiles; nothing built "
                   "(choose a place with sites or find-site and build it there)\n",
                   payable, kRoadReach);
    }
    sim::BuildOrder order;
    order.player = m_local_player;
    order.island = isl;
    order.items = {sim::BuildItem{*id, best->x, best->y, best->rotation, 0}};
    const sim::CommandResult result = control_execute(order);
    if (!result.build) {
        return "error: refused (the game did not accept the order: is your player still in the game?)\n";
    }
    std::string out = fmt("%s at %d,%d rotation %u: ", building_key(*id).c_str(), best->x, best->y,
                          static_cast<unsigned>(best->rotation)) +
                      plan_text(*result.build);
    if (result.build->placed == 0) {
        return "error: " + out;
    }
    control_look_at(isl, best->x, best->y);
    // The second order depends on the first: the road is planned around the building on the copy of the world.
    std::uint32_t w = type.size_x;
    std::uint32_t h = type.size_y;
    sim::rotated_size(type, best->rotation, w, h);
    if (road_beside(world.islands()[isl].map, m_buildings, best->x, best->y, w, h)) {
        return out + "road: already connected\n";
    }
    const auto link = control_link_road(isl, best->x, best->y, w, h, kRoadReach, true, false);
    if (!link) {
        return out + "road: no way found\n";
    }
    return out + (link->placed == link->wanted
                      ? fmt("road: %zu tiles to %d,%d\n", link->placed, link->to.x, link->to.y)
                      : fmt("road: %zu of %zu tiles to %d,%d (%s: not connected yet, see fix-roads or road)\n",
                            link->placed, link->wanted, link->to.x, link->to.y, link->refused.c_str()));
}

std::string MapViewer::control_route(const std::vector<std::string>& args) {
    std::int64_t id = 0;
    if (!number(args, 1, id) || args.size() < 3) {
        return "error: route SHIP show|start|stop|clear | route SHIP stop N ISLAND CITY [load|unload WARE TONS]...\n";
    }
    const sim::Ship* ship = nullptr;
    for (const sim::Ship& s : m_state->world.ships()) {
        if (s.id == id && s.owner == m_local_player) {
            ship = &s;
        }
    }
    if (ship == nullptr) {
        return "error: no such ship of yours\n";
    }
    const std::string& what = args[2];
    sim::RouteEdit edit;
    edit.player = m_local_player;
    edit.ship = ship->id;
    const auto run = [&](sim::RouteEdit e) { return control_execute(e).accepted; };
    if (what == "show") {
        std::string out = fmt("route of ship %u: %s\n", ship->id, ship->route.active ? "running" : "stopped");
        for (std::size_t n = 0; n < ship->route.stops.size(); ++n) {
            const sim::RouteStop& s = ship->route.stops[n];
            if (s.target.empty()) {
                continue;
            }
            std::string entries;
            for (const sim::RouteEntry& e : s.entries) {
                if (e.ware != 0) {
                    entries += fmt(" %s %s %.0f t;", e.unload ? "unload" : "load", ware_key(e.ware).c_str(),
                                   tons(e.amount));
                }
            }
            out += fmt("  stop %zu: island %u city %u%s%s\n", n, s.target.island, s.target.city,
                       entries.empty() ? " (nothing)" : ":", entries.c_str());
        }
        return out;
    }
    if (what == "start" || (what == "stop" && args.size() == 3)) {
        edit.op = what == "start" ? sim::RouteEdit::Op::Start : sim::RouteEdit::Op::Stop;
        return run(edit) ? "route " + what + "ed\n" : "error: refused (no stops?)\n";
    }
    if (what == "clear") {
        edit.op = sim::RouteEdit::Op::ClearStop;
        edit.stop = 0xFF;
        return run(edit) ? "route cleared\n" : "error: refused\n";
    }
    std::int64_t n = 0;
    std::int64_t island = 0;
    std::int64_t city = 0;
    if (what != "stop" || !number(args, 3, n) || n < 0 || n >= static_cast<std::int64_t>(sim::TradeRoute::kStops) ||
        !number(args, 4, island) || !number(args, 5, city) ||
        m_state->world.city(static_cast<std::uint16_t>(island), static_cast<std::uint8_t>(city)) == nullptr) {
        return "error: route SHIP stop N ISLAND CITY [load|unload WARE TONS]... (N 0-7, a city with a Kontor)\n";
    }
    // The whole command is checked before the first order goes out: a half-set route is worse than none.
    if ((args.size() - 6) % 3 != 0) {
        return "error: the last entry is incomplete (load|unload WARE TONS); nothing changed\n";
    }
    std::vector<sim::RouteEntry> entries;
    for (std::size_t i = 6; i + 2 < args.size(); i += 3) {
        const auto ware = ware_arg(args[i + 1]);
        std::int64_t amount = 0;
        if ((args[i] != "load" && args[i] != "unload") || !ware || !number(args, i + 2, amount) || amount < 0 ||
            amount > 10000 || !m_state->world.goods().is_trade(*ware)) {
            return fmt("error: entry %zu: load|unload WARE TONS (a trade good, see: goods; TONS 0..10000); nothing "
                       "changed\n",
                       entries.size());
        }
        entries.push_back(sim::RouteEntry{*ware, args[i] == "unload", static_cast<std::uint32_t>(amount) * 32U});
    }
    if (entries.size() > sim::RouteStop::kEntries) {
        return fmt("error: at most %zu entries a stop; nothing changed\n", sim::RouteStop::kEntries);
    }
    edit.op = sim::RouteEdit::Op::SetStop;
    edit.stop = static_cast<std::uint8_t>(n);
    edit.target = sim::Target::city_of(static_cast<std::uint16_t>(island), static_cast<std::uint8_t>(city));
    if (!run(edit)) {
        return "error: refused stop (a city of yours, or one whose Kontor the route may call at?); nothing changed\n";
    }
    for (std::size_t i = 0; i < entries.size(); ++i) {
        sim::RouteEdit e = edit;
        e.op = sim::RouteEdit::Op::SetEntry;
        e.entry = static_cast<std::uint8_t>(i);
        e.value = entries[i];
        if (!run(e)) {
            return fmt("error: entry %zu refused after the stop was set; see: route SHIP show\n", i);
        }
    }
    return fmt("stop %lld set with %zu entries (route SHIP start to run it)\n", static_cast<long long>(n),
               entries.size());
}

}  // namespace o1602::app
