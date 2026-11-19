"""Constants for the Surplife BLE integration."""

from datetime import timedelta

DOMAIN = "surplife_ble"
# The media_player, image and number platforms add entities only for the IOTBT curtain.
PLATFORMS = ["light", "media_player", "image", "number", "text", "select", "switch"]
UPDATE_INTERVAL = timedelta(seconds=15)

# Options of the config entry: color calibration for the IOTBT curtain (see
# core/calibration.py). The defaults are the identity.
CONF_RED_GAIN = "red_gain"
CONF_GREEN_GAIN = "green_gain"
CONF_BLUE_GAIN = "blue_gain"
CONF_GAMMA = "gamma"
CALIBRATION_OPTIONS = (CONF_RED_GAIN, CONF_GREEN_GAIN, CONF_BLUE_GAIN, CONF_GAMMA)

# Options of the config entry: how the IOTBT curtain is hung. The controller box can be on
# the left or the right of the picture, and the curtain may hang upside down. Used as the
# default for every image upload.
CONF_CONTROLLER_SIDE = "controller_side"
CONF_FLIP = "flip"
ORIENTATION_OPTIONS = (CONF_CONTROLLER_SIDE, CONF_FLIP)
