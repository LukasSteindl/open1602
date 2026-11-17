// SPDX-License-Identifier: GPL-3.0-or-later
#include "army.hpp"

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstdlib>

#include "o1602/sim/land_paths.hpp"
#include "o1602/sim/military.hpp"

namespace o1602::tool {

namespace {

constexpr std::uint64_t kOrderTicks = 30'000 / sim::Simulation::kTickMs;  // new orders every 30 s
constexpr std::size_t kGroup = 12;                                        // units ordered together
constexpr std::uint8_t kAnimWalk = 0;
constexpr std::uint8_t kAnimAttack = 2;
// Swordsmen, cavalry, musketeers, cannoneers: the first figure of each family.
constexpr std::array<std::uint32_t, 4> kFamilies = {1, 5, 9, 13};
// A target cleared farther than a soldier may stop from a spot (7 half tiles) was given up after
// failed searches, not reached.
constexpr std::uint32_t kStopRange = 7;

bool on_way(const sim::Soldier& s) {
    return !s.away() &&
           (s.motion.phase == sim::SoldierMotion::Phase::Run || s.motion.path_index < s.motion.path.size());
}

std::int32_t chebyshev(std::int32_t dx, std::int32_t dy) {
    return std::max(std::abs(dx), std::abs(dy));
}

}  // namespace

std::uint64_t ArmyBench::next_random() {
    // splitmix64: the measurement's own numbers, apart from the game's.
    std::uint64_t z = (m_random += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30U)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27U)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31U);
}

bool ArmyBench::walkable(const sim::Simulation& simulation, std::int32_t x, std::int32_t y) const {
    const sim::LandMap& land = simulation.combat().land();
    if (land.island_at(x, y) == sim::World::kSea) {
        return false;
    }
    const assets::BuildingType* b = land.building(x, y);
    return b == nullptr || sim::soldiers_walk_on(*b);
}

bool ArmyBench::connected(const sim::Simulation& simulation, const sim::World& world, std::uint16_t island,
                          std::int32_t ax, std::int32_t ay, std::int32_t bx, std::int32_t by) {
    if (island >= world.islands().size()) {
        return false;
    }
    const sim::WorldIsland& isl = world.islands()[island];
    const auto x0 = static_cast<std::int32_t>(isl.x);
    const auto y0 = static_cast<std::int32_t>(isl.y);
    const auto w = static_cast<std::int32_t>(isl.map.width());
    const auto h = static_cast<std::int32_t>(isl.map.height());
    const auto inside = [&](std::int32_t x, std::int32_t y) { return x >= x0 && y >= y0 && x < x0 + w && y < y0 + h; };
    if (!inside(ax, ay) || !inside(bx, by)) {
        return false;
    }
    std::vector<std::uint32_t>& region = m_regions[island];
    if (region.empty()) {
        // Label the island's walkable tiles once: flood fill over tiles joined by their sides.
        const sim::LandMap& land = simulation.combat().land();
        const auto at = [&](std::int32_t x, std::int32_t y) {
            return static_cast<std::size_t>(y - y0) * static_cast<std::size_t>(w) + static_cast<std::size_t>(x - x0);
        };
        region.assign(static_cast<std::size_t>(w) * static_cast<std::size_t>(h), 0);
        std::uint32_t next = 1;
        std::vector<std::pair<std::int32_t, std::int32_t>> stack;
        for (std::int32_t y = y0; y < y0 + h; ++y) {
            for (std::int32_t x = x0; x < x0 + w; ++x) {
                if (region[at(x, y)] != 0 || land.tile(x, y, 0) != sim::LandMap::Cell::Walk) {
                    continue;
                }
                region[at(x, y)] = next;
                stack.emplace_back(x, y);
                while (!stack.empty()) {
                    const auto [cx, cy] = stack.back();
                    stack.pop_back();
                    constexpr std::array<std::pair<std::int32_t, std::int32_t>, 4> kSides{
                        {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}};
                    for (const auto& [dx, dy] : kSides) {
                        const std::int32_t nx = cx + dx;
                        const std::int32_t ny = cy + dy;
                        if (inside(nx, ny) && region[at(nx, ny)] == 0 &&
                            land.tile(nx, ny, 0) == sim::LandMap::Cell::Walk) {
                            region[at(nx, ny)] = next;
                            stack.emplace_back(nx, ny);
                        }
                    }
                }
                ++next;
            }
        }
    }
    const auto at = [&](std::int32_t x, std::int32_t y) {
        return static_cast<std::size_t>(y - y0) * static_cast<std::size_t>(w) + static_cast<std::size_t>(x - x0);
    };
    return region[at(ax, ay)] != 0 && region[at(ax, ay)] == region[at(bx, by)];
}

