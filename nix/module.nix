{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.spot-vision;
  settingsFormat = pkgs.formats.json { };
in
{
  options.services.spot-vision = {
    enable = lib.mkEnableOption "Spot vision";
    package = lib.mkPackageOption pkgs "spot-vision" { default = null; };
    settings = lib.mkOption {
      type = settingsFormat.type;
      default = { };
      description = "Spot installation settings written to /etc/spot-vision/installation.json.";
    };
  };
  config = lib.mkIf cfg.enable {
    services.spot-vision.settings = {
      schema_version = lib.mkDefault 2;
      backend = lib.mkDefault "cuda";
      nt = {
        enabled = lib.mkDefault true;
        mode = lib.mkDefault "client";
        identity = lib.mkDefault "spot-vision";
      };
      http = {
        bind = lib.mkDefault "0.0.0.0";
        port = lib.mkDefault 5800;
        hostnames = lib.mkDefault [ "spot.local" ];
      };
    };
    users.groups.spot-vision = { };
    users.users.spot-vision = {
      isSystemUser = true;
      group = "spot-vision";
      extraGroups = [
        "video"
        "render"
      ];
    };
    environment.etc."spot-vision/installation.json".source =
      settingsFormat.generate "spot-vision.json" cfg.settings;
    environment.systemPackages = [
      cfg.package
      pkgs.networkmanager
      pkgs.iproute2
      pkgs.v4l-utils
    ];
    networking.networkmanager.enable = true;
    networking.firewall.allowedTCPPorts = [ cfg.settings.http.port ];
    services.avahi = {
      enable = true;
      hostName = "spot";
      openFirewall = true;
      publish = {
        enable = true;
        addresses = true;
      };
      extraServiceFiles.spot = ''
        <?xml version="1.0" standalone='no'?>
        <!DOCTYPE service-group SYSTEM "avahi-service.dtd">
        <service-group><name replace-wildcards="yes">Spot on %h</name><service>
        <type>_http._tcp</type><port>${toString cfg.settings.http.port}</port><txt-record>path=/</txt-record>
        </service></service-group>
      '';
    };
    systemd.services.spot-vision = {
      description = "Team 581 Spot Vision";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      path = [
        pkgs.iproute2
        pkgs.v4l-utils
      ];
      environment = {
        PYTHONUNBUFFERED = "1";
      }
      // lib.optionalAttrs (config.system.configurationRevision != null) {
        SPOT_CONFIGURATION_REVISION = config.system.configurationRevision;
      };
      unitConfig = {
        StartLimitIntervalSec = 60;
        StartLimitBurst = 5;
      };
      serviceConfig = {
        Type = "notify";
        User = "spot-vision";
        Group = "spot-vision";
        SupplementaryGroups = [
          "video"
          "render"
        ];
        ExecStart = "${cfg.package}/bin/spot-vision --json-logs run --installation /etc/spot-vision/installation.json";
        Restart = "on-failure";
        RestartSec = 1;
        WatchdogSec = 15;
        NotifyAccess = "main";
        StateDirectory = "spot-vision";
        StateDirectoryMode = "0750";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        RestrictAddressFamilies = [
          "AF_UNIX"
          "AF_INET"
          "AF_INET6"
          "AF_NETLINK"
        ];
      };
    };
    systemd.sockets.spot-network = {
      description = "Spot Ethernet configuration socket";
      wantedBy = [ "sockets.target" ];
      listenStreams = [ "/run/spot-network.sock" ];
      socketConfig = {
        SocketUser = "root";
        SocketGroup = "spot-vision";
        SocketMode = "0660";
        RemoveOnStop = true;
      };
    };
    systemd.services.spot-network = {
      description = "Spot Ethernet bridge configuration helper";
      requires = [
        "NetworkManager.service"
        "NetworkManager-ensure-profiles.service"
      ];
      after = [
        "NetworkManager.service"
        "NetworkManager-ensure-profiles.service"
      ];
      path = [
        pkgs.networkmanager
        pkgs.systemd
        pkgs.iproute2
      ];
      serviceConfig = {
        ExecStart = "${pkgs.python312}/bin/python ${../apps/vision/src/spot_vision/networking.py}";
        Restart = "on-failure";
        RestartSec = 1;
        User = "root";
        Group = "root";
        StateDirectory = "spot-network";
        StateDirectoryMode = "0700";
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        RestrictAddressFamilies = [
          "AF_UNIX"
          "AF_NETLINK"
        ];
        CapabilityBoundingSet = "";
      };
    };
  };
}
