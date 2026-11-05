# Project agent notes

- Keep documentation brief. Prefer executable configuration and CLI help over
  duplicated option lists, implementation summaries, plans, or status reports.
- Canonical guides live in `apps/docs/src/content/docs/`; READMEs should link to
  the published site at <https://spot.frc581.com/> instead of duplicating guides.
- Jetson access and recovery: `apps/docs/src/content/docs/operator/deployment.md`.
- Use `bash tools/jetson-ssh.sh` with the shared maintenance key. Never store
  passwords in this repository.
- Target hardware is an Orin Nano on a Seeed reComputer Robotics J401 carrier.
  Preserve Seeed's firmware-provided device tree; never flash developer-kit firmware.
  Firmware changes are separate from normal NixOS deployments.
