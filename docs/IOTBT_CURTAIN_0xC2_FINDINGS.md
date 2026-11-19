# IOTBT curtain (product 0xC2) findings

## 1. Device

- Local name: `IOTBT437`.
- Product: "curtain christmas lights", 2 m x 2 m, 400 LEDs (20 x 20).
- Product ID: `0x00C2` (194).
- Same GATT profile as the DX23012: service `FFFF`, write `FF01`, notify `FF02`.

## 2. Advertisement

Service data is `80 07 08 65 f0 1b 14 37 00 c2 0e 03 01 05`.

- The product ID `00 c2` is at service-data bytes 8-9 here. The vendor app counts two UUID
  bytes in front, so it reads them at offsets 10-11.
- The byte after the firmware field is the led version (`0x03` here).
- Service-data UUID: `00005a00-0000-1000-8000-00805f9b34fb`.
- Manufacturer data uses company ID `0x5A00` (23040). It mirrors the EA 81 state bytes:
  - Before any color command: `8023620164f0000000000001019000000102030000000000000000`.
  - After a color command: `8023666e64f0000000000001019000000102030000000000000000`.

## 3. EA 81 bytes 3-4 are the product ID

Bytes 3-4 of an EA 81 state frame are the big-endian product ID, not a mesh address.
Evidence:

1. Surplife 1.6.4 APK, `com/zengge/hagallbjarkan/device/ZGHBDevice.java`. `setDeviceInfo`
   parses the product ID from service-data bytes [10..11]. The same value appears at EA 81
   bytes 3-4.
2. Our curtain advertises `00 c2` and its EA 81 reply has `00 c2` at bytes 3-4. The DX23012
   fixture has `00 aa`, which is product `0x00AA` (170, "Symphony strip" in the
   `8none1/lednetwf_ble` docs).
3. `8none1/lednetwf_ble`, `ai_instructions/DISCOVERIES.md`, section "IOTBT 0xEA 0x81
   status/notification frame", independently resolved the same byte as the product ID.

Byte 5 matches the service-data byte right after the firmware field (`ledVersion` in
`ZGHBDevice`). It is `0x03` on the curtain and `0x09` on the DX23012. This is a hypothesis:
treat it as a led/firmware version, not a layout ID.

## 4. Vendor device database

The ObjectBox `data.mdb` in the APK (db v43) lists product 0xC2 as:

- categoryCode `hc3` (symphony curtain).
- Command protocols: `common`, `common1_0`, `common2_0`, `curtainLightE2`.
- State protocol: `wifibleSymphonyCurtainLight`.
- Panel: `symphony_curtain`.

It is in the same family as products 0xAC and 0xAD (172, 173), documented in
`lednetwf_ble` `protocol_docs/10_device_specific.md`.

## 5. State frames

The `classic-magichome2` query on `FFFF/FF01` → `FF02` returns a repeatable 25-byte state.
The DX23012 state is 27 bytes.

```text
on          : ea810100c20323620164f00000000000010190000001020300
off         : ea810100c20324620164f00000000000010190000001020300
after color: ea810100c20323666e64f00000000000010190000001020300
```

- Byte 6 is power: `0x23` on, `0x24` off.
- Byte 7 is the mode:
  - `0x62` is the initial state (music or program mode; unverified for this product).
  - `0x66` appears after the first `3B A1` color command.
  - `0x67` appears after a built-in effect (scene mode).
  - `0x74` appears after an `E2 09` play command (DIY playback of an uploaded animation).
    Byte 8 is the play mode argument and byte 9 is the speed.
- Bytes 8-9 matter in scene mode: byte 8 is the effect ID and byte 9 is the speed. In the
  other modes they are `01 64` (initial) and `6e 64` (after color). Their meaning there is
  unknown.
- Color and brightness are never reported. See section 7.
- Pushed notifications use ctrl `0x04` and cmd `0x15` or `0x16`. The cmd byte can be
  ignored. The body is the same state frame.
- The DX23012 color layout (bytes 7-13) does not apply. The classifier decodes power only.

Fixtures in `tests/fixtures/protocol_packets.json`, key `iotbt437_curtain_c2`:
`state_hex` (on), `state_off_hex` (off), `state_after_color_hex` (after color) and an
`advertisement` block.

