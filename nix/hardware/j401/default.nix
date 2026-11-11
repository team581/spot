{ lib, pkgs, ... }:
let
  # Physical USB port labels for Spot's camera `port` selectors, keyed by label, with
  # the udev ID_PATH of the port (without the interface suffix). Read one with
  # `udevadm info -q property /dev/videoN | grep ID_PATH=` while a camera is in it.
  usbPorts = { };
in
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
        cudaPackages = final.cudaPackages_13_2;
        nvidia-jetpack = prev.nvidia-jetpack.overrideScope (
          _: previous: {
            # Firmware is provisioned by Seeed, not built from this NixOS generation.
            otaUtils = previous.otaUtils.override {
              expectedBiosVersion = "39.2.0-gcid-45755727";
            };
          }
        );
      })
    ];

    hardware.nvidia-jetpack = {
      enable = true;
      som = "orin-nano";
      carrierBoard = "seeed-robotics-j401";
      majorVersion = "7";
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

    # Loading this after mounting a USB root disconnects the onboard hub's devices.
    boot.initrd.kernelModules = [ "onboard_usb_hub" ];

    hardware.graphics.enable = true;
    # Preserve the firmware's J401 DTB, including its runtime memory/board fixups.
    hardware.deviceTree.name = lib.mkForce null;

    # These are the policies selected by Seeed's factory image on the 8GB module.
    services.nvfancontrol.enable = true;
    services.nvpmodel.configFile = "${pkgs.nvidia-jetpack.l4t-nvpmodel}/etc/nvpmodel/nvpmodel_p3767_0003_super.conf";

    # /dev/spot/<label> links to the capture node of the camera in each labeled port.
    services.udev.extraRules = lib.concatStrings (
      lib.mapAttrsToList (label: path: ''
        SUBSYSTEM=="video4linux", ATTR{index}=="0", ENV{ID_PATH}=="${path}:*", SYMLINK+="spot/${label}"
      '') usbPorts
    );

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
