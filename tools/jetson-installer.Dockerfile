# syntax=docker/dockerfile:1

FROM nixos/nix@sha256:aca6983e5cefd9936445840fc1c59780f313b3974401305acb56d562ec73f3a0 AS nix

FROM nix AS build
WORKDIR /workspace
ENV XDG_CACHE_HOME=/nix/var/spot-installer-cache
COPY . .
RUN --mount=type=cache,id=spot-installer-nix,target=/nix,from=nix,source=/nix,sharing=locked \
    nix --extra-experimental-features "nix-command flakes" build \
      path:.#packages.aarch64-linux.installer -L \
      --max-jobs 1 --cores 8 --out-link /tmp/spot-installer \
    && mkdir /output \
    && cp -L /tmp/spot-installer/iso/*.iso /output/spot-installer.iso

FROM scratch
COPY --from=build /output/ /
