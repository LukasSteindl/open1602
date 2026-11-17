// SPDX-License-Identifier: GPL-3.0-or-later
//
// bench --army N: puts N land units at every player's first warehouse, sends them about the
// islands in groups, and measures how they walk (F17: soldiers stuttering in a late game).
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "o1602/assets/figure_table.hpp"
#include "o1602/sim/land_paths.hpp"
#include "o1602/sim/simulation.hpp"
#include "o1602/sim/world.hpp"

namespace o1602::tool {

class ArmyBench {
public:
    /// Puts `per_player` units next to each settler player's first warehouse; returns how many.
    std::size_t place(sim::Simulation& simulation, const sim::World& world, const assets::FigureTable& figures,
                      std::size_t per_player, std::uint64_t seed);
    /// Every 30 s of game time: new orders for the groups (some march across their island, some to
    /// another city on it, the rest stand).
    void order(sim::Simulation& simulation, const sim::World& world, std::uint64_t tick);
    /// Around each tick: what every soldier did in it.
    void before_tick(const sim::World& world);
    void after_tick(const sim::World& world, const sim::Simulation& simulation);
    /// Prints the walking figures of the measurement.
    void print() const;

private:
    struct Before {
        std::int32_t x = 0;
        std::int32_t y = 0;
        bool on_way = false;
        std::uint8_t direction = 0;
        std::int32_t moved = 0;     ///< way in the tick before, 1/4096 tile (0: stood)
        std::uint32_t stall = 0;    ///< ticks in a row on the way without moving
        std::uint32_t waiting = 0;  ///< ticks in a row with an order but no way
    };
    struct Goal {
        std::int32_t x2 = 0;  ///< ordered half-tile cell
        std::int32_t y2 = 0;
        bool open = false;  ///< not arrived yet
    };
    std::uint64_t next_random();
    bool walled_in_by_units(const sim::Simulation& simulation, const sim::World& world, const sim::Soldier& s) const;
    bool walkable(const sim::Simulation& simulation, std::int32_t x, std::int32_t y) const;
    /// Whether soldiers can walk from world tile (ax, ay) to (bx, by) on island `island` (tiles
    /// joined by their sides, units and closed gates left out).
    bool connected(const sim::Simulation& simulation, const sim::World& world, std::uint16_t island, std::int32_t ax,
                   std::int32_t ay, std::int32_t bx, std::int32_t by);

    std::uint64_t m_random = 0;
    std::vector<std::vector<std::uint32_t>> m_units;  ///< per player, the units placed
    std::unordered_map<std::uint32_t, Before> m_before;
    std::unordered_map<std::uint32_t, Goal> m_goals;
    std::uint32_t m_round = 0;

    // Totals.
    std::uint64_t m_ticks = 0;
    std::uint64_t m_on_way_ticks = 0;         ///< unit-ticks on the way to somewhere
    std::uint64_t m_stall_ticks = 0;          ///< ... of those, standing although the way goes on
    std::uint64_t m_walk_in_place_ticks = 0;  ///< walk animation without moving
    std::uint32_t m_longest_stall = 0;        ///< ticks
    std::uint64_t m_tempo_changes = 0;        ///< way per tick changed by more than an eighth, same direction
    std::uint64_t m_moving_pairs = 0;         ///< ticks in which a unit moved in this and the last tick
    std::uint64_t m_turns = 0;                ///< direction changes while walking
    std::uint64_t m_cells_walked = 0;         ///< half tiles
    std::vector<std::uint32_t> m_arrival;     ///< half tiles from the ordered cell when the way ended
    std::uint64_t m_goals_dropped = 0;
    std::unordered_map<std::uint16_t, std::vector<std::uint32_t>> m_regions;  ///< per island, tile -> land region
    std::uint64_t m_given_up_reachable = 0;  ///< orders given up although the land joins unit and spot
    std::uint64_t m_given_up_enclosed = 0;   ///< ... of those, walled in by other units
    std::uint64_t m_given_up_route = 0;      ///< ... a coarse way within the route's tiles
    std::uint64_t m_given_up_far_route = 0;  ///< ... a coarse way only with more tiles
    std::vector<std::string> m_given_up_samples;
    sim::LandPlanner m_route_planner;
    std::uint64_t m_wait_ticks = 0;
    std::uint32_t m_longest_wait = 0;
    std::uint64_t m_long_waits = 0;
    std::string m_longest_wait_unit;
    std::uint64_t m_orders = 0;
    std::uint64_t m_orders_accepted = 0;
    std::uint64_t m_searches = 0;
    std::uint64_t m_cells = 0;
    std::uint64_t m_turned_away = 0;
    std::uint64_t m_turned_away_walking = 0;
    std::uint32_t m_max_turned_away = 0;
    std::uint64_t m_ticks_budget_used_up = 0;  ///< ticks with every search of the budget taken
};

}  // namespace o1602::tool
