{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.spot-vision;
in
{
  options.services.spot-vision = {
    enable = lib.mkEnableOption "Spot vision";
    package = lib.mkOption {
      type = lib.types.package;
      description = "The spot-vision service.";
    };
    web = lib.mkOption {
      type = lib.types.package;
      description = "Built dashboard (`dashboard/`) and documentation (`jetson-docs/`).";
    };
    revision = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Short Git commit Spot was built from, shown on the dashboard and sent to robot code.";
    };
    commitTime = lib.mkOption {
      type = lib.types.nullOr lib.types.int;
      default = null;
      description = "Unix time of the commit Spot was built from.";
    };
    team = lib.mkOption {
      type = lib.types.nullOr lib.types.ints.u16;
      default = null;
      description = "Team number used until one is set on the dashboard.";
    };
    ports = lib.mkOption {
      type = lib.types.listOf lib.types.port;
      default = [
        80
        5800
      ];
      description = "HTTP ports for the dashboard and API.";
    };
  };
  config = lib.mkIf cfg.enable {
    users.groups.spot-vision = { };
    users.users.spot-vision = {
      isSystemUser = true;
      group = "spot-vision";
      extraGroups = [
        "video"
        "render"
      ];
    };
    environment.systemPackages = [
      cfg.package
      # The command-line tools, without the Qt GUIs.
      (pkgs.v4l-utils.override { withGUI = false; })
    ];
    # Dashboard and API, plus the Foxglove WebSocket server.
    networking.firewall.allowedTCPPorts = cfg.ports ++ [ 5801 ];
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
        <type>_http._tcp</type><port>${toString (builtins.head cfg.ports)}</port><txt-record>path=/</txt-record>
        </service></service-group>
      '';
    };
    systemd.services.spot-vision = {
      description = "Team 581 Spot Vision";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      # The Jetson multimedia libraries run lsmod.
      path = [ pkgs.kmod ];
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
        ExecStart = lib.escapeShellArgs (
          [
            (lib.getExe cfg.package)
            "run"
            "--state-dir"
            "/var/lib/spot-vision"
            "--web-dir"
            "${cfg.web}/dashboard"
            "--docs-dir"
            "${cfg.web}/jetson-docs"
          ]
          ++ lib.concatMap (port: [
            "--listen"
            "0.0.0.0:${toString port}"
          ]) cfg.ports
          ++ lib.optionals (cfg.revision != null) [
            "--revision"
            cfg.revision
          ]
          ++ lib.optionals (cfg.commitTime != null) [
            "--commit-time"
            (toString cfg.commitTime)
          ]
          ++ lib.optionals (cfg.team != null) [
            "--team"
            (toString cfg.team)
          ]
        );
        Restart = "on-failure";
        RestartSec = 1;
        WatchdogSec = 15;
        NotifyAccess = "main";
        StateDirectory = "spot-vision";
        StateDirectoryMode = "0750";
        AmbientCapabilities = [ "CAP_NET_BIND_SERVICE" ];
        CapabilityBoundingSet = [ "CAP_NET_BIND_SERVICE" ];
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
      description = "Spot Ethernet configuration helper";
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
        ExecStart = "${cfg.package}/bin/spot-network";
        Restart = "on-failure";
        RestartSec = 1;
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
