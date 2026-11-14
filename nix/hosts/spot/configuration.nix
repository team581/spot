{
  pkgs,
  packageFor,
  ...
}:
{
  imports = [
    ../../hardware/j401
    ./maintenance.nix
  ];
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
  # The installer partitions and formats the NVMe drive from this layout.
  disko.devices.disk.main = {
    device = "/dev/nvme0n1";
    type = "disk";
    content = {
      type = "gpt";
      partitions = {
        ESP = {
          type = "EF00";
          size = "1G";
          content = {
            type = "filesystem";
            format = "vfat";
            extraArgs = [
              "-F"
              "32"
              "-n"
              "SPOT_EFI"
            ];
            mountpoint = "/boot";
          };
        };
        root = {
          size = "100%";
          content = {
            type = "filesystem";
            format = "ext4";
            extraArgs = [
              "-L"
              "SPOT_ROOT"
            ];
            mountpoint = "/";
          };
        };
      };
    };
  };
  # Mount by filesystem label, which Jetsons installed before disko also have.
  disko.enableConfig = false;
  fileSystems."/" = {
    device = "/dev/disk/by-label/SPOT_ROOT";
    fsType = "ext4";
  };
  fileSystems."/boot" = {
    device = "/dev/disk/by-label/SPOT_EFI";
    fsType = "vfat";
  };

  documentation.nixos.enable = false;
  environment.systemPackages = [
    pkgs.git
    pkgs.usbutils
  ];
  services.spot-vision = {
    enable = true;
    package = (packageFor pkgs).spot;
    web = (packageFor pkgs).web;
    team = 581;
  };
  system.stateVersion = "26.05";
}
