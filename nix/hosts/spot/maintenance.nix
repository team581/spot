{
  networking.hostName = "spot";
  networking.networkmanager.enable = true;
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
}