bool ArmyBench::walled_in_by_units(const sim::Simulation& simulation, const sim::World& world,
                                   const sim::Soldier& s) const {
    // Flood fill over walkable cells within 9 cells, the cells of other units blocked (the
    // planner blocks them within 8): walled in when the fill does not reach the box's edge.
    constexpr std::int32_t kBox = 9;
    constexpr std::int32_t kSide = 2 * kBox + 1;
    const sim::LandMap& land = simulation.combat().land();
    std::array<std::uint8_t, kSide * kSide> state{};  // 1 blocked, 2 seen
    const std::int32_t x0 = s.cell_x() - kBox;
    const std::int32_t y0 = s.cell_y() - kBox;
    for (const sim::Soldier& o : world.soldiers()) {
        const std::int32_t i = o.cell_x() - x0;
        const std::int32_t j = o.cell_y() - y0;
        if (o.id != s.id && !o.away() && i >= 0 && j >= 0 && i < kSide && j < kSide) {
            state[static_cast<std::size_t>(j * kSide + i)] = 1;
        }
    }
    std::vector<std::pair<std::int32_t, std::int32_t>> stack{{kBox, kBox}};
    state[static_cast<std::size_t>(kBox * kSide + kBox)] = 2;
    while (!stack.empty()) {
        const auto [i, j] = stack.back();
        stack.pop_back();
        if (i == 0 || j == 0 || i == kSide - 1 || j == kSide - 1) {
            return false;
        }
        constexpr std::array<std::pair<std::int32_t, std::int32_t>, 4> kSides{{{1, 0}, {-1, 0}, {0, 1}, {0, -1}}};
        for (const auto& [dx, dy] : kSides) {
            const std::int32_t ni = i + dx;
            const std::int32_t nj = j + dy;
            auto& st = state[static_cast<std::size_t>(nj * kSide + ni)];
            if (st != 0 || land.cell(x0 + ni, y0 + nj, 0) != sim::LandMap::Cell::Walk) {
                continue;
            }
            st = 2;
            stack.emplace_back(ni, nj);
        }
    }
    return true;
}

std::size_t ArmyBench::place(sim::Simulation& simulation, const sim::World& world, const assets::FigureTable& figures,
                             std::size_t per_player, std::uint64_t seed) {
    m_random = seed;
    m_units.assign(world.players().size(), {});
    std::vector<std::uint32_t> families;
    for (const std::uint32_t f : kFamilies) {
        if (figures.unit_of(f) && figures.get(f) != nullptr) {
            families.push_back(f);
        }
    }
    if (families.empty()) {
        return 0;
    }
    std::size_t placed = 0;
    for (sim::PlayerId p = 0; p < world.players().size(); ++p) {
        if (world.behaviour(world.players()[p]) != sim::FactionBehaviour::Settlers) {
            continue;
        }
        const auto city = std::find_if(world.cities().begin(), world.cities().end(), [&](const sim::City& c) {
            return c.owner == p && c.warehouse_x && c.warehouse_y && c.island < world.islands().size();
        });
        if (city == world.cities().end()) {
            continue;
        }
        const sim::WorldIsland& isl = world.islands()[city->island];
        const auto cx = static_cast<std::int32_t>(isl.x + *city->warehouse_x);
        const auto cy = static_cast<std::int32_t>(isl.y + *city->warehouse_y);
        // Rings around the warehouse, one unit per free tile.
        std::size_t n = 0;
        for (std::int32_t r = 1; r < 200 && n < per_player; ++r) {
            for (std::int32_t dy = -r; dy <= r && n < per_player; ++dy) {
                for (std::int32_t dx = -r; dx <= r && n < per_player; ++dx) {
                    if (chebyshev(dx, dy) != r || !walkable(simulation, cx + dx, cy + dy)) {
                        continue;
                    }
                    const std::uint32_t family = families[n % families.size()];
                    if (const auto id = simulation.script_unit(p, family, cx + dx, cy + dy)) {
                        m_units[p].push_back(*id);
                        ++n;
                    }
                }
            }
        }
        placed += n;
    }
    return placed;
}

