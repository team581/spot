let
  interface = "br0";
  maintenanceAddress = "192.168.69.170/24";
  defaultConnection = "58100000-0000-4000-8000-000000000001";
in
{
  networking.hostName = "spot";
  networking.networkmanager.enable = true;
  networking.networkmanager.ensureProfiles.profiles = {
    spot-maintenance = {
      connection = {
        id = "Spot maintenance";
        uuid = defaultConnection;
        type = "bridge";
        interface-name = interface;
        stable-id = "spot-ethernet";
        autoconnect = true;
        autoconnect-ports = 1;
        autoconnect-priority = 0;
      };
      bridge.stp = true;
      ethernet.cloned-mac-address = "stable";
      ipv4 = {
        method = "auto";
        may-fail = true;
        address1 = maintenanceAddress;
        never-default = false;
        ignore-auto-dns = false;
      };
      ipv6 = {
        method = "link-local";
        never-default = true;
      };
    };
    spot-port-0 = {
      connection = {
        id = "Spot Ethernet port 0";
        uuid = "58100000-0000-4000-8000-000000000002";
        type = "ethernet";
        interface-name = "spot0";
        controller = interface;
        port-type = "bridge";
        autoconnect = true;
      };
    };
    spot-port-1 = {
      connection = {
        id = "Spot Ethernet port 1";
        uuid = "58100000-0000-4000-8000-000000000003";
        type = "ethernet";
        interface-name = "spot1";
        controller = interface;
        port-type = "bridge";
        autoconnect = true;
      };
    };
  };
  environment.etc."spot-vision/network.json".text = builtins.toJSON {
    inherit interface;
    maintenance_address = maintenanceAddress;
    default_connection = defaultConnection;
  };
  services.avahi.allowInterfaces = [ interface ];
  time.timeZone = "America/Los_Angeles";
  services.timesyncd.enable = true;
  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
      PermitRootLogin = "no";
      # Drop vanished clients within ~45 s so stale deploy forwards don't hold ports.
      ClientAliveInterval = 15;
      ClientAliveCountMax = 3;
    };
  };
  users.users.team581 = {
    isNormalUser = true;
    extraGroups = [
      "video"
      "wheel"
    ];
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
