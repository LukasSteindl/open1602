# SPDX-License-Identifier: GPL-3.0-or-later
# o1602-ctl: gives commands to a game started with --control PORT (engine/app/src/control_server.hpp).

add_executable(o1602-ctl main.cpp)
if(WIN32)
    target_link_libraries(o1602-ctl PRIVATE ws2_32)
endif()
o1602_set_warnings(o1602-ctl)
o1602_utf8_manifest(o1602-ctl)
o1602_set_output_dir(o1602-ctl)