void ArmyBench::order(sim::Simulation& simulation, const sim::World& world, std::uint64_t tick) {
    if (tick % kOrderTicks != 0) {
        return;
    }
    ++m_round;
    for (sim::PlayerId p = 0; p < m_units.size(); ++p) {
        std::vector<std::uint32_t>& units = m_units[p];
        std::erase_if(units, [&](std::uint32_t id) {
            const sim::Soldier* s = world.soldier(id);
            return s == nullptr || s->owner != p;
        });
        for (std::size_t g = 0; g * kGroup < units.size(); ++g) {
            const std::size_t first = g * kGroup;
            const std::size_t last = std::min(units.size(), first + kGroup);
            const sim::Soldier* lead = world.soldier(units[first]);
            if (lead == nullptr || lead->away() || lead->island >= world.islands().size()) {
                continue;
            }
            const std::uint32_t kind = static_cast<std::uint32_t>((g + m_round) % 3);
            if (kind == 2) {
                continue;  // stands
            }
            const sim::WorldIsland& isl = world.islands()[lead->island];
            std::int32_t tx = -1;
            std::int32_t ty = -1;
            if (kind == 1) {
                // To another city's warehouse on the island.
                for (const sim::City& c : world.cities()) {
                    if (c.island == lead->island && c.owner != p && c.warehouse_x && c.warehouse_y) {
                        tx = static_cast<std::int32_t>(isl.x + *c.warehouse_x) + 2;
                        ty = static_cast<std::int32_t>(isl.y + *c.warehouse_y) + 2;
                        break;
                    }
                }
            }
            // Across the island: a land tile far from the group that the group can walk to.
            const auto reachable = [&](std::int32_t x, std::int32_t y) {
                return x >= 0 && walkable(simulation, x, y) &&
                       connected(simulation, world, lead->island, lead->cell_x() / 2, lead->cell_y() / 2, x, y);
            };
            if (tx >= 0 && !reachable(tx, ty)) {
                tx = -1;
            }
            for (int attempt = 0; attempt < 64 && !reachable(tx, ty); ++attempt) {
                tx = static_cast<std::int32_t>(isl.x + next_random() % std::max<std::uint32_t>(1, isl.map.width()));
                ty = static_cast<std::int32_t>(isl.y + next_random() % std::max<std::uint32_t>(1, isl.map.height()));
                if (chebyshev(2 * tx - lead->cell_x(), 2 * ty - lead->cell_y()) < 30) {
                    tx = -1;
                }
            }
            if (!reachable(tx, ty)) {
                continue;
            }
            // As the interface sends a group: the spot, each unit with its place in the group.
            sim::SoldierOrder o;
            o.player = p;
            o.target = sim::Target::tile_spot(static_cast<std::uint32_t>(tx), static_cast<std::uint32_t>(ty));
            std::int64_t sx = 0;
            std::int64_t sy = 0;
            for (std::size_t i = first; i < last; ++i) {
                if (const sim::Soldier* s = world.soldier(units[i])) {
                    sx += s->pos_x;
                    sy += s->pos_y;
                }
            }
            const auto count = static_cast<std::int64_t>(last - first);
            for (std::size_t i = first; i < last; ++i) {
                const sim::Soldier* s = world.soldier(units[i]);
                o.soldiers.push_back(units[i]);
                const std::int64_t eighth = sim::kPosUnit / 8;
                const auto ox = s != nullptr ? (s->pos_x - sx / count) / eighth : 0;
                const auto oy = s != nullptr ? (s->pos_y - sy / count) / eighth : 0;
                o.offsets.emplace_back(static_cast<std::int16_t>(std::clamp<std::int64_t>(ox, -64, 64)),
                                       static_cast<std::int16_t>(std::clamp<std::int64_t>(oy, -64, 64)));
            }
            ++m_orders;
            if (simulation.execute(o).accepted) {
                ++m_orders_accepted;
                for (const std::uint32_t id : o.soldiers) {
                    if (const sim::Soldier* s = world.soldier(id);
                        s != nullptr && s->target.kind == sim::Target::Kind::Spot) {
                        m_goals[id] =
                            Goal{static_cast<std::int32_t>(s->target.x), static_cast<std::int32_t>(s->target.y), true};
                    }
                }
            }
        }
    }
}