## 6. Verified control

Hardware-verified on 2026-10-17 on IOTBT437 (Linux, BlueZ, bleak, `ble-rgb raw-write` to
`FF01`). The user watched the lamp for each frame.

All frames use the 8-byte transport header: ctrl `00`, sequence, `80 00`, length `000d`,
length+1 `0e`. Then comes cmdId `0x0B` and the 12-byte inner command plus a checksum. The
checksum is the sum of the inner bytes, masked to 8 bits.

### 6.1 Power

Inner: `3b {23|24} 00 00 00 00 00 00 00 32 00 00` plus checksum. The lamp turned off and
on, and state byte 6 followed.

```text
off: 00018000000d0e0b3b240000000000000032000091
on : 00028000000d0e0b3b230000000000000032000090
```

### 6.2 Color and brightness

Inner:

```text
3b a1 <hs_hi> <hs_lo> <bri 0-100> 00 00 00 00 00 00 00 <sum checksum>
```

- `packed = (hue << 7) | saturation`, with hue 0-359 and saturation 0-100.
- `hs_hi` and `hs_lo` are the high and low bytes of `packed`.
- The 7 bytes before the checksum are zero. RGB bytes are not sent.
- This differs from the library's `iotbt_3b_rgb`, which puts RGB bytes at positions 7-9.
  The curtain builders are `color_hsv` and `color_rgb` in `core/curtain_c2.py`.

| Color     | Frame                                                |
|------------|------------------------------------------------------|
| red 100%   | `00038000000d0e0b3ba100646400000000000000a4`         |
| blue 50%   | `00048000000d0e0b3ba178643200000000000000ea`         |
| blue 10%   | `00058000000d0e0b3ba178640a00000000000000c2`         |
| blue 100%  | `00078000000d0e0b3ba1786464000000000000001c`         |
| green 100% | `00088000000d0e0b3ba13c646400000000000000e0`         |
| white (sat 0) | `00098000000d0e0b3ba10000640000000000000040`      |

- Blue 10% was visibly dimmer than blue 50%, so the brightness byte works.
- Blue 100% restored full brightness. It was sent after the ignored standalone `3B 01`
  frame (section 6.3).
- Green 100% (hue 120, `packed = 0x3c64`) showed green.
- White (saturation 0) gives a white-ish RGB mix. The lamp is RGB-only. It has no white or
  CCT channel, and the vendor DB has no `temp_value` function for product 194.

### 6.3 Standalone brightness is ignored

The `bright_value_v2` command did nothing. The lamp stayed dim.

```text
inner: 3b 01 00 00 64 00 64 00 00 00 00 00 04
frame: 00068000000d0e0b3b010000640064000000000004
```

Brightness must be re-sent through the color command, as on the DX23012.

### 6.4 Built-in effects

Hardware-verified on 2026-10-17 on IOTBT437. The user watched the lamp.

```text
E0 02 <preview 00> <effect id> <speed 0-100> <brightness 0-100>
```

- No checksum.
- Transport cmdId is `0x0A`, not `0x0B`.
- This is the `scene_data_v3` template in the vendor `wifi_dp_cmd.json`.
- Effect 1: the whole curtain cycles through one color at a time.
- Effect 10: a multi-color per-pixel pattern (a rainbow fill, bottom to top).
- Other effect IDs are untested.
- The device pushes an EA 81 state notification after the command. Example for effect 10,
  speed 80: `ea810100c20323670a50f00000000000010190000001020300`.

Example frame (effect 10, speed 80, brightness 100, sequence 1):

```text
000180000006070ae002000a5064
```

## 7. State feedback limits

- After the first `3B A1`, EA 81 bytes 7-8 changed from `62 01` to `66 6e`.
- They stayed identical for every later color and brightness change.
- The advertisement manufacturer data mirrors the same bytes.
- So only power (byte 6) is reliable feedback. Color and brightness would need assumed
  state in any integration.

The classifier resolves `state_after_color_hex` as `iotbt-ea81-curtain-c2` and decodes
power only.

## 8. Segmented transport

