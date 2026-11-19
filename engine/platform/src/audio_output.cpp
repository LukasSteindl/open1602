// SPDX-License-Identifier: GPL-3.0-or-later
#include "o1602/platform/audio_output.hpp"

#include <SDL3/SDL.h>

#include "o1602/platform/window.hpp"

namespace o1602::platform {

core::Result<std::unique_ptr<AudioOutput>> AudioOutput::open(std::uint32_t rate) {
    // A small device buffer (about 12 ms at 44.1 kHz): the game keeps its own short queue ahead of
    // it, and a large one would only delay every sound. Drivers may round it up.
    SDL_SetHint(SDL_HINT_AUDIO_DEVICE_SAMPLE_FRAMES, "512");
    if (!SDL_InitSubSystem(SDL_INIT_AUDIO)) {
        return sdl_error("SDL_InitSubSystem(audio)");
    }
    SDL_AudioSpec spec{};
    spec.format = SDL_AUDIO_S16;
    spec.channels = 2;
    spec.freq = static_cast<int>(rate);
    // O1602_AUDIO_DEVICE=<part of a name>: play on that output instead of the default one (a
    // stream that captures the game's sound while the person at the computer hears nothing).
    SDL_AudioDeviceID device = SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK;
    if (const char* wanted = SDL_getenv("O1602_AUDIO_DEVICE"); wanted != nullptr && *wanted != '\0') {
        int count = 0;
        if (SDL_AudioDeviceID* ids = SDL_GetAudioPlaybackDevices(&count); ids != nullptr) {
            for (int i = 0; i < count; ++i) {
                const char* name = SDL_GetAudioDeviceName(ids[i]);
                if (name != nullptr && SDL_strcasestr(name, wanted) != nullptr) {
                    device = ids[i];
                    break;
                }
            }
            SDL_free(ids);
        }
        SDL_Log("audio: O1602_AUDIO_DEVICE=%s -> %s", wanted,
                device == SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK ? "not found, default output" : SDL_GetAudioDeviceName(device));
    }
    SDL_AudioStream* stream = SDL_OpenAudioDeviceStream(device, &spec, nullptr, nullptr);
    if (stream == nullptr) {
        auto error = sdl_error("SDL_OpenAudioDeviceStream");
        SDL_QuitSubSystem(SDL_INIT_AUDIO);
        return error;
    }
    SDL_ResumeAudioStreamDevice(stream);
    return std::unique_ptr<AudioOutput>(new AudioOutput(stream, rate));
}

AudioOutput::~AudioOutput() {
    SDL_DestroyAudioStream(m_stream);
    SDL_QuitSubSystem(SDL_INIT_AUDIO);
}

std::size_t AudioOutput::queued_frames() const noexcept {
    const int bytes = SDL_GetAudioStreamQueued(m_stream);
    return bytes > 0 ? static_cast<std::size_t>(bytes) / 4 : 0;
}

void AudioOutput::push(const std::int16_t* frames, std::size_t count) {
    if (count != 0) {
        SDL_PutAudioStreamData(m_stream, frames, static_cast<int>(count * 4));
    }
}

}  // namespace o1602::platform