void ArmyBench::before_tick(const sim::World& world) {
    for (const sim::Soldier& s : world.soldiers()) {
        Before& b = m_before[s.id];
        b.x = s.pos_x;
        b.y = s.pos_y;
        b.on_way = on_way(s);
        b.direction = s.direction;
    }
}

void ArmyBench::after_tick(const sim::World& world, const sim::Simulation& simulation) {
    ++m_ticks;
    const sim::Military::PlanStats& stats = simulation.military().plan_stats();
    m_searches += stats.searches;
    m_cells += stats.cells;
    m_turned_away += stats.turned_away;
    m_turned_away_walking += stats.turned_away_walking;
    m_max_turned_away = std::max(m_max_turned_away, stats.turned_away);
    m_ticks_budget_used_up += stats.turned_away > 0 ? 1U : 0U;
    for (const sim::Soldier& s : world.soldiers()) {
        const auto it = m_before.find(s.id);
        if (it == m_before.end() || s.away()) {
            continue;
        }
        Before& b = it->second;
        const std::int32_t moved = chebyshev(s.pos_x - b.x, s.pos_y - b.y);
        const bool now_on_way = on_way(s);
        if (moved == 0 && s.anim == kAnimWalk) {
            ++m_walk_in_place_ticks;
        }
        if (b.on_way && now_on_way) {
            ++m_on_way_ticks;
            if (moved == 0 && s.anim != kAnimAttack) {
                ++m_stall_ticks;
                ++b.stall;
                m_longest_stall = std::max(m_longest_stall, b.stall);
            } else {
                b.stall = 0;
            }
        } else {
            b.stall = 0;
        }
        // An order but no way yet: waiting for a search (or after a failed one).
        if (!s.target.empty() && !now_on_way && moved == 0 && s.anim != kAnimAttack &&
            s.motion.phase == sim::SoldierMotion::Phase::Wait) {
            ++m_wait_ticks;
            ++b.waiting;
            if (b.waiting > m_longest_wait) {
                m_longest_wait = b.waiting;
                const sim::Player* pl = world.player(s.owner);
                char text[320];
                std::snprintf(text, sizeof text,
                              "unit %u of player %u (behaviour %d, role %d), figure %u, %s, cell %d,%d, target kind %d "
                              "at %u,%u (ship/unit %u), failures %u, wait %u us, hold %d, patrol %d, attack move %d",
                              s.id, unsigned{s.owner}, pl != nullptr ? static_cast<int>(world.behaviour(*pl)) : -1,
                              pl != nullptr ? static_cast<int>(pl->role) : -1, unsigned{s.figure},
                              m_goals.contains(s.id) ? "placed by the bench" : "of the game", s.cell_x(), s.cell_y(),
                              static_cast<int>(s.target.kind), s.target.x, s.target.y, s.target.ship,
                              unsigned{s.failures}, s.motion.duration_us, int{s.hold}, int{s.patrol.active},
                              int{s.attack_move});
                m_longest_wait_unit = text;
            }
        } else {
            if (b.waiting >= 200) {
                ++m_long_waits;
            }
            b.waiting = 0;
        }
        if (moved > 0 && b.moved > 0) {
            ++m_moving_pairs;
            if (s.direction == b.direction && std::abs(moved - b.moved) * 8 > b.moved) {
                ++m_tempo_changes;
            }
            if (s.direction != b.direction) {
                ++m_turns;
            }
        }
        m_cells_walked += static_cast<std::uint64_t>(moved);  // in 1/4096 tile, divided in print()
        b.moved = moved;
        // The order done (the target cleared on arrival): how far from the cell it was sent to.
        // Another target (a fight, the next order) ends the goal without counting.
        if (const auto g = m_goals.find(s.id); g != m_goals.end() && g->second.open) {
            if (s.target.empty()) {
                const auto d =
                    static_cast<std::uint32_t>(chebyshev(s.cell_x() - g->second.x2, s.cell_y() - g->second.y2));
                m_arrival.push_back(d);
                g->second.open = false;
                // A spot that is built over is reached from a cell within kStopRange of it.
                bool joined = false;
                for (std::int32_t dy = -3; d > kStopRange && !joined && dy <= 3; ++dy) {
                    for (std::int32_t dx = -3; !joined && dx <= 3; ++dx) {
                        joined = connected(simulation, world, s.island, s.cell_x() / 2, s.cell_y() / 2,
                                           g->second.x2 / 2 + dx, g->second.y2 / 2 + dy);
                    }
                }
                if (joined) {
                    ++m_given_up_reachable;
                    // Why: walled in by other units (as the planner sees them), or no coarse way.
                    const bool enclosed = walled_in_by_units(simulation, world, s);
                    m_given_up_enclosed += enclosed ? 1U : 0U;
                    sim::LandRoute route;
                    route.start_x = s.cell_x();
                    route.start_y = s.cell_y();
                    route.walker = s.owner;
                    route.goal_area = sim::CellRect{g->second.x2, g->second.y2, g->second.x2, g->second.y2};
                    route.goal_reach = static_cast<std::int32_t>(kStopRange);
                    std::uint32_t tiles = 0;
                    route.visited = &tiles;
                    route.max_tiles = 16'384;
                    const bool near_route = m_route_planner.waypoint(simulation.combat().land(), route).has_value();
                    bool far_route = near_route;
                    if (!near_route) {
                        route.max_tiles = 1U << 22U;
                        far_route = m_route_planner.waypoint(simulation.combat().land(), route).has_value();
                    }
                    m_given_up_route += near_route ? 1U : 0U;
                    m_given_up_far_route += !near_route && far_route ? 1U : 0U;
                    if (m_given_up_samples.size() < 8) {
                        char text[240];
                        std::snprintf(
                            text, sizeof text,
                            "unit %u of player %u, figure %u, at cell %d,%d, spot %d,%d; walled in by units %d, "
                            "coarse way %s (%u tiles)",
                            s.id, unsigned{s.owner}, unsigned{s.figure}, s.cell_x(), s.cell_y(), g->second.x2,
                            g->second.y2, int{enclosed},
                            near_route  ? "yes"
                            : far_route ? "only beyond 16384 tiles"
                                        : "no",
                            tiles);
                        m_given_up_samples.emplace_back(text);
                    }
                }
            } else if (s.target.kind != sim::Target::Kind::Spot ||
                       static_cast<std::int32_t>(s.target.x) != g->second.x2 ||
                       static_cast<std::int32_t>(s.target.y) != g->second.y2) {
                g->second.open = false;
                ++m_goals_dropped;
            }
        }
    }
}

