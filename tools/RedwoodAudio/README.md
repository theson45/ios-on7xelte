# RedwoodAudio.driver (J7 Prime)

The HAL plug-in (AudioServerPlugIn) that gives iOS 16's audio server (mediaserverd) a speaker on
the J7 Prime. It presents the devices the iPhone X's VirtualAudio expects ("Speaker", "Hawking",
"Actuator", "Codec") and writes the mixed 48 kHz 16-bit stereo frames to `/dev/redwood-audio`
(xnu patch 0158, `bsd/dev/on7xelte_audio.c`), which feeds them to I2S0 -> s1402x -> cod3026x.

The code is HackiOS user space (<https://github.com/oosexgang/hackios-xnu-userland>, MIT License,
Copyright (c) 2026 OOSEX GANG; see LICENSE), as ios-b0s (taimen) carries it in
`tools/phone/RedwoodAudio`. Only the manufacturer string differs from the taimen copy.

`.github/workflows/root-tweak.yml` builds it with the iPhoneOS SDK (ad hoc signed MH_BUNDLE) and
`tools/sweet-root-tweaks.py --hal-plugin DIR` installs it as
`/System/Library/Audio/Plug-Ins/HAL/RedwoodAudio.driver` and leaves VirtualAudio.plugin in place
(without these devices VirtualAudio crashed mediaserverd, which is why it was moved aside).
