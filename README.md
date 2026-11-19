# Surplife BLE

[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

This integration controls Surplife and MagicHome2 Bluetooth LED lights in Home Assistant.
It supports the MIHEAL DX23012 floor lamp and similar devices that use the IOTBT BLE protocol.
It also supports the IOTBT curtain lights (product `0x00C2`, for example `IOTBT437`) as a light
and as a 20x20 screen for images and GIFs.

## Features

| Capability | Status |
| --- | --- |
| Power on and off | Verified on DX23012 |
| RGB color | Verified on one DX23012 |
| White brightness | Needs hardware retest |
| Overall brightness | Verified on one DX23012 |
| State confirmation | Verified on one DX23012 |
| Curtain lights: power, RGB color, brightness, effects, screen | Verified on one IOTBT437 |
| Net lights 32x16 (product `0x0071`): power, RGB color, effects, screen | Verified on one unit, through an ESPHome Bluetooth proxy |
| Multiple devices | Supported |
| Automatic discovery | Supported |
| Manual setup | Supported |

## Supported devices

- MIHEAL DX23012 floor lamp with the verified IOTBT state signature
- IOTBT curtain lights (product `0x00C2`, 20x20 LEDs, tested as `IOTBT437`)
- IOTBT net lights (product `0x0071`, 32x16 = 512 LEDs, about 3 m x 1.5 m, sold with the Surplife app)

Other `IOTBT` devices can use different commands. An `IOTBT` name alone does not prove compatibility.

## Requirements

- Home Assistant 2024.1 or later
- A Bluetooth adapter (built-in, USB, or an ESPHome Bluetooth proxy)
- A Surplife or MagicHome2 BLE light that uses the IOTBT protocol

## Installation

### Via HACS

1. Add this repository as a custom repository in HACS. Use the Integration type.
2. Install "Surplife BLE" from HACS.
3. Restart Home Assistant.
4. Add the integration through **Settings → Devices and Services → Add Integration**.
5. Select a discovered device from the list. Or enter the address manually.

### Manual

1. Copy the `custom_components/surplife_ble/` folder into your HA `config/custom_components/` directory.
2. Restart Home Assistant.
3. Add the integration through **Settings → Devices and Services → Add Integration**.

## Configuration

Configure the integration through the UI:

1. Go to **Settings → Devices and Services → Add Integration**.
2. Search for "Surplife BLE".
3. Select a discovered device from the list. Or enter the BLE address manually.

> **Tip:** If discovery does not find your device, use a BLE scanner app to find its address.
> The device advertises as `IOTBT` followed by a short string. For example, `IOTBT144`.

## IOTBT net lights (product 0x71, 32x16)

This fork adds the 32x16 net light (512 LEDs, product `0x0071`). It uses the same commands as
the 20x20 curtain below and gets the same entities. The grid size follows the product ID that
the device reports, so pictures and GIFs are scaled to 32x16 and a frame is 1024 bytes. The
device memory holds at most 100 frames (102400 bytes), and a 100-frame upload was accepted.

Verified on one unit on 2026-11-19: power, color, effect 10, uploads of 1, 16, 46, 93 and 100
frames, playback speed, and control from Home Assistant through an ESPHome Bluetooth proxy.
Not verified: the other effect IDs. The vendor manual lists 17 built-in effects.

Everything in the curtain section below applies, with 32x16 in place of 20x20.

**Text.** The `surplife_ble.show_text` service writes text on the net or the curtain. Short
text is shown still and centered, longer text scrolls from right to left. Letters are bold
and 10 LEDs tall by default; `size` can be `small` (7), `medium` (10) or `large` (14, twice
as wide), and `scroll` forces scrolling on or off. The Screen preview shows the whole text as one wide picture.
With `preview_only: true` only the preview changes and nothing is sent to the device.

```yaml
action: surplife_ble.show_text
target:
  entity_id: light.net
data:
  text: BUON NATALE
  color: [255, 200, 0]
  speed: 75
```

**Text controls.** The device page also has a Text box, with Text size, Text scrolling,
Text color and Text bold next to it. Typing a text shows it with those settings, at the
speed of the Animation speed slider. Changing one of those controls redraws the text of the
box. With scrolling on "never" a wide text is made to fit: no bold, narrower letters, two
lines if the size is small or automatic. It scrolls only if it cannot fit. Text color has
twelve colors and Rainbow. The names are translated to Italian.

**Animations.** The Animation selector on the device page draws 37 built-in effects for
the grid of the device and plays them. Patterns, for any grid: sparkling lights (two kinds),
rain, snow, green rain, fire, fireworks, rainbow, color clouds, color fade, Italian flag,
Christmas lights, candy stripes, confetti, falling hearts, starry night, shooting stars,
northern lights, lava, ocean, waves, ripples, pinwheel, checkerboard, disco, bouncing ball
and warm glow. Pictures, from 32x16 up: heart, star, heart and star, Christmas tree, comet,
sleigh, smiley, moon and stars, gift and snowman. The `surplife_ble.show_effect` service
does the same.

**Sequences.** A sequence shows effects and texts one after the other, each for its own
time, and starts again after the last one. Write it in the Sequence text box as one line,
with the steps separated by `;`, then turn on the Sequence running switch:

```text
heart 30s; BUON NATALE 1m; rain; fireworks 45s
```

- A step that is an effect name (English or Italian, any case) shows that effect.
- Anything else is a text, shown with the current text settings. Put it in quotes if the
  word is also an effect name.
- A time is a number followed by `s` or `m` at the end of the step. Without one a step
  lasts 60 seconds. A plain number is part of the text, so `AUGURI 2027` is a text.
- `random` (or `casuale`) is a step that shows a different built-in effect every time.

The `surplife_ble.play_sequence` service takes the same line, or a list of steps, and
`surplife_ble.stop_sequence` stops it. Choosing another effect or text, or turning the
light off, stops the sequence too. It does not restart by itself after Home Assistant
restarts.

Home Assistant runs the sequence, so it needs the Bluetooth link at every change of step.
If the link is down, the step is retried. Every step is written to the flash memory of the
device when it starts. How many writes that memory takes is not known, so a step lasts at
least 20 seconds and long steps are kinder to the device: one minute per step is about
1400 writes a day, ten minutes about 140.

**Examples.** [examples/net_32x16](examples/net_32x16) has the same effects as GIF files and
the script that saves them.

## IOTBT curtain lights (product 0xC2)

A curtain is added like any other device. When the integration recognizes it, one device
holds four entities:

| Entity | What it does |
| --- | --- |
| Light | Power, RGB color and brightness, and the effect list. |
| Screen (media player) | Plays images and GIFs on the 20x20 grid. |
| Screen preview (image) | A 200x200 PNG of the first frame of the last upload. |
| Animation speed (number) | Speed of the stored animation, 1 to 100. |

The Screen, preview and speed entities appear only for curtains. Other devices are unchanged.

**Light.** The curtain is RGB only. It has no white channel. It never reports its color or
brightness, so the integration shows the last values it sent and marks the state as assumed.
Power, effect and animation state are read back from the device. Brightness is sent with every
color, effect and animation command. Changing only the brightness resends the current color,
effect or animation.

**Effects.** The effect list holds `Animation (uploaded)` and `Effect 1` to `Effect 100`.
Effect 1 (a color cycle) and effect 10 (a rainbow fill) are verified. The other IDs are not.
The device accepts any ID, so the list length of 100 is a guess. `Animation (uploaded)` plays
the animation stored in the curtain.

**Screen.** The Screen media player supports play, pause, stop, turn on, turn off, play media
and browse media. Browsing shows images only.

- `play_media` takes an image or GIF from a media source, an `http(s)` URL (5 MB at most), or
  a local file in an allowed directory (`allowlist_external_dirs`). Use media type `image/gif`,
  `image/png` and so on, or `url`. The picture is scaled to 20x20, written to the curtain and
  played with mode 1.
- Play loops the stored animation. Pause holds frame 1 (play mode 2). Stop and turn off power
  the curtain off.
- The media title is the name of the last uploaded file.

**Services.** Both services target a curtain light entity.

```yaml
service: surplife_ble.upload_animation
target:
  entity_id: light.curtain
data:
  path: /config/www/animations/fire.gif   # or url: https://example.com/fire.gif
  speed: 50            # 1-100, default 50
  brightness: 100      # 1-100, default 100
  mode: 1              # default 1, see below
  controller_side: right  # optional: left or right, overrides the device option
  flip: false             # optional: overrides the device option
  max_frames: 128      # default and limit 128
  resample: box        # nearest, box or lanczos
```

```yaml
service: surplife_ble.play_animation
target:
  entity_id: light.curtain
data:
  mode: 1
  speed: 50
  brightness: 100
```

| Play mode | Behavior |
| --- | --- |
| 0 | Loop all frames |
| 1 | Loop all frames (constant). This is the default and what the Surplife app sends |
| 2 and up | Hold frame 1 |

**Controller side and orientation.** The curtain has no front or back. The controller box
hangs on the left or the right, and the curtain may hang upside down. Choose **Configure** on
the curtain and set **Controller side (swap left/right)** to the side the controller is on when
you look at the curtain (default `left`), and turn on **Upside down** if it hangs upside down.
Every upload then comes out the right way round: the Screen media player, the
`upload_animation` service and the preview all use these options. With `left`, image column 0
is the string nearest the controller. With `right`, the columns are reversed, so the picture
is mirrored for the curtain and looks upright. `flip` swaps top and bottom. The
`controller_side` and `flip` fields of `upload_animation` are optional. When you give one, it
overrides the device option for that call only. A change in the options takes effect at once.
The preview image always shows the picture as you see it, not the mirrored data.

**Color calibration.** The curtain stores colors in a coarse format and its LEDs differ from
a screen: green is strong, and partly saturated colors look pale. On the same **Configure** page, set
a gain for red, green and blue (0.0 to 2.0) and a gamma (0.2 to 4.0). The
default of 1.0 changes nothing. The calibration applies to the light's colors and to every
image the service or the Screen uploads, and takes effect at once. It does not apply to
effects or the stored animation. Find good values with `ble-rgb curtain calibrate` (see
Development). Tips: use fully saturated colors with one channel at 0 (a good LED orange is
`#FF3C00`, not `#FF7518`), lower the green gain if green is too strong, and raise the gamma to
darken dark tones.

**Limits and flash wear.**

- Every upload writes the curtain's flash memory. The animation then survives power cycles and
  plays without Bluetooth. Do not upload from a fast automation. Use `play_animation` to start
  or restart the stored animation.
- The curtain holds at most 128 frames of 20x20 (102400 bytes). An animation with more frames
  fails with a "too many frames" error. If the device says it is too big, you get a "too big
  for device memory" error.
- Decoding runs in an executor. A 128-frame upload takes about 30 seconds.
- The curtain acknowledges every frame and the integration waits for it before it sends the
  next one. If the Bluetooth link is too weak, the upload stops with an error such as
  "no reply to upload step 'content 98'" instead of losing frames silently. Move the
  Bluetooth adapter or proxy closer and try again.
- The preview is kept in memory. It is empty after a restart until the next upload.
- Needs no extra packages: the integration has its own LZ4 encoder. Pillow comes with Home Assistant.

## Known limitations

**Color state may show as "assumed" on the first command.**

The integration sends a color command and completes a short state query.
The query prepares the lamp for the next color or brightness command.
If confirmation fails, the integration shows an assumed state and requests a background refresh.
A matching poll confirms the state. The assumed state expires after five seconds.

**Use one controller at a time.**

The lamp accepts one active BLE controller at a time.
The integration keeps its connection open for faster commands.
Each connected lamp uses one Bluetooth adapter or proxy connection slot.
Close the vendor app before you control the lamp from Home Assistant.
External changes appear after the assumed state expires and a poll succeeds.

**The first connection can take several seconds.**

The integration keeps a successful connection open.
Tests measured later color and brightness commands at approximately 0.2 to 0.8 seconds.

**Brightness in color mode sends the full color command again.**

The device does not accept a standalone brightness command in color mode.
The integration resends the current color with the new brightness value.

## Troubleshooting

### Device not discovered

- Make sure the light is powered on and within Bluetooth range.
- Make sure your Bluetooth adapter works in Home Assistant. Go to **Settings → System → Bluetooth**.
- Enter the address manually. Use a BLE scanner app to find it.
- The device advertises as `IOTBT` followed by a short string. For example, `IOTBT144`.

### Commands do not work

- Power on and power off should always work. If they do not, make sure the device is connected.
- Color changes work on a verified DX23012 state signature.
- An assumed state means that the lamp did not send a matching notification.
- A background refresh confirms or corrects the state.
- If the light does not respond, power cycle it. Then reload the integration.

### State shows the wrong color after a restart

The integration queries the device state on startup.
If the device is not reachable, the state stays empty until the next successful poll.
Send a color command from Home Assistant to update the display immediately.

## Development

This repository includes a standalone `ble-rgb` command-line tool.
Use it to investigate the protocol and to debug.
For protocol details, GATT characteristics, and command formats, see [docs/CAPTURE_WORKFLOW.md](docs/CAPTURE_WORKFLOW.md).
For the verified DX23012 command findings, see [docs/DX23012_PROTOCOL_FINDINGS.md](docs/DX23012_PROTOCOL_FINDINGS.md).

Install the development environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test,reference]'
```

On macOS, grant Bluetooth access to the terminal application that starts Python.
macOS uses a CoreBluetooth UUID in place of a public Bluetooth MAC address.

### Safe investigation workflow

Use these commands to investigate the protocol safely:

```bash
ble-rgb scan --duration 15 --json captures/scan.json
ble-rgb inspect --device COREBLUETOOTH-UUID --json captures/gatt.json
ble-rgb probe --device COREBLUETOOTH-UUID --allow-probe-write \
  --jsonl captures/probe.jsonl