void ArmyBench::print() const {
    const auto per = [](std::uint64_t a, std::uint64_t b) {
        return b != 0 ? 100.0 * static_cast<double>(a) / static_cast<double>(b) : 0.0;
    };
    const double ticks = static_cast<double>(std::max<std::uint64_t>(1, m_ticks));
    const double cells = static_cast<double>(m_cells_walked) / static_cast<double>(sim::kCellUnit);
    std::printf("\narmy: %llu orders (%llu accepted), every 30 s in groups of %zu\n",
                static_cast<unsigned long long>(m_orders), static_cast<unsigned long long>(m_orders_accepted), kGroup);
    std::printf("way searches: %.2f per tick, %.0f cells per tick, budget used up in %.1f%% of the ticks\n",
                static_cast<double>(m_searches) / ticks, static_cast<double>(m_cells) / ticks,
                per(m_ticks_budget_used_up, m_ticks));
    std::printf("turned away: %.2f per tick (max %u), %.2f per tick with a way still to go\n",
                static_cast<double>(m_turned_away) / ticks, m_max_turned_away,
                static_cast<double>(m_turned_away_walking) / ticks);
    std::printf("on the way: %llu unit ticks, standing although the way goes on %.2f%%, longest %u ticks (%u ms)\n",
                static_cast<unsigned long long>(m_on_way_ticks), per(m_stall_ticks, m_on_way_ticks), m_longest_stall,
                m_longest_stall * sim::Simulation::kTickMs);
    std::printf("walk animation without moving: %llu unit ticks\n",
                static_cast<unsigned long long>(m_walk_in_place_ticks));
    std::printf("an order but no way yet (waiting for a search): %llu unit ticks, longest %u ticks (%u ms)\n",
                static_cast<unsigned long long>(m_wait_ticks), m_longest_wait,
                m_longest_wait * sim::Simulation::kTickMs);
    std::printf("waits for a way of 10 s or more that ended: %llu; the longest: %s\n",
                static_cast<unsigned long long>(m_long_waits), m_longest_wait_unit.c_str());
    std::printf("tempo changes on a straight line: %.2f%% of %llu moving ticks; %llu turns in %.0f half tiles walked\n",
                per(m_tempo_changes, m_moving_pairs), static_cast<unsigned long long>(m_moving_pairs),
                static_cast<unsigned long long>(m_turns), cells);
    std::printf("way searches per unit tick on the way: %.4f; goals given up for a fight or another order: %llu\n",
                m_on_way_ticks != 0 ? static_cast<double>(m_searches) / static_cast<double>(m_on_way_ticks) : 0.0,
                static_cast<unsigned long long>(m_goals_dropped));
    std::vector<std::uint32_t> a;
    std::uint64_t given_up = 0;
    std::uint64_t given_up_sum = 0;
    for (const std::uint32_t d : m_arrival) {
        if (d <= kStopRange) {
            a.push_back(d);
        } else {
            ++given_up;
            given_up_sum += d;
        }
    }
    std::printf("orders given up after failed searches: %llu of %zu, mean %.1f half tiles from the ordered cell\n",
                static_cast<unsigned long long>(given_up), m_arrival.size(),
                given_up != 0 ? static_cast<double>(given_up_sum) / static_cast<double>(given_up) : 0.0);
    std::printf("  of those with the land joining unit and spot (the way search lost it): %llu\n",
                static_cast<unsigned long long>(m_given_up_reachable));
    std::printf("    walled in by units: %llu; a coarse way within 16384 tiles: %llu, only beyond: %llu\n",
                static_cast<unsigned long long>(m_given_up_enclosed), static_cast<unsigned long long>(m_given_up_route),
                static_cast<unsigned long long>(m_given_up_far_route));
    for (const std::string& t : m_given_up_samples) {
        std::printf("    %s\n", t.c_str());
    }
    if (!a.empty()) {
        std::sort(a.begin(), a.end());
        std::uint64_t sum = 0;
        std::size_t exact = 0;
        for (const std::uint32_t d : a) {
            sum += d;
            exact += d == 0 ? 1U : 0U;
        }
        std::printf("arrivals: %zu, on the ordered cell %.1f%%, mean %.2f, p90 %u, max %u half tiles away\n", a.size(),
                    100.0 * static_cast<double>(exact) / static_cast<double>(a.size()),
                    static_cast<double>(sum) / static_cast<double>(a.size()), a[a.size() * 9 / 10], a.back());
    }
}

}  // namespace o1602::tool
