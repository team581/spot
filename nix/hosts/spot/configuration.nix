{
  pkgs,
  packageFor,
  ...
}:
{
  nixpkgs.hostPlatform = "aarch64-linux";
  nixpkgs.config.allowUnfree = true;
  nixpkgs.overlays = [ (final: _: { cudaPackages = final.cudaPackages_12_6; }) ];
  hardware.nvidia-jetpack = {
    enable = true;
    som = "orin-nano";
    carrierBoard = "devkit";
    majorVersion = "6";
    # Firmware updates require a separate, deliberate maintenance operation.
    firmware.autoUpdate = false;
  };
  hardware.graphics.enable = true;
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

  networking.hostName = "spot";
  networking.networkmanager.enable = true;
  # Give the developer kit's built-in Realtek NIC a stable name.
  systemd.network.links."10-spot-ethernet" = {
    matchConfig.Driver = "r8168 r8169";
    linkConfig.Name = "spot0";
  };
  networking.networkmanager.ensureProfiles.profiles.spot-maintenance = {
    connection = {
      id = "Spot maintenance";
      uuid = "58100000-0000-4000-8000-000000000001";
      type = "ethernet";
      interface-name = "spot0";
      autoconnect = true;
      autoconnect-priority = -999;
    };
    ipv4 = {
      method = "manual";
      address1 = "192.168.69.170/24";
      never-default = true;
    };
    ipv6 = {
      method = "link-local";
      never-default = true;
    };
  };
  time.timeZone = "America/Los_Angeles";
  services.timesyncd.enable = true;
  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
      PermitRootLogin = "no";
    };
  };
  users.users.team581 = {
    isNormalUser = true;
    extraGroups = [ "wheel" ];
    openssh.authorizedKeys.keys = [ (builtins.readFile ../../maintenance_ed25519.pub) ];
  };
  security.sudo.wheelNeedsPassword = false;
  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];
  nix.settings.trusted-users = [
    "root"
    "team581"
  ];
  environment.systemPackages = [
    pkgs.git
    pkgs.v4l-utils
  ];
  services.spot-vision = {
    enable = true;
    package = (packageFor pkgs).spot;
    ethernetInterfaces = [ "spot0" ];
    settings.nt.team = 581;
  };
  system.stateVersion = "26.05";
}
