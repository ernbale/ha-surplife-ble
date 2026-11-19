# Example animations for the 32 x 16 net light

Animations drawn at 32 x 16, one image pixel per LED, for the net light with product ID
`0x0071`. They are original and are drawn in code by `core/effects.py`, so the Animation
selector of the device shows the same ones without any file.

![Preview](preview.png)

| File | Frames | Name in the Animation selector |
| --- | --- | --- |
| `aurora.gif` | 32 | Northern lights |
| `bouncing_ball.gif` | 58 | Bouncing ball |
| `candy_stripes.gif` | 8 | Candy stripes |
| `checkerboard.gif` | 24 | Checkerboard |
| `christmas_lights.gif` | 4 | Christmas lights |
| `color_fade.gif` | 36 | Color fade |
| `comet.gif` | 48 | Comet |
| `confetti.gif` | 19 | Confetti |
| `disco.gif` | 16 | Disco |
| `fire.gif` | 24 | Fire |
| `fireworks.gif` | 36 | Fireworks |
| `flag_italy.gif` | 16 | Italian flag |
| `gift.gif` | 4 | Gift |
| `heart.gif` | 4 | Heart |
| `heart_and_star.gif` | 6 | Heart and star |
| `hearts_rain.gif` | 22 | Falling hearts |
| `lava.gif` | 32 | Lava |
| `matrix.gif` | 26 | Green rain |
| `meteors.gif` | 28 | Shooting stars |
| `moon.gif` | 4 | Moon and stars |
| `ocean.gif` | 32 | Ocean |
| `pinwheel.gif` | 24 | Pinwheel |
| `plasma.gif` | 32 | Color clouds |
| `rain.gif` | 23 | Rain |
| `rainbow.gif` | 24 | Rainbow |
| `ripples.gif` | 24 | Ripples |
| `scrolling_text.gif` | 100 | Scrolling text (the Text box does this for any text) |
| `sleigh.gif` | 59 | Sleigh |
| `smiley.gif` | 3 | Smiley |
| `snow.gif` | 16 | Snow |
| `snowman.gif` | 16 | Snowman |
| `sparkle.gif` | 48 | Sparkling lights |
| `sparkle_gold.gif` | 48 | Sparkling lights, white and gold |
| `star.gif` | 6 | Star |
| `starry_night.gif` | 48 | Starry night |
| `tree.gif` | 8 | Christmas tree |
| `warm_glow.gif` | 24 | Warm glow |
| `waves.gif` | 24 | Waves |

## Use them in Home Assistant

Copy the files to a folder Home Assistant may read, for example `/config/www/net/`, then:

```yaml
action: surplife_ble.upload_animation
target:
  entity_id: light.net
data:
  path: /config/www/net/heart.gif
  speed: 55
  resample: nearest
```

`resample: nearest` keeps the pixels as drawn. Speeds that look right: 45 for the tree, 55
for the heart, the star and the snow, 65 to 80 for the others.

## What reads well on this net

The LEDs are 10 cm apart, so from a few meters the eye sees dots, not a picture. One or two
big filled shapes in a few saturated colors read best. One-pixel lines, small details and
dark colors are lost. In testing, the heart and the star were clear at 2 m, and the tree
and the sleigh were only just recognizable.

## Make your own

`make_examples.py` builds all files. Run it from the repository root. It needs Pillow.

```bash
python examples/net_32x16/make_examples.py [output directory] [scrolling text]
```
