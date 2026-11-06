# Spot cheatsheet

Run from the repo root. The Jetson is `192.168.69.170`; set `SPOT_HOST=<ip>` for another address.

Open a shell on the Jetson with the shared maintenance key:

```sh
mise run jetson:ssh
```

Build on the Jetson (downloads go through the Mac) and run it until the next reboot:

```sh
mise run jetson:remote-deploy
```

Same, but also make it the boot default:

```sh
mise run jetson:remote-deploy switch
```

On the test unit, prefix either deploy with `SPOT_CONFIG=spot-test`.
The script is `tools/jetson-remote-deploy.sh`; `--help` lists its options.