Payloads that do not fit one ATT write are split. This comes from
`LowerTransportLayerEncoder.generator` (writeVersion 0) in the Surplife APK. It is needed
for image uploads (section 10). On hardware, content payloads above 174 bytes (the 100- and
128-frame rainbow uploads, about 195 bytes per frame, and a replay of the app's 10-frame GIF)
were sent segmented at `maxLen` 182 with the same algorithm and played correctly. Those
runs used the standalone `zg_send.py` and `zg_upload.py` tools, not `ble-rgb curtain`.

- `maxLen = min(MTU, 255)`. The app uses ATT MTU - 4, which is 182 by default.
- If `len(payload) <= maxLen - 8`, send one frame:
  `00 seq 80 00 len16 (len+1) cmdId payload`.
- Otherwise the first frame is
  `40 seq 00 00 total_len16 (maxLen-7) cmdId payload[:maxLen-8]`. It is exactly `maxLen`
  bytes long.
- Later frames are `40 seq idx16 chunk_len chunk`. `idx` starts at 1 and bit 15 is set on
  the last one. A chunk holds at most `maxLen - 5` bytes.
- All segments of one message use the same sequence byte.
- Example: an 807-byte payload at `maxLen` 182 gives 5 frames of 182, 182, 182, 182 and 107
  bytes.

The code is `wrap_magichome_segments` in `core/framing.py`. Tests compare it with the
`frames()` function of the hardware-tested `zg_send.py` tool.

On BlueZ, bleak reports an MTU of 23 until `client._backend._acquire_mtu()` is awaited.
After that it reports 512. Await it before any write longer than 20 bytes. The
`ble-rgb curtain` commands do this.

## 9. Test commands (`ble-rgb curtain`)

`ble-rgb curtain` sends the verified commands above and prints the decoded EA 81 state.
It is a test tool. The Home Assistant integration drives the same device through the same
client code (section 12).

- Every subcommand needs `--device` and `--allow-curtain-c2`.
- It subscribes to FF02 before it writes, and acquires the MTU on BlueZ.
- It writes only to FF01. It never writes to the OTA service (`FE00`, `FF11`).
- After a command it waits for a pushed state (default 1.5 s, `--response-timeout`). If none
  arrives it queries the state.
- `--jsonl PATH` appends a traffic transcript.
- Color and brightness are not reported, so the printed state shows only power, mode,
  effect and speed.

```bash
ble-rgb curtain state  --device MAC --allow-curtain-c2
ble-rgb curtain off    --device MAC --allow-curtain-c2
ble-rgb curtain on     --device MAC --allow-curtain-c2
ble-rgb curtain color  --device MAC --allow-curtain-c2 --rgb 0,0,255 --brightness 50
ble-rgb curtain color  --device MAC --allow-curtain-c2 --hsv 120,100 --brightness 100
ble-rgb curtain effect --device MAC --allow-curtain-c2 --id 10 --speed 80 --brightness 100
ble-rgb curtain play   --device MAC --allow-curtain-c2 --mode 1 --speed 50 --brightness 100
ble-rgb curtain upload --device MAC --allow-curtain-c2 --allow-flash-write \
  --image anim.gif --speed 50
ble-rgb curtain upload --device MAC --allow-curtain-c2 --allow-flash-write \
  --solid "255,0,0;0,0,255" --speed 50
ble-rgb curtain calibrate --device MAC --allow-curtain-c2 --save led.json
ble-rgb curtain color  --device MAC --allow-curtain-c2 --rgb 255,60,0 --calibration led.json
ble-rgb curtain upload --device MAC --allow-curtain-c2 --allow-flash-write \
  --image anim.gif --calibration led.json
```

`upload` writes the animation to device flash, so it also needs `--allow-flash-write`. See
section 10 for its options. `calibrate` and `--calibration` are described in section 13.

The builders are in `core/curtain_c2.py`: `power`, `color_hsv`, `color_rgb`, `effect`,
`state_query`, `play`, `build_upload`, `parse_upload_reply` and `parse_state`. The color
calibration is in `core/calibration.py`.

## 10. Images and animations

Hardware-verified on 2026-10-17 on IOTBT437 (20 x 20). The user watched the lamp. The
protocol was read from the Dart code in the APK (decompiled with blutter) and then tested.
Research notes are in the research workspace (`FINDINGS.md`, sections "BLE file upload of
animations" and "HW VERIFIED 2026-10-17"), not in this repository.

The device never receives a GIF or PNG. The app decodes the image and sends converted
pixel frames.

### 10.1 Pixel format

- Convert RGB to HSV: hue in whole degrees (0-359), saturation and value in whole percent.
- `H = hue * 120 // 360` (7 bits), `S = sat * 15 // 100` (4 bits), `V = val * 31 // 100` (5 bits).
- Each pixel is `((H & 0x7F) << 9) | ((S & 0xF) << 5) | (V & 0x1F)` as a big-endian 16-bit
  value.
- Red is `01 FF`, green `51 FF`, blue `A1 FF`, black `00 00`.
- A frame is 400 pixels, 800 bytes.

### 10.2 Pixel order

The 20 strings hang vertically with 20 LEDs each. A marker frame confirmed the order:

- Buffer index = `column * 20 + row`.
- Row 0 is the TOP of a string (the rod end). The index runs down the string.
- Column 0 is the string nearest the controller. The next column starts at the top again.
  The order is NOT serpentine.
- Pixel 0 is the top of the controller-side string, pixel 19 is its bottom, pixel 20 is the
  top of the next string and pixel 399 is the bottom of the far string.
- The curtain has no front or back. The controller box ends up on the left or the right
  depending on how it is hung, so the left/right choice is part of the mapping.
- For an image pixel (x, y) with y = 0 at the top and the controller on the LEFT of the
  image, the index is `x * 20 + y`. Image column 0 is the controller-side string.
- With the controller on the RIGHT, the columns are reversed: the index is
  `(19 - x) * 20 + y`. Image column 19 is the controller-side string.
- Examples: `(0, 0)` is index 0 with the controller on the left, and `(19, 0)` is index 0
  with the controller on the right.
- In the tool this is `--controller-side left|right` (default `left`). `--mirror` is an
  alias that flips that choice. `--flip` maps y to 19 - y. In the core helpers it is the
  `controller_side` parameter of `pixel_index`, `image_to_frame` and `load_image_frames`.

### 10.3 Upload (`EA 01` to `EA 04`)

Each frame is compressed separately as a raw LZ4 block, with no frame header and no size
prefix. The integration uses its own pure-Python encoder
(`core/lz4_block.py`), so it needs no native package. Any valid LZ4 block works. Vectors
Vectors:

```text
400 x red  01ff -> 2f01ff0200ffffff0950ff01ff01ff
400 x blue a1ff -> 2fa1ff0200ffffff0950ffa1ffa1ff
```

All steps use cmdId `0x0A`, write to `FF01`, and use the segmented transport (section 8,
`maxLen` 182) when a payload is longer than 174 bytes.

| Step | Payload | Reply |
|------|---------|-------|
| Header | `EA 01 01 <u32 BE total bytes = 800 * frames> 00 x16 <u16 BE frames> 00 x15` (40 bytes) | `EA 01 00` |
| Address | `EA 02` and per frame `<u32 BE offset> <u16 BE compressed length>` (6 bytes per frame, no padding) | `EA 02 00` |
| Content | `EA 03 <u16 BE frame number from 1> <lz4 block>` per frame | `EA 03 <u16 frame> 00` |
| End | `EA 04 00` | `EA 04 00` |

- The offset is the sum of the compressed lengths of the earlier frames.
- The header `total` is `800 * frames` (20 * 20 * 2 bytes per frame), not the pixel count.
- The address entries are 6 bytes. There is NO `00 00` padding (see section 10.5).
- The last reply byte is the status. `00` is ok. Status `02` means "too big" (section 10.5).
- Replies arrive as normal notifications (ctrl `0x04`, cmd `0x15`). The body is the payload.
- Every step is acked, content frames included, and the sender waits for the reply before it
  sends the next step. This is the flow control of the upload. The Surplife app does the same.
  A sender that does not wait overruns the device on a weak Bluetooth link. Frames are then
  lost without any error, and the failure only shows as a missing reply to `EA 04`.
- The reply to a content frame carries the frame number. It only counts as the ack for the
  frame just sent when the numbers match. A reply for another frame is logged and the wait
  continues.
- The tool aborts if a step gets no matching reply within 4 s (`--ack-timeout`), or if any
  reply has a non-zero status. The message names the step, for example
  "no reply to upload step 'content 98'". Status `02` gives the message "too big for device
  memory".
- Header byte 2 is `0x01`, which is what the app uses for interactive uploads. It was
  verified persistent. The app's scheduled tasks and scenes use `0x11`; its meaning is
  unknown and the tool does not offer it.

Example vectors (the 3-frame and app vectors are in the tests):

```text
1 frame, red:    header  ea010100000320 00 x16 0001 00 x15
                 address ea0200000000000f
                 content ea0300012f01ff0200ffffff0950ff01ff01ff
                 end     ea0400
2 frames:        header total 1600 (00000640), address ea0200000000000f0000000f000f
3 frames R,G,B:  header total 2400 (00000960)
                 address ea0200000000000f0000000f000f0000001e000f
```

The Surplife app, 10-frame GIF (captured from the phone, 2026-10-17 19:34):

```text
header  ea010100001f40 00 x16 000a 00 x15   (40 bytes, total 8000)
address ea0200000000011100000111011300000224011b0000033f011a00000459010f
        00000568011a0000068201190000079b0125000008c00123000009e3012e   (62 bytes = 2 + 10 * 6)
```

### 10.4 Playback (`E2 09`)

```text
E2 09 <mode> <speed 0-100> <brightness 0-100> 00      cmdId 0x0A
```

- The app plays with `E2 09 01 <speed> <bright> 00` (mode 1). The tool and Home Assistant
  default to mode 1.

| Mode | Behavior |
| --- | --- |
| 0 | Loop all frames |
| 1 | Loop all frames (constant). The default, and what the app sends |
| 2 and up | Hold frame 1 |

- Home Assistant uses mode 1 to play and mode 2 to pause (hold frame 1).
- Speed 0-10 is about 5 s per frame. 50 is about 0.5-1 s per frame. 100 is very fast. These
  are estimates by eye.
- Brightness 1 is dim and 100 is full.
- The device pushes an EA 81 state: byte 7 `0x74` (DIY playback), byte 8 the mode argument
  and byte 9 the speed. Examples: `ea810100c20323740032f00000000000010190000001020300`
  (mode 0, speed 50) and `23 74 01 41` while the app plays a GIF (mode 1, speed 65).
- `E2 09` is the only `E2` command the device honors (section 10.6).

### 10.5 Upload format details, capacity and persistence

The upload format below was confirmed byte by byte against the Surplife app, captured on a
phone (logcat, `HBConnectionImpl writer.bytes`).

- **Address entries are 6 bytes**: `[u32 BE offset][u16 BE compressed length]`, no padding.
  The app's 10-frame address is 62 bytes (2 + 10 * 6). Padding the entries to 8 bytes makes
  the controller read entry 3 as offset `0x000F0000`, decode far past the data, and reboot
  when playback reaches frame 3; uploads of one or two frames still appear to work.
- **Header `total` is `800 * frames`** (bytes per frame times frames), not 400 pixels times
  frames. App captures: 40 frames gave 32000, 10 frames 8000, 16 frames 12800.

With this format, 3 solid frames (R, G, B) with total 2400 and `E2 09 01 0a 01 00` loop
stably. Replaying the app's captured 10-frame GIF through this transport (`maxLen` 182)
also plays and is stable.

Capacity (hardware, 2026-10-17):

- The device rejects a header whose total is above 102400 bytes. The reply is `EA 01 02`
  (status 02, "too big"; the app calls it "out of memory").
- 128 frames (102400 bytes) are accepted and 129 (103200) are rejected. So the maximum is
  128 frames of 20 x 20, which is 100 KiB uncompressed.
- Verified full uploads: 3, 40, 100 and 128 frames (rainbow, about 195 bytes per frame after
  LZ4). A 128-frame upload takes about 30 s. Playback is stable.
- The tool limits `--max-frames` to `102400 // (20 * 20 * 2)` = 128 (the default) and stops on
  status 02.

Persistence: an upload goes to flash. The curtain plays it without a BLE connection, and the
app's GIF keeps playing after the phone's Bluetooth is switched off. Uploads of up to 128
frames play standalone from flash. After a full power cycle (unplugged for about 10 s) the
curtain resumed an uploaded red and blue animation in the same play state, and the EA 81
state read `23 74 00 32`. So the last play command is restored at boot. Treat every upload
as a flash write.

The app's `lz4-java`, python-lz4 and the built-in encoder produce different bytes for
complex frames. The device decodes all of them.

### 10.6 History: live E2 commands are ignored

The live DIY sequence from the app is silently ignored on this device. No ack, no visible
change, state unchanged:

- Bare `E2 31` (size inquiry) with cmdId `0x0A` and `0x0B`, with the curtain on and off.
- `E2 31` wrapped in the `C0 C1 C2 C3 C4 03 02 01 <len16> payload <sum8>` file header.
- Bare FrameInfo `E2 10 01 01 64 14 14 FF`.
- The full live sequence: FrameInfo `E2 10 ...`, NewDiyData `E2 11 01 01 00 01 00` plus 400
  pixels of `01 FF` (807 bytes, 5 segments at `maxLen` 182), PlaySync `E2 17` plus twelve
  `00` bytes. Tried with cmdId `0x0A` and `0x0B`.

The curtain stores animations through the `EA 01..04` file upload instead. Do not scan
opcodes blindly: 7 is net state and 8 is reset.

### 10.7 Tool options

```text
ble-rgb curtain upload --device MAC --allow-curtain-c2 --allow-flash-write
    (--solid R,G,B[;R,G,B...] | --image PATH)
    [--resample nearest|box|lanczos] [--max-frames 128]
    [--controller-side left|right] [--mirror] [--flip]
    [--no-play] [--mode 1] [--speed 50] [--brightness 100] [--ack-timeout 4]
ble-rgb curtain play --device MAC --allow-curtain-c2 [--mode 1] [--speed 50] [--brightness 100]
```

- `--solid` makes one solid frame per color.
- `--image` reads PNG, JPEG, GIF or WebP files with Pillow. Every frame of an animated
  image is used. Frames are composited on black, converted to RGB and stretched to 20 x 20
  with the chosen filter (default `box`).
- `--max-frames` keeps the first N frames and prints a warning. The default and the limit
  are 128, the most the device accepts.
- `--controller-side` says which side of the image the controller box hangs on (default
  `left`). `--mirror` flips that choice. The tool prints the effective side before it
  uploads an image.
- Install the extra packages with `pip install 'surplife-ble[curtain]'`. Pillow is imported
  only for `--image`. LZ4 is built in.
- The tool prints each step and its reply, then the decoded state after the play command.

## 11. OTA channel

The device also exposes a separate firmware update (OTA) service, `FE00`, with `FF11` for
writes and `FF22` for notifications. Firmware update is out of scope. The tools in this
repository never write to that service. A wrong firmware image can brick the device.

## 12. Status in code and Home Assistant

Control is unlocked for `iotbt-ea81-curtain-c2` in `LightClient` and in the Home Assistant
integration. Other unresolved EA 81 layouts (`unresolved-ea81`) and the DX23012 are unchanged.
The `ble-rgb curtain` commands still use their own flags (`--allow-curtain-c2`, and
`--allow-flash-write` for uploads).

A curtain is one device with four entities:

- **Light.** RGB only. The effect list is `Animation (uploaded)` and `Effect 1` to
  `Effect 100`. Effects 1 and 10 are verified. The device echoes any ID from 0 to 255 in its
  state, so the real effect count is unknown and 100 is tentative (`CURTAIN_EFFECT_COUNT`).
  Color and brightness are never reported, so the entity shows the last values sent as
  assumed state. Power, mode, effect and speed come from EA 81 (byte 6 power, byte 7 mode
  `0x66` color, `0x67` effect, `0x74` animation, byte 8 effect ID or play mode, byte 9 speed).
  If the curtain is off, a color, effect or play command sends power on first. This is a
  precaution, because the effect of those commands on an off curtain was not tested.
- **Screen** (media player). Play media uploads an image or GIF (media source, URL or allowed
  local path) and plays it with mode 1. Play sends mode 1, pause sends mode 2, stop and turn
  off send power off, turn on sends power on. State: off when power is off, playing for DIY
  mode with play mode 0 or 1, paused for DIY mode with play mode 2 or more, on otherwise.
- **Screen preview** (image). A 200x200 PNG of the first frame after each upload, scaled with
  nearest-neighbor. It shows the picture as seen, whatever the orientation (section 12.1).
  It lives in memory only.
- **Animation speed** (number, 1-100). It shows byte 9 while the animation plays and the last
  known speed otherwise. Setting it sends `E2 09` with the current play mode (or 1) and the
  last brightness, which also starts the stored animation.

Services `surplife_ble.upload_animation` and `surplife_ble.play_animation` use the same
upload pipeline as the Screen. See the README. Each upload writes the device flash.

The options of the config entry hold the orientation (section 12.1) and the color calibration
(section 13): `red_gain`, `green_gain`, `blue_gain` and `gamma`. The calibration applies to
the light's colors and to every image upload, from the service and from the Screen. It does
not apply to effects, playback or other devices. A change in the options takes effect at
once, without a reload.

### 12.1 Orientation

The curtain has no front or back, so the controller box ends up on the left or the right,
depending on how it is hung (see the pixel order in section 10.2). The options of the config
entry set the default for every upload:

- `controller_side` (`left` or `right`, default `left`): set it to match how the curtain is
  hung. It is the side of the picture the controller box is on when you look at the curtain.
  With `right`, the image columns are reversed (`x -> 19 - x`), so the picture appears upright.
- `flip` (default off, "Upside down"): swap top and bottom (`y -> 19 - y`).

They are used by the Screen media player (`play_media`), the `upload_animation` service and
the preview. In the service, `controller_side` and `flip` are optional fields without
defaults. A field that is given overrides the option for that call only. The code is
`animation.async_upload`, which falls back to the coordinator's options.

The preview is the source picture as the user sees it. It is built by inverting the same
mapping that was used for the upload, so the orientation is not applied a second time and a
mirrored upload has an unmirrored preview.

## 13. Color calibration and LED color tips

The curtain stores a pixel as coarse HSV: hue in 3 degree steps (0-120), saturation 0-15 and
value 0-31. The LEDs also render colors differently from a screen. On hardware (observed by
eye, not measured):

- LED green is strong. A screen's `#00FF00` looks much brighter than the same value in red or
  blue.
- Partly saturated colors look pale. `#FF7518` (a screen orange) looked pale white.
- A good LED orange is `#FF3C00` (hue about 14 degrees, full saturation).
- A good brownish olive green is `#5A7800` (hue about 75 degrees, full saturation, darker).

Tips:

- Use fully saturated colors, with one RGB channel at 0 where you can. Mixed, pastel and
  desaturated colors turn pale or white, because the saturation has only 16 steps and the
  LEDs wash out.
- For orange use hue 10 to 20 degrees (`#FF3C00`), not 25 to 30 degrees (`#FF7518`).
- Make dark colors with a low value, not by lowering saturation. Olive is `#5A7800`.
- If green looks too strong, lower the green gain (for example 0.7).
- Raise gamma above 1.0 to darken dark and mid tones. Lower it to lift them.
- A warm white is `#FFB46E`. Saturation 0 is a white-ish mix of all three LEDs.

### 13.1 The calibration

The calibration is deliberately minimal: a gain per RGB channel and one gamma value. It is
applied to the RGB color before the HSV conversion, for each channel `c`:

```text
c' = clamp(round(255 * min(1, (c / 255) ** gamma * gain)))
```

- Gains are 0.0 to 2.0 and gamma is 0.2 to 4.0. The default is 1.0 for all four, which
  changes nothing: the input comes back byte for byte.
- It is stored as JSON: `{"red_gain": 1.0, "green_gain": 0.7, "blue_gain": 1.0, "gamma": 1.2}`.
  Missing fields keep the default. Unknown fields and out-of-range values are errors.
- It applies to the whole-curtain color command (`color_rgb`, `LightClient.set_rgb` and
  `set_brightness`) and to image and GIF uploads (`build_upload`, before each pixel is
  quantized). It does not apply to `--hsv` colors, effects, playback or the DX23012.
- The whole-curtain color command ignores the value of an RGB color (the brightness is a
  separate field), so gains and gamma change its hue and saturation. In uploads they also
  change the value of each pixel.
- Rounding of exact halves goes to the even number (Python `round`), so 127.5 becomes 128.

### 13.2 `ble-rgb curtain calibrate`

An interactive session that shows reference swatches on the whole curtain. It uses the color
command (`3B A1`, cmdId `0x0B`) only. It never writes to flash and never touches `FE00` or
`FF11`. Turn the curtain on first.

```bash
ble-rgb curtain calibrate --device MAC --allow-curtain-c2 \
  [--calibration start.json] [--save led.json]
```

The swatches are white, red, orange (`#FF3C00`), yellow (`#FFB400`), green, olive
(`#5A7800`), cyan, blue, purple and warm white (`#FFB46E`). The brightness of a swatch is the
value of its calibrated color, so dark colors look dark, as they would in an upload.

| Command | Effect |
| --- | --- |
| `next`, `prev` | Show the next or previous swatch |
| `color R,G,B` | Show any color |
| `r+ r- g+ g- b+ b-` | Change a gain by 0.05 |
| `gamma+ gamma-` | Change the gamma by 0.1 |
| `set NAME VALUE` | Set `red_gain`, `green_gain`, `blue_gain` or `gamma` |
| `show`, `list` | Print the calibration and swatch, or the swatch list |
| `save [FILE]` | Write the JSON file (default: the `--save` file) |
| `help`, `quit` | |

After every change the swatch is sent again. Each line shows the raw and the calibrated RGB,
the hue and saturation of the color command, its packed 16-bit value (`hs16`, hue shifted left
by 7 plus saturation) and the 16-bit HSV pixel (`pixel16`) that an upload would store. A value
that is out of range is refused and the calibration stays as it was. When the session ends
with unsaved changes it prints a warning.

### 13.3 Home Assistant

A curtain entry has an options flow (Configure). It sets the orientation (section 12.1) and
the four calibration values as sliders: gains 0.0 to 2.0 and gamma 0.2 to 4.0 in steps of
0.05. The flow is refused for devices that are known not
to be curtains. Use `ble-rgb curtain calibrate` to find good values first. The preview image
shows the picture as given, before the calibration.

## 14. Open items

- Effect IDs other than 1 and 10 are untested. Scenes in general are untested.
- The meaning of byte 7 (`0x62` before color, `0x66` after color, `0x67` scene, `0x74`
  DIY playback) is only partly known. Bytes 8-9 outside scene and DIY mode (`01 64`,
  `6e 64`) are unexplained.
- The meaning of the other state bytes (10-24) is unknown.
- Header byte 2 `0x11` (scheduled tasks) is unexplored.
- The number of built-in effects is unknown. Only effects 1 and 10 are verified.
- Home Assistant control has been tested against a fake device only, not on a running Home
  Assistant with the real curtain.
- Uploads overwrite flash. Whether there is more than one slot is unknown.
- Byte 5 as a led/firmware version is a hypothesis.
- Color and brightness are never reported, so Home Assistant shows them as assumed state.
- The calibration values for the LED look were chosen by eye. The calibration is not a
  measured color profile, and it has no per-device default.

## 15. Product 0x0071: 32 x 16 net light

Hardware-verified on 2026-11-19 on one unit (512 LEDs, about 3 m x 1.5 m, 10 cm pitch).

- Same GATT profile and the same transport as product 0xC2.
- EA 81 state: `ea810100710623666e64f0000000000001020000000102010071`. Bytes 3-4 are the
  product ID `00 71` and byte 5 is `06`. Bytes 17-18 are `02 00` (512) where the 20 x 20
  curtain has `01 90` (400), so they look like the LED count. This is a hypothesis.
- Power (`3B 23`/`3B 24`, cmdId `0B`), color (`3B A1`), effects (`E0 02`, cmdId `0A`) and
  playback (`E2 09`) work as on 0xC2. Effect 10 shows horizontal bands moving down.
- Grid: 32 columns of 16 LEDs. Buffer index = `column * 16 + row`, row 0 at the top, column 0
  nearest the controller, not serpentine. A frame is 512 pixels, 1024 bytes.
- Upload: the header total is `1024 * frames`. One-frame header:
  `ea 01 01 00 00 04 00`, 16 zero bytes, `00 01`, 15 zero bytes. Uploads of 1, 16, 46, 93 and
  100 frames were acknowledged and played. 100 frames is the 102400-byte limit.
- The code keeps the grid per product in `curtain_c2.GRIDS`. `LightClient.curtain_grid` reads
  the product ID from the resolved state.
