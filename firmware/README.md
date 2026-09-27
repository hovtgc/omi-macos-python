# Motion firmware for the Omi CV 1

Stock Omi firmware compiles the pendant's LSM6DS3TR-C (6-axis accelerometer + gyroscope) out, and the
upstream motion code could not have worked if switched on. `accel-stream.patch` fixes that against
[BasedHardware/omi](https://github.com/BasedHardware/omi) at `771fe01` (firmware 3.0.21):

1. `omi.conf`: `CONFIG_OMI_ENABLE_ACCELEROMETER=y`.
2. `CMakeLists.txt`: compile `accel.c` when that option is on (upstream never did, so it failed to link).
3. `accel.c`:
   - start streaming when a client subscribes and stop when it unsubscribes (upstream never scheduled its first read),
   - stop driving gpio1 8, a dev-kit pin (the board powers the sensor with its own regulator on gpio1 12),
   - stream 50 Hz instead of 1 Hz, as 12 bytes: six little-endian int16 (ax ay az gx gy gz) at 0.122 mg and 17.5 mdps per LSB,
   - fall back to 12.5 Hz with the gyro off when nobody listens.

Service `32403790-0000-1000-7450-bf445e5829a2`, characteristic `…3791` (read, notify). The feature
bitmask at `19b10021` gains bit 1 (motion). The Omi phone app's fall detection reads the upstream
48-byte format and ignores these packets; Sideband reads both.

## Use the prebuilt release

`sideband firmware --install motion` downloads
`Sideband_Omi_CV1_motion_3.0.21.1.zip` from this repo's releases, checks its pinned SHA-256
(`3ca5f664…0df3`), and flashes only with `--yes-flash`. See ONBOARDING.md step 7 for the safe order
(official rehearsal first) and the risk: the bootloader has no rollback.

The release zip's app-core image hash is `d0857ecf…6213`, the image verified on a real Omi CV 1:
it booted, served the motion service, streamed 45 notifications/s of 12 bytes, and read 1 g at rest.

## Build it yourself

About 4 GB of Nordic tools and an hour on a typical connection.

```sh
# Nordic toolchain (nrfutil, then nRF Connect SDK 2.9.0)
curl -fsSL -o ~/.local/bin/nrfutil https://files.nordicsemi.com/artifactory/swtools/external/nrfutil/executables/universal-apple-darwin/nrfutil
chmod +x ~/.local/bin/nrfutil
nrfutil install toolchain-manager
nrfutil toolchain-manager install --ncs-version v2.9.0

# Omi firmware at the patch's base, plus the SDK
git clone --filter=blob:none https://github.com/BasedHardware/omi.git && cd omi && git checkout 771fe01
git apply /path/to/omi-macos-python/firmware/accel-stream.patch
cd omi/firmware && mkdir -p v2.9.0 && cd v2.9.0
nrfutil toolchain-manager launch --ncs-version v2.9.0 -- sh -c 'west init -m https://github.com/nrfconnect/sdk-nrf --mr v2.9.0 && west update --narrow -o=--depth=1'

# Build (from omi/firmware/v2.9.0)
cp ../omi/omi.conf ../omi/prj.conf
nrfutil toolchain-manager launch --ncs-version v2.9.0 -- west build -p always -d ../build-motion -b omi/nrf5340/cpuapp ../omi --sysbuild -- -DBOARD_ROOT="$(cd .. && pwd)"

# Inspect, then install (dry run without --yes-flash)
sideband firmware --update ../build-motion/dfu_application.zip
```

Builds are signed with Omi's public MCUboot key from the repo (`bootloader/mcuboot/root-rsa-2048.pem`),
the same key the official releases use, so the pendant accepts them.

Firmware license: the Omi firmware is MIT (BasedHardware/omi); the patch is MIT like this repo.
