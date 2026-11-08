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
    pkgs.v4l-utils
  ];
  services.spot-vision = {
    enable = true;
    package = (packageFor pkgs).spot;
    settings.nt.team = 581;
  };
  system.stateVersion = "26.05";
}