```

`inspect` does not write to the device.
`probe` sends known state queries, one at a time, after it subscribes to notifications.
Review the output before you use `on`, `off`, `color`, `white`, or `brightness`.

### IOTBT curtain test commands

`ble-rgb curtain` sends hardware-verified commands to an IOTBT curtain light (product `0x00C2`,
for example `IOTBT437`) and prints the decoded `EA 81` state.
It needs `--allow-curtain-c2`, writes only to `FF01`, and never touches the OTA service.
The Home Assistant integration also controls the curtain (see above).
See [docs/IOTBT_CURTAIN_0xC2_FINDINGS.md](docs/IOTBT_CURTAIN_0xC2_FINDINGS.md).

```bash
ble-rgb curtain state --device MAC --allow-curtain-c2
ble-rgb curtain color --device MAC --allow-curtain-c2 --rgb 0,0,255 --brightness 50
ble-rgb curtain effect --device MAC --allow-curtain-c2 --id 10 --speed 80
ble-rgb curtain upload --device MAC --image anim.gif --allow-curtain-c2 --allow-flash-write \
  --speed 50
ble-rgb curtain upload --device MAC --image anim.gif --allow-curtain-c2 --allow-flash-write \
  --controller-side right --speed 50
```

`upload` stores a 20x20 image or animation in the curtain's flash, so it also needs
`--allow-flash-write`. The curtain holds at most 128 frames (102400 bytes) and then plays
them on its own. `--max-frames` defaults to that limit, and a larger upload is rejected by
the device with status `02`. It needs the optional packages: `pip install -e '.[curtain]'`.
The curtain has no front or back, so the controller box can hang on the left or the right.
`--controller-side left|right` (default `left`) says which side of the image it is on.
With `left`, image column 0 is the string nearest the controller. With `right`, the columns
are reversed. `--mirror` flips the choice.

**Color calibration from the command line.** `curtain calibrate` is an interactive session
that shows reference colors on the whole curtain, with the color command only (nothing is
written to flash). Adjust per-channel gains and the gamma, then save them to a JSON file:

```bash
ble-rgb curtain calibrate --device MAC --allow-curtain-c2 --save led.json
ble-rgb curtain color --device MAC --allow-curtain-c2 --rgb 255,60,0 --calibration led.json
ble-rgb curtain upload --device MAC --image anim.gif --allow-curtain-c2 --allow-flash-write \
  --calibration led.json
```

In the session type `next`, `prev`, `color R,G,B`, `r+ r- g+ g- b+ b-`, `gamma+ gamma-`,
`set red_gain 0.8`, `show`, `save [FILE]` or `quit`. Use the same values in the Home Assistant
options. See [docs/IOTBT_CURTAIN_0xC2_FINDINGS.md](docs/IOTBT_CURTAIN_0xC2_FINDINGS.md),
section 13.

For an unknown protocol, the safest method is state-diffing.
Set the lamp to known states with the vendor app.
Probe from the computer at each state.
Then compare the states with `ble-rgb diff`.
For automated capture, use `ble-rgb watch` and `ble-rgb analyze`.
See [docs/CAPTURE_WORKFLOW.md](docs/CAPTURE_WORKFLOW.md) for the full workflow.

## Contributing

Pull requests are welcome.
Run `ruff check` and `pytest` before you submit a pull request.

```bash
ruff check .
pytest
```

## License

[MIT](LICENSE). For protocol research sources, see [NOTICE.md](NOTICE.md).
