{
  description = "Team 581 Spot vision appliance";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    jetpack = {
      url = "github:anduril/jetpack-nixos";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
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
    in
    {
      nixosModules.spot = import ./nix/module.nix;
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
              if [ "$#" -eq 0 ]; then set -- test; fi
              nixos-rebuild "$@" --flake "$PWD#spot" \
                --build-host "$host" \
                --target-host "$host" --sudo
            '';
          };
        }
        // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          installer = jetpack.packages.${system}.iso_minimal;
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
      checks = forSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          spot = self.packages.${system}.spot-vision;
        in
        {
          # Start with CPU processing and empty discovery even for a CUDA build.
          # This exercises the installed package without claiming GPU qualification.
          application = pkgs.runCommand "spot-installed-service" { } ''
            unset PYTHONPATH PYTHONHOME
            cd "$TMPDIR"
            ${spot}/bin/python ${./apps/vision/tests/installed_service.py} \
              --smoke${lib.optionalString (system == "aarch64-linux") "-cuda"} ${spot} "$TMPDIR"
            touch "$out"
          '';
        }
      );
    };
}
