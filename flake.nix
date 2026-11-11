{
  description = "Team 581 Spot vision appliance";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    pnpm2nix = {
      url = "github:mnixry/pnpm2nix-pure";
      flake = false;
    };
    jetpack = {
      url = "github:anduril/jetpack-nixos";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    inputs@{
      self,
      nixpkgs,
      jetpack,
      ...
    }:
    let
      inherit (nixpkgs) lib;
      forSystems = lib.genAttrs [
        "aarch64-linux"
        "x86_64-linux"
        "aarch64-darwin"
      ];
      packageFor = pkgs: import ./nix/packages.nix { inherit inputs pkgs; };
      host = self.nixosConfigurations.spot;
      installerFor =
        system:
        lib.nixosSystem {
          modules = [
            "${nixpkgs}/nixos/modules/installer/cd-dvd/installation-cd-minimal.nix"
            jetpack.nixosModules.default
            self.nixosModules.j401
            ./nix/hosts/spot/maintenance.nix
            (
              { pkgs, ... }:
              {
                nixpkgs.buildPlatform = system;
                hardware.enableAllHardware = lib.mkForce false;
                # Install the bundled system without general-purpose installer payloads.
                boot.supportedFilesystems.zfs = lib.mkForce false;
                system.installer.channel.enable = false;
                documentation.nixos.enable = lib.mkForce false;
                isoImage.storeContents = [ host.config.system.build.toplevel ];
                environment.systemPackages = [
                  (pkgs.writeShellApplication {
                    name = "spot-install";
                    runtimeInputs = [ pkgs.nixos-install ];
                    text = ''
                      exec nixos-install --system ${host.config.system.build.toplevel} \
                        --no-channel-copy --no-root-passwd --option substituters "" "$@"
                    '';
                  })
                ];
              }
            )
          ];
        };
    in
    {
      nixosModules.spot = import ./nix/module.nix;
      nixosModules.j401 = import ./nix/hardware/j401;
      nixosConfigurations.spot = lib.nixosSystem {
        specialArgs = { inherit packageFor; };
        modules = [
          jetpack.nixosModules.default
          self.nixosModules.spot
          ./nix/hosts/spot/configuration.nix
          { system.configurationRevision = self.rev or self.dirtyRev or null; }
        ];
      };
      packages = forSystems (
        system:
        let
          pkgs = if system == "aarch64-linux" then host.pkgs else import nixpkgs { inherit system; };
          packages = packageFor pkgs;
        in
        {
          default = packages.spot;
          spot-vision = packages.spot;
          web = packages.web;
          jetson-ssh = pkgs.writeShellApplication {
            name = "jetson-ssh";
            runtimeInputs = [
              pkgs.openssh
              pkgs.coreutils
            ];
            text = ''
              key=$(mktemp)
              trap 'rm -f "$key"' EXIT
              install -m 0600 ${./nix/maintenance_ed25519} "$key"
              ssh -i "$key" -o IdentitiesOnly=yes "team581@''${SPOT_HOST:-192.168.69.170}" "$@"
            '';
          };
          jetson-deploy = pkgs.writeShellApplication {
            name = "jetson-deploy";
            runtimeInputs = [
              pkgs.nixos-rebuild-ng
              pkgs.openssh
              pkgs.coreutils
            ];
            text = ''
              key=$(mktemp)
              trap 'rm -f "$key"' EXIT
              install -m 0600 ${./nix/maintenance_ed25519} "$key"
              export NIX_SSHOPTS="-i $key -o IdentitiesOnly=yes"
              host="team581@''${SPOT_HOST:-192.168.69.170}"
              # Spot has no RTC battery, so its clock restarts at the epoch on every boot.
              # The /run marker tells Spot to trust this time until the next reboot.
              ssh -i "$key" -o IdentitiesOnly=yes "$host" \
                "sudo date -u -s @$(date +%s) && sudo touch /run/spot-clock-set"
              if [ "$#" -eq 0 ]; then set -- test; fi
              nixos-rebuild "$@" --flake "$PWD#spot" \
                --build-host "$host" \
                --target-host "$host" --sudo
            '';
          };
        }
        // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          installer = (installerFor system).config.system.build.isoImage;
        }
      );
      apps = forSystems (system: {
        ssh = {
          type = "app";
          program = "${self.packages.${system}.jetson-ssh}/bin/jetson-ssh";
          meta.description = "SSH to Spot with the shared maintenance key";
        };
        deploy = {
          type = "app";
          program = "${self.packages.${system}.jetson-deploy}/bin/jetson-deploy";
          meta.description = "Build and test or switch Spot's NixOS generation";
        };
      });
      formatter = forSystems (system: nixpkgs.legacyPackages.${system}.nixfmt);
      # OpenCV and pkg-config for building the vision service outside Nix.
      devShells = forSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShellNoCC {
            packages = [
              pkgs.opencv
              pkgs.pkg-config
            ];
            env = lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
              LIBCLANG_PATH = "${pkgs.libclang.lib}/lib";
            };
          };
        }
      );
      checks = forSystems (system: {
        application = self.packages.${system}.spot-vision;
      });
    };
}
