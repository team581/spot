{ lib, pkgs, ... }:
{
  # jetpack-nixos explicitly supports extending its carrier-board enum.
  options.hardware.nvidia-jetpack.carrierBoard = lib.mkOption {
    type = lib.types.enum [ "seeed-robotics-j401" ];
  };

  config = {
    nixpkgs.hostPlatform = "aarch64-linux";
    nixpkgs.config.allowUnfree = true;
    nixpkgs.overlays = [
      (final: prev: {
        cudaPackages = final.cudaPackages_12_6.overrideScope (_: cudaPrev: {
          # Backport NVIDIA/cccl e5269a0: infer discarded ReduceByKey outputs from the input.
          cuda_cccl = cudaPrev.cuda_cccl.overrideAttrs (old: {
            patches = (old.patches or [ ]) ++ [ ./cccl-thrust-discard.patch ];
          });
        });
        nvidia-jetpack = prev.nvidia-jetpack.overrideScope (
          _: previous: {
            # Firmware is provisioned by Seeed, not built from this NixOS generation.
            otaUtils = previous.otaUtils.override {
              expectedBiosVersion = "36.4.3-gcid-38968081";
            };
          }
        );
      })
    ];

    hardware.nvidia-jetpack = {
      enable = true;
      som = "orin-nano";
      carrierBoard = "seeed-robotics-j401";
      majorVersion = "6";
      super = true;
      # Spot requests CUDA explicitly; keep other packages on the binary cache.
      configureCuda = false;
      # Retain Seeed's board-specific QSPI firmware and pinmux configuration.
      firmware.autoUpdate = lib.mkForce false;
      flashScriptOverrides = {
        targetBoard = lib.mkForce null;
        configFileName = throw "J401 firmware flashing is not supported by this flake; use Seeed's Robotics J401 BSP.";
      };
    };

    boot.kernelParams = [ "panic=10" "boot.panic_on_fail" ];

    hardware.graphics.enable = true;
    # Preserve the firmware's J401 DTB, including its runtime memory/board fixups.
    hardware.deviceTree.name = lib.mkForce "spot-j401.dtb";
    hardware.deviceTree.dtbSource = lib.mkForce (pkgs.runCommand "spot-j401-factory-device-tree" {
      nativeBuildInputs = [ pkgs.dtc ];
    } ''
      mkdir -p $out
      fdtoverlay -i ${./device-tree/base.dtb} -o $out/spot-j401.dtb \
        ${./device-tree/header.dtbo} ${./device-tree/gmsl.dtbo}
    '');

    # These are the policies selected by Seeed's factory image on the 8GB module.
    services.nvfancontrol.enable = true;
    services.nvpmodel.configFile = "${pkgs.nvidia-jetpack.l4t-nvpmodel}/etc/nvpmodel/nvpmodel_p3767_0003_super.conf";

    # Match physical ports, not the shared driver or a per-device MAC address.
    systemd.network.links = {
      "10-spot-ethernet" = {
        matchConfig.Path = "platform-140a0000.pcie-pci-0008:01:00.0";
        linkConfig.Name = "spot0";
      };
      "10-spot-secondary-ethernet" = {
        matchConfig.Path = "platform-141e0000.pcie-pci-0007:01:00.0";
        linkConfig.Name = "spot1";
      };
    };
  };
}
