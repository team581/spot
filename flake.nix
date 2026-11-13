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
          opencv = packages.opencv;
          web = packages.web;
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
              host="team581@''${SPOT_HOST:-10.5.81.11}"
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
        // lib.optionalAttrs pkgs.stdenv.hostPlatform.isDarwin {
          # Remote builder VM for building the Linux outputs on macOS.
          linux-builder = pkgs.darwin.linux-builder.override {
            modules = [
              # Only change the host-side VM settings, so the guest system stays
              # cached and the builder doesn't need a Linux builder to build.
              {
                virtualisation.cores = 8;
                virtualisation.darwin-builder = {
                  memorySize = 16 * 1024;
                  diskSize = 40 * 1024;
                };
              }
            ];
          };
        }
      );
      apps = forSystems (system: {
        deploy = {
          type = "app";
          program = "${self.packages.${system}.jetson-deploy}/bin/jetson-deploy";
          meta.description = "Build and test or switch Spot's NixOS generation";
        };
      });
      formatter = forSystems (system: nixpkgs.legacyPackages.${system}.nixfmt);
      checks = forSystems (system: {
        application = self.packages.${system}.spot-vision;
      });
    };
}
